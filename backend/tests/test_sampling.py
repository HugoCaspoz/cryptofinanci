import asyncio
from types import SimpleNamespace

import numpy as np

from app.capture_engine.source import Frame
from app.pipeline_engine.sampling import SmartSampler
from app.pipeline_engine.pipeline import FramePipeline
from app.pipeline_engine.processor import FrameProcessor
from test_pipeline import SyntheticSource, assert_accounted


def make_frame(t, value=0, image=None):
    return Frame(round(t * 10) + 1, t, np.full((100, 100, 3), value, np.uint8) if image is None else image, 10)


def test_static_gate_saves_eighty_percent():
    sampler = SmartSampler()
    selected = [i for i in range(100) if sampler.select(make_frame(i / 10))]
    assert selected == list(range(0, 100, 5))
    assert sampler.snapshot()["skipped_frames"] == 80


def test_five_fps_source_keeps_two_fps_average_without_duplicating_frames():
    sampler = SmartSampler()
    assert sum(sampler.select(make_frame(i / 5)) for i in range(50)) == 20


def test_change_bursts_for_two_seconds_then_returns_to_normal():
    sampler = SmartSampler()
    assert sampler.select(make_frame(0))
    assert not sampler.select(make_frame(.1, 2))  # compression noise
    assert sampler.select(make_frame(.2, 255))
    for i in range(3, 22):
        assert sampler.select(make_frame(i / 10, 255))
        assert sampler.target_fps == 10
    assert not sampler.select(make_frame(2.2, 255))
    assert sampler.target_fps == 2
    assert sampler.select(make_frame(2.6, 255))
    assert sampler.select(make_frame(2.7, 0))  # change bypasses normal cadence


def test_regions_ignore_background_and_detect_small_roi_change():
    roi = SimpleNamespace(x=10, y=10, width=20, height=20)
    layout = SimpleNamespace(width=100, height=100, players=[], regions=SimpleNamespace(
        hero_cards=roi, board=roi, pot=roi, dealer_button=roi))
    sampler = SmartSampler(layout)
    sampler.select(make_frame(0))
    image = np.zeros((100, 100, 3), np.uint8)
    image[70:90] = 255
    assert not sampler.select(make_frame(.1, image=image))
    image[10:30, 10:30] = 255
    assert sampler.select(make_frame(.2, image=image))
    assert sampler.target_fps == 10


def test_pipeline_skips_before_processor_and_preserves_queue_accounting():
    async def run():
        source = SyntheticSource(total=100)
        source.sampling_mode = "adaptive"
        source.start()
        processed = []
        pipeline = FramePipeline(source, FrameProcessor(), lambda result: processed.append(result.metadata))
        await pipeline.run()
        snapshot = pipeline.snapshot()
        assert_accounted(snapshot)
        assert snapshot["sampling"]["observed_frames"] == 100
        assert snapshot["sampling"]["skipped_frames"] == 98
        assert snapshot["captured_frames"] == len(processed) == 2
        assert FramePipeline(source, FrameProcessor(), lambda result: None).sampler.observed == 0
    asyncio.run(run())
