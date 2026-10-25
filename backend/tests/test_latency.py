import asyncio
from dataclasses import replace
from math import inf, nan
from types import SimpleNamespace

import pytest

from app.capture_engine.engine import CaptureEngine
from app.config import Mode
from app.pipeline_engine.latency import LatencyWindow
from app.pipeline_engine.metrics import PipelineMetrics
from app.pipeline_engine.pipeline import FramePipeline
from app.pipeline_engine.processor import FrameProcessor
from app.vision_engine import VisionObservation
from test_pipeline import SyntheticSource, frame, assert_accounted, wait_until


def test_bounded_window_nearest_rank_p95_strict_goals_and_invalid_samples():
    window = LatencyWindow(50)
    assert window.snapshot()["within_target"] is None
    for value in range(1, 101):
        window.add(value, value)
    result = window.snapshot()
    assert result["p95_ms"] == 95 and result["mean_ms"] == 50.5
    assert result["within_target"] is False and result["frame_id"] == 100
    for value in [nan, inf, -1, None]: window.add(value)
    assert window.snapshot() == result
    for value in range(10000): window.add(value, value)
    assert window.snapshot()["samples"] == 128
    assert window.snapshot()["total_samples"] == 10100
    boundary = LatencyWindow(50)
    boundary.add(50)
    assert boundary.snapshot()["within_target"] is False
    boundary = LatencyWindow(50)
    boundary.add(49.99)
    assert boundary.snapshot()["within_target"] is True


def test_analysis_uses_origin_of_its_own_frame_and_evicted_origins_are_unknown():
    metrics = PipelineMetrics(clock=lambda: 1.)
    metrics.record_origin(1, 10., 20.)
    metrics.record_origin(2, 11., 10.)
    metrics.record_analysis("strategy", 1, 25., 12.)
    assert metrics.latencies["strategy"].snapshot()["last_ms"] == 25
    assert metrics.latencies["strategy_total"].snapshot()["last_ms"] == 2020
    assert metrics.latencies["strategy_total"].snapshot()["frame_id"] == 1
    for number in range(3, 10000): metrics.record_origin(number, 10. + number, 2.)
    assert len(metrics.origins) == 128
    metrics.record_analysis("strategy", 1, 40., 10010.)
    assert metrics.latencies["strategy"].snapshot()["total_samples"] == 2
    assert metrics.latencies["strategy_total"].snapshot()["total_samples"] == 1


def test_processor_splits_observation_and_preview_using_monotonic_clock(monkeypatch):
    clock = iter([1., 1.25, 1.27])
    monkeypatch.setattr("app.pipeline_engine.processor.monotonic", lambda: next(clock))
    vision = SimpleNamespace(observe=lambda item: VisionObservation(item.frame_id, item.timestamp, 8, 8))
    result = FrameProcessor(vision).process(frame(3))
    assert result.timings["vision"] == pytest.approx(250)
    assert result.timings["preview"] == pytest.approx(20)
    assert result.metadata["frame_id"] == 3 and result.jpeg


def test_completed_callback_sees_consistent_current_frame_metrics():
    async def run():
        source = SyntheticSource(total=3)
        source.start()
        snapshots = []
        async def publish(result):
            return {"state": 1.25}
        pipeline = FramePipeline(source, FrameProcessor(), publish, on_processed=lambda: snapshots.append(pipeline.snapshot()))
        await pipeline.run()
        assert len(snapshots) == 3
        for number, snapshot in enumerate(snapshots, 1):
            assert snapshot["processed_frames"] == number and snapshot["in_flight"] == 0
            assert_accounted(snapshot)
            for stage in ["capture", "vision", "preview", "state", "publish", "total_backend"]:
                assert snapshot["latencies"][stage]["last_ms"] >= 0
                if stage == "capture":
                    # Capture is independent and can already be ahead of processing.
                    assert snapshot["latencies"][stage]["frame_id"] >= number
                else:
                    assert snapshot["latencies"][stage]["frame_id"] == number
            assert snapshot["latencies"]["state"]["last_ms"] == 1.25
        source.stop()
    asyncio.run(run())


def test_capture_rejects_previous_scope_timings_and_resets_samples_on_restart():
    async def run():
        engine = CaptureEngine(mode=Mode.TRAINING)
        try:
            await engine.start(SyntheticSource(total=2))
            await wait_until(lambda: engine.state == "ended")
            scope = engine.observation_state.current_state.scope_id
            engine._analysis_timing("another-capture", 1, "strategy", 20)
            assert engine.status()["pipeline"]["latencies"]["strategy"]["samples"] == 0
            engine._analysis_timing(scope, 1, "strategy", 20)
            assert engine.status()["pipeline"]["latencies"]["strategy"]["last_ms"] == 20
            assert engine.status()["pipeline"]["latencies"]["state"]["samples"] == 2
            await engine.start(SyntheticSource(total=2))
            assert engine.status()["pipeline"]["latencies"]["state"]["samples"] == 0
            engine._analysis_timing(scope, 1, "strategy", 99)
            assert engine.status()["pipeline"]["latencies"]["strategy"]["samples"] == 0
            await wait_until(lambda: engine.state == "ended")
        finally:
            await engine.close()
    asyncio.run(run())


@pytest.mark.parametrize("mode", list(Mode))
def test_ready_strategy_reports_only_timing_even_when_results_are_private(mode):
    from app.decision_engine.tracker import DecisionTracker
    from app.strategy_engine.strategy_service import StrategyService
    from test_decisions import setup, freeze
    async def run():
        s, request = setup()
        frozen = freeze(DecisionTracker(), s, request, mode=mode)
        timings = []
        service = StrategyService(mode, lambda: None, on_timing=lambda *args: timings.append(args))
        service.submit(request.state, request.poker, request.decision, request.preflop,
            request.frame_id, request.timestamp, request.sequence, decision_snapshot=frozen)
        await service.task
        assert len(timings) == 1
        scope, number, kind, milliseconds = timings[0]
        assert scope == request.state.scope_id and number == request.frame_id
        assert kind == "strategy" and milliseconds >= 0
        if mode == Mode.LIVE_REAL_MONEY:
            assert service.snapshot()["result"] is None
        await service.close()
    asyncio.run(run())
