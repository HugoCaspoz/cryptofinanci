import asyncio
import threading
import time
import weakref

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.capture_engine.engine import CaptureEngine
from app.capture_engine.source import EndOfSource, Frame, SourceError, VideoSource
from app.config import Mode, Settings
from app.game_state_engine import GameStateEngine
from app.main import create_app
from app.pipeline_engine.frame_queue import FrameQueue
from app.pipeline_engine.metrics import PipelineMetrics
from app.pipeline_engine.pipeline import FramePipeline
from app.pipeline_engine.processor import FrameProcessor
from app.vision_engine import VisionObservation


def frame(number):
    return Frame(number, number / 100, np.zeros((8, 8, 3), np.uint8), 100)


class SyntheticSource(VideoSource):
    kind = "file"
    name = "deterministic-test"
    capture_fps = 100

    def __init__(self, total=12, fail_at=None):
        self.total = total
        self.fail_at = fail_at
        self.count = 0
        self.closed = False

    def start(self):
        self.count = 0

    def get_frame(self):
        if self.count == self.fail_at:
            raise SourceError("Fallo de lectura de prueba")
        if self.count >= self.total:
            raise EndOfSource
        self.count += 1
        return frame(self.count)

    def stop(self):
        self.closed = True


class GatedProcessor(FrameProcessor):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def process(self, item):
        self.started.set()
        if not self.release.wait(4):
            raise RuntimeError("Test did not release its processor")
        return super().process(item)


async def wait_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.005)


def assert_accounted(metrics):
    assert metrics["captured_frames"] == sum(metrics[key] for key in (
        "processed_frames", "dropped_frames", "discarded_frames", "failed_frames", "queue_size", "in_flight",
    ))


def test_queue_evicts_oldest_and_consumer_takes_latest_without_retaining_history():
    async def scenario():
        queue = FrameQueue(2)
        references = []
        for number in range(10000):
            item = frame(number)
            references.append(weakref.ref(item))
            queue.offer(item)
        assert len(queue) == queue.high_watermark == 2
        assert sum(reference() is not None for reference in references) == 2
        latest = await queue.take_latest()
        assert latest.frame_id == 9999
        assert queue.dropped == 9999
        assert len(queue) == 0
        queue.close()
        assert await queue.take_latest() is None
        with pytest.raises(RuntimeError):
            queue.offer(frame(10000))
    asyncio.run(scenario())


def test_close_wakes_an_empty_consumer_and_discards_pending_frames():
    async def scenario():
        queue = FrameQueue()
        waiting = asyncio.create_task(queue.take_latest())
        await asyncio.sleep(0)
        queue.close(discard=True)
        assert await asyncio.wait_for(waiting, 1) is None
        pending = FrameQueue()
        pending.offer(frame(1))
        pending.close(discard=True)
        assert pending.discarded == 1
        assert await pending.take_latest() is None
    asyncio.run(scenario())


def test_slow_processor_does_not_block_capture_and_eof_drains_newest():
    async def scenario():
        source = SyntheticSource()
        processor = GatedProcessor()
        published = []
        pipeline = FramePipeline(source, processor, lambda result: published.append(result.metadata["frame_id"]))
        source.start()
        task = asyncio.create_task(pipeline.run())
        try:
            await wait_until(lambda: processor.started.is_set())
            await wait_until(lambda: pipeline.eof)
            metrics = pipeline.snapshot()
            assert metrics["captured_frames"] == 12
            assert metrics["processed_frames"] == 0
            assert metrics["in_flight"] == 1
            assert metrics["queue_size"] == metrics["queue_high_watermark"] == 2
            assert_accounted(metrics)
        finally:
            processor.release.set()
        await asyncio.wait_for(task, 2)
        assert published == [1, 12]
        metrics = pipeline.snapshot()
        assert metrics["processed_frames"] == 2 and metrics["dropped_frames"] == 10
        assert metrics["active"] is False and metrics["queue_size"] == 0
        assert metrics["frame_latency_ms"] >= metrics["processing_latency_ms"]
        assert_accounted(metrics)
        source.stop()
    asyncio.run(scenario())


def test_stop_waits_for_inflight_work_without_publishing_and_restart_resets_state():
    async def scenario():
        processor = GatedProcessor()
        engine = CaptureEngine(processor_factory=lambda: processor)
        source = SyntheticSource(total=200)
        try:
            original = await engine.start(source)
            await wait_until(lambda: engine.pipeline.metrics.captured_frames >= 5)
            stopping = asyncio.create_task(engine.stop())
            await asyncio.sleep(0.03)
            assert not stopping.done() and not source.closed
            processor.release.set()
            stopped = await asyncio.wait_for(stopping, 2)
            assert source.closed and stopped["frame"] is None
            assert stopped["observation_state"]["observations_seen"] == 0
            assert stopped["pipeline"]["discarded_frames"] > 0
            assert_accounted(stopped["pipeline"])
            engine.processor_factory = FrameProcessor
            restarted = await engine.start(SyntheticSource(total=3))
            assert restarted["capture_id"] != original["capture_id"]
            assert restarted["pipeline"]["captured_frames"] == 0
            assert restarted["observation_state"]["last_frame_id"] is None
            await wait_until(lambda: engine.state == "ended")
            final = engine.status()
            assert final["frame"]["frame_id"] == 3
            assert final["observation_state"]["observations_seen"] == final["pipeline"]["processed_frames"]
            assert_accounted(final["pipeline"])
        finally:
            processor.release.set()
            await engine.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["capture", "processing"])
def test_worker_failure_stops_the_other_worker_and_releases_source(stage):
    class BrokenProcessor(FrameProcessor):
        def process(self, item):
            raise RuntimeError("Intentional processing failure")

    async def scenario():
        engine = CaptureEngine(processor_factory=BrokenProcessor if stage == "processing" else FrameProcessor)
        source = SyntheticSource(total=200, fail_at=2 if stage == "capture" else None)
        try:
            await engine.start(source)
            await wait_until(lambda: engine.state == "error")
            assert source.closed
            state = engine.status()
            assert state["error"]
            assert state["pipeline"]["queue_size"] == 0
            assert state["pipeline"]["active"] is False
            assert state["pipeline"]["in_flight"] == 0
            assert state["pipeline"]["failed_frames"] == (1 if stage == "processing" else 0)
            assert_accounted(state["pipeline"])
        finally:
            await engine.close()
    asyncio.run(scenario())


def test_metrics_use_monotonic_window_and_bounded_sample_storage():
    now = [0.0]
    metrics = PipelineMetrics(clock=lambda: now[0])
    metrics.active = True
    queue = FrameQueue()
    for index in range(25):
        now[0] = index / 5
        metrics.record_capture()
    now[0] = 5
    metrics.record_processed(4.0, 4.1, 4.3)
    state = metrics.snapshot(queue)
    assert state["capture_fps"] == pytest.approx(4.8)
    assert state["processing_latency_ms"] == 200
    assert state["queue_wait_ms"] == 100
    assert state["frame_latency_ms"] == 300
    now[0] = 11
    assert metrics.snapshot(queue)["capture_fps"] == 0
    assert metrics.snapshot(queue)["processing_fps"] == 0
    for index in range(10000):
        now[0] += .2
        metrics.record_capture()
        metrics.record_processed(now[0], now[0], now[0])
    assert len(metrics._captures) <= metrics.MAX_RATE_SAMPLES
    assert len(metrics._processed) <= metrics.MAX_RATE_SAMPLES
    assert len(metrics._latencies) == metrics.MAX_LATENCY_SAMPLES
    metrics.active = False
    assert metrics.snapshot(queue)["capture_fps"] == 0


def test_api_stays_responsive_while_processing_is_blocked(monkeypatch):
    processor = GatedProcessor()
    monkeypatch.setattr("app.main.CaptureEngine", lambda queue_size, processor_factory, **kwargs: CaptureEngine(queue_size, lambda: processor, **kwargs))
    jpeg = cv2.imencode(".jpg", np.zeros((16, 16, 3), np.uint8))[1].tobytes()
    with TestClient(create_app()) as client:
        try:
            result = client.post("/api/capture/screen", json={"capture_fps": 15}).json()
            url = f'/api/capture/{result["capture_id"]}/screen-frame'
            client.post(url, content=jpeg)
            assert processor.started.wait(2)
            assert client.get("/health").status_code == 200
            for _ in range(3):
                assert client.post(url, content=jpeg).status_code == 204
                time.sleep(.09)
            state = client.get("/api/capture").json()
            assert state["pipeline"]["captured_frames"] >= 3
            assert state["pipeline"]["processed_frames"] == 0
            assert state["pipeline"]["queue_size"] <= 2
            assert_accounted(state["pipeline"])
        finally:
            processor.release.set()


def test_observation_sink_rejects_duplicates_without_inventing_poker_state():
    state = GameStateEngine()
    observation = VisionObservation(1, 0.0, 160, 90)
    state.accept(observation)
    with pytest.raises(ValueError):
        state.accept(observation)
    snapshot = state.snapshot()
    assert snapshot["recognition_available"] is False
    assert snapshot["observations_seen"] == 1 and snapshot["last_frame_id"] == 1
    assert snapshot["cards"]["hero"]["cards"] == []
    assert snapshot["cards"]["events"] == []


@pytest.mark.parametrize("capacity", [0, 9])
def test_queue_configuration_rejects_unbounded_or_excessive_capacity(capacity):
    with pytest.raises(ValueError):
        Settings(mode=Mode.TRAINING, frame_queue_size=capacity)
    with pytest.raises(ValueError):
        FrameQueue(capacity)
