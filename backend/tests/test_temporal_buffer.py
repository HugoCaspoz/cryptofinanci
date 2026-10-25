import asyncio
import weakref

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.capture_engine.source import Frame
from app.config import Settings, Mode
from app.main import create_app
from app.pipeline_engine.temporal_buffer import TemporalBuffer
from app.pipeline_engine.pipeline import FramePipeline
from app.pipeline_engine.processor import FrameProcessor
from test_pipeline import SyntheticSource, GatedProcessor, wait_until


def frame(number, timestamp=None):
    return Frame(number, number if timestamp is None else timestamp,
                 np.full((32, 64, 3), number % 255, np.uint8), 10)


def test_time_window_boundaries_and_lookup_never_select_future():
    buffer = TemporalBuffer(10)
    for i in range(31):
        buffer.append(frame(i))
    assert [f["frame_id"] for f in buffer.index()] == list(range(20, 31))
    assert buffer.get(timestamp=20).frame_id == 20
    assert buffer.get(timestamp=20.9).frame_id == 20
    assert buffer.get(timestamp=19.9) is None
    assert buffer.get(timestamp=31) is None
    assert buffer.get(timestamp=float("nan")) is None
    assert buffer.get(frame_id=19) is None
    assert buffer.snapshot()["evicted_frames"] == 20


def test_memory_count_limits_and_immutable_original_resolution():
    buffer = TemporalBuffer(30, max_frames=3)
    for i in range(5):
        item = frame(i, i / 10)
        buffer.append(item)
    reference = weakref.ref(item.image)
    saved = buffer.get(frame_id=4)
    item.image[:] = 255
    del item
    assert reference() is None
    decoded = cv2.imdecode(np.frombuffer(saved.jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (32, 64, 3) and decoded.mean() < 5
    assert [f["frame_id"] for f in buffer.index()] == [2, 3, 4]
    limited = TemporalBuffer(max_bytes=len(saved.jpeg) * 2, max_frames=50)
    for i in range(20):
        limited.append(frame(i, i / 10))
        assert limited.snapshot()["bytes"] <= limited.max_bytes
    tiny = TemporalBuffer(max_bytes=1)
    tiny.append(frame(1))
    assert tiny.snapshot()["frames"] == tiny.snapshot()["bytes"] == 0
    buffer.clear()
    assert buffer.snapshot()["frames"] == buffer.snapshot()["bytes"] == 0


def test_duplicate_out_of_order_and_encoding_failure(monkeypatch):
    buffer = TemporalBuffer()
    buffer.append(frame(3))
    buffer.append(frame(2))
    buffer.append(frame(3))
    buffer.append(frame(4, 2))
    assert len(buffer.index()) == 1
    monkeypatch.setattr(cv2, "imencode", lambda *args: (False, None))
    buffer.append(frame(4))
    assert buffer.snapshot()["encoding_failures"] == 1
    assert len(buffer.index()) == 1


@pytest.mark.parametrize("seconds", [9, 31])
def test_configuration_bounds(seconds):
    with pytest.raises(ValueError):
        TemporalBuffer(seconds)
    with pytest.raises(ValueError):
        Settings(mode=Mode.TRAINING, frame_buffer_seconds=seconds)


def test_buffer_includes_frames_skipped_by_sampler():
    async def run():
        source = SyntheticSource(total=20)
        source.sampling_mode = "adaptive"
        source.start()
        pipeline = FramePipeline(source, FrameProcessor(), lambda result: None)
        await pipeline.run()
        assert pipeline.snapshot()["sampling"]["skipped_frames"] == 19
        assert len(pipeline.buffer.index()) == 20
        assert pipeline.buffer.get(frame_id=10).frame_id == 10
    asyncio.run(run())


def test_buffer_retains_images_discarded_by_processing_queue():
    async def run():
        source = SyntheticSource(total=20)
        source.start()
        processor = GatedProcessor()
        pipeline = FramePipeline(source, processor, lambda result: None)
        task = asyncio.create_task(pipeline.run())
        await wait_until(lambda: source.count == 20)
        processor.release.set()
        await task
        assert pipeline.snapshot()["dropped_frames"] > 0
        assert len(pipeline.buffer.index()) == 20
        assert pipeline.buffer.get(frame_id=2).frame_id == 2
    asyncio.run(run())


def test_api_retention_lookup_and_scope_reset():
    with TestClient(create_app()) as client:
        result = client.post("/api/capture/screen", json={"sampling_mode": "adaptive"}).json()
        identity = result["capture_id"]
        buffer = client.app.state.capture.pipeline.buffer
        for i in range(15):
            buffer.append(frame(i))
        prefix = f"/api/capture/{identity}/buffer"
        index = client.get(prefix)
        assert index.headers["cache-control"] == "no-store"
        assert index.json()["frames"][0]["frame_id"] == 4
        response = client.get(prefix + "/frame?timestamp=7.9")
        assert response.status_code == 200
        assert response.headers["x-frame-id"] == "7"
        assert response.headers["x-frame-timestamp"] == "7"
        assert response.headers["cache-control"] == "no-store"
        assert cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR).shape == (32, 64, 3)
        for suffix in ["/frames/1", "/frame?timestamp=3.9", "/frame?timestamp=15"]:
            assert client.get(prefix + suffix).status_code == 404
        for value in ["nan", "inf", "-1"]:
            assert client.get(prefix + "/frame?timestamp=" + value).status_code == 422
        client.post(f"/api/capture/{identity}/stop")
        assert client.get(prefix + "/frames/7").status_code == 200
        next_capture = client.post("/api/capture/screen", json={}).json()
        assert next_capture["pipeline"]["buffer"]["frames"] == 0
        assert client.get(prefix).status_code == 409
        assert client.get(prefix + "/frames/7").status_code == 409
