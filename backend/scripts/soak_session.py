"""Reproducible synthetic session. Accelerated by default; no OCR/EV benchmark.

Use --realtime for a real 2/4/8-hour synthetic run. Always creates its own SQLite DB.
"""
import argparse
import asyncio
from dataclasses import asdict
import gc
from hashlib import sha256
import json
from pathlib import Path
import sys
import shutil
import tempfile
import time
import tracemalloc
from uuid import uuid4

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.action_engine.vision import ActionObservation, ActionReading
from app.card_detector.models import Card, CardObservation, RegionReading
from app.capture_engine.source import Frame
from app.capture_engine.source import VideoSource, EndOfSource
from app.capture_engine.engine import CaptureEngine
from app.config import Mode
from app.game_state_engine import GameStateEngine
from app.game_state_engine.corrections import CorrectionRequest, corrected_game
from app.hand_reconstructor.store import HandStore
from app.opponent_model.engine import OpponentModel
from app.ocr_engine.models import OcrObservation, TextReading
from app.pipeline_engine.frame_queue import FrameQueue
from app.pipeline_engine.memory import process_rss_bytes
from app.pipeline_engine.metrics import PipelineMetrics
from app.pipeline_engine.sampling import SmartSampler
from app.pipeline_engine.temporal_buffer import TemporalBuffer
from app.poker_engine.models import PokerConfig, OpponentRange
from app.strategy_engine.engine import StrategyRequest
from app.strategy_engine.models import StrategyConfig
from app.vision_engine import VisionObservation
from app.websocket_engine.capture_hub import CaptureHub


def observation(frame, sampled):
    phase = frame.timestamp % 20
    visible = 3 <= phase < 15
    hero = RegionReading("known", (Card("A", "spades", 1), Card("K", "diamonds", 1))) if visible else RegionReading("empty")
    board = RegionReading("known", (Card("2", "hearts", 1), Card("3", "clubs", 1), Card("4", "diamonds", 1))) if 10 <= phase < 15 else RegionReading("empty")
    readings = [TextReading("pot", "amount", value="300" if 10 <= phase < 15 else "150" if visible else "0", confidence=1),
                TextReading("blinds", "blinds", value="50 / 100", confidence=1)]
    for i in range(6):
        readings.extend([TextReading(f"players.{i}.nickname", "nickname", value=f"P{i}_{int(frame.timestamp // 60)}", confidence=1),
            TextReading(f"players.{i}.stack", "amount", value="9900", confidence=1),
            TextReading(f"players.{i}.bet", "amount", value="50" if i == 0 else "100" if i == 1 else "0", confidence=1)])
    return VisionObservation(frame.frame_id, frame.timestamp, 96, 54, True,
        CardObservation("ready", "synthetic-soak", True, "synthetic", hero, board),
        OcrObservation("ready" if sampled else "not_sampled", sampled, tuple(readings) if sampled else (), "synthetic"),
        ActionObservation("ready", tuple(ActionReading("ACTIVE", 1) if i == 0 and (5 <= phase < 8 or 11 <= phase < 14)
                                       else ActionReading() for i in range(6))))


async def soak(hours, output_dir, realtime=False):
    output_dir.mkdir(parents=True, exist_ok=True)
    # Never accept a user database path or touch the main application's archive.
    temporary_db = tempfile.TemporaryDirectory(prefix="zeros-soak-db-")
    database = Path(temporary_db.name) / f"soak-{uuid4().hex}.sqlite3"
    store = HandStore(path=database)
    store.initialize()
    game, buffer, sampler, queue, metrics = GameStateEngine(), TemporalBuffer(30), SmartSampler(), FrameQueue(2), PipelineMetrics()
    model = OpponentModel(game.current_state.scope_id)
    capture_id = f"synthetic-soak-{uuid4().hex}"
    context = {"capture_id": capture_id, "mode": Mode.TRAINING, "source": "synthetic", "name": "Synthetic soak"}
    store.start_review_session(game.current_state.scope_id, capture_id, Mode.TRAINING, "SESSION_FINISHED")
    hub = CaptureHub()
    fast, slow = hub.subscribe(), hub.subscribe()
    config = PokerConfig(hero_seat=1, opponents=(OpponentRange(seat=2, range="AA"),), pot_includes_bets=True)
    records, events, samples = [], [], []
    last_ocr, correction_revision = -1, 0
    last_profile_revision = -1
    started = time.monotonic()
    tracemalloc.start()

    def flush():
        if records or events:
            store.save(records, events, context)
            records.clear()
            events.clear()

    async def process(frame):
        nonlocal game, last_ocr, last_profile_revision
        begin = time.monotonic()
        sequence = game.event_engine.replay.sequence
        sampled = frame.timestamp - last_ocr >= .5 - 1e-6
        if sampled:
            last_ocr = frame.timestamp
        game.accept(observation(frame, sampled))
        current_events = [e for e in game.event_engine.events if e.sequence > sequence]
        events.extend(current_events)
        records.extend(game.hands.pending_records)
        for event in current_events:
            model.consume(event)
            if event.type in {"HAND_STARTED", "HAND_FINISHED"}:
                saved = buffer.get(frame_id=frame.frame_id)
                identity = sha256(f"{capture_id}:{frame.frame_id}:{event.type}".encode()).hexdigest()
                store.save_important_frame({"id": identity, "capture_id": capture_id, "scope_id": game.current_state.scope_id,
                    "mode": Mode.TRAINING, "frame_id": frame.frame_id, "timestamp": frame.timestamp,
                    "kind": event.type.lower(), "hand_id": event.hand_id}, saved.jpeg)
        state = game.current_state
        request = StrategyRequest(state, config, StrategyConfig(), None, None, frame.frame_id, frame.timestamp, game.event_engine.replay.sequence)
        frozen = game.decisions.detect(request, mode=Mode.TRAINING, events=tuple(game.event_engine.events),
            evidence=game.evidence, opponents=None, preflop_config=None, running=True)
        if frozen:
            flush()
            event = game.event_engine.emit("HERO_DECISION_REQUIRED", state, frame.frame_id, frame.timestamp,
                player_id=state.current_player, decision_id=frozen.id)
            store.save_decision(frozen.record(), event, buffer.get(frame_id=frame.frame_id).jpeg)
            model.consume(event)
        if len(events) >= 64 or current_events and any(e.type == "HAND_FINISHED" for e in current_events):
            flush()
            if model.revision != last_profile_revision:
                store.save_opponents(model.snapshot() | {"mode": Mode.TRAINING})
                last_profile_revision = model.revision
        metrics.record_processed(frame.captured_at, begin, time.monotonic())
        hub.publish({"frame_id": frame.frame_id, "sequence": game.event_engine.replay.sequence})
        if not fast.empty():
            fast.get_nowait()

    steps = int(hours * 3600 * 10)
    for index in range(steps + 1):
        timestamp = index / 10
        if realtime:
            await asyncio.sleep(max(0, timestamp - (time.monotonic() - started)))
        image = np.full((54, 96, 3), int(timestamp % 20) * 8, np.uint8)
        frame = Frame(index + 1, timestamp, image, 10)
        buffer.append(frame)
        if sampler.select(frame):
            metrics.record_origin(frame.frame_id, frame.captured_at, 0)
            metrics.record_capture()
            queue.offer(frame)
        if index % 3 == 0 and len(queue):
            await process(await queue.take_latest())
        if index and index % 36000 == 0:
            flush()
            saved = buffer.get(frame_id=game.last_observation.frame_id)
            correction_revision += 1
            patch = CorrectionRequest(id=uuid4(), expected_frame_id=game.last_observation.frame_id,
                expected_revision=correction_revision, reason="Synthetic hourly label", players=[{"seat": 1, "nickname": "SyntheticLabel"}])
            trial, event = corrected_game(game, patch)
            store.save_correction({"id": str(patch.id), "capture_id": capture_id, "scope_id": game.current_state.scope_id,
                "revision": correction_revision, "mode": Mode.TRAINING, "frame_id": game.last_observation.frame_id,
                "before": asdict(game.current_state), "after": asdict(trial.current_state), "synthetic": True}, event, None, saved.jpeg)
            game = trial
            model.consume(event)
            store.save_important_frame({"id": uuid4().hex, "capture_id": capture_id, "scope_id": game.current_state.scope_id,
                "mode": Mode.TRAINING, "frame_id": frame.frame_id, "timestamp": timestamp, "kind": "processing_error",
                "error_type": "synthetic_probe"}, buffer.get(frame_id=frame.frame_id).jpeg)
            gc.collect()
            current, peak = tracemalloc.get_traced_memory()
            with store.connection() as db:
                counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in
                    ("observed_events", "observed_hands", "decision_snapshots", "important_frames", "manual_corrections", "opponent_profiles")}
            sample = {"source_hours": timestamp / 3600, "elapsed_real_seconds": round(time.monotonic() - started, 2),
                "python_current_bytes": current, "python_peak_bytes": peak, "process_rss_bytes": process_rss_bytes(),
                "buffer": buffer.snapshot(), "event_log": len(game.event_engine.events), "event_keys": len(game.event_engine._frame_keys),
                "profiles": len(model.profiles), "identities_created": model.identities_created,
                "decision_keys": len(game.decisions.seen), "recent_hands": len(game.hands.recent), "archive_rows": counts}
            samples.append(sample)
            print(json.dumps(sample), flush=True)
            assert sample["event_log"] <= 40 and sample["event_keys"] <= 40
            assert sample["profiles"] <= 128 and sample["decision_keys"] <= 512 and sample["recent_hands"] <= 20
            assert slow.qsize() == 1 and len(buffer.index()) <= 450 and buffer.snapshot()["bytes"] <= 64 * 1024 * 1024
    queue.close()
    if len(queue):
        await process(await queue.take_latest())
    flush()
    hub.unsubscribe(fast)
    hub.unsubscribe(slow)
    assert not hub.subscribers
    growth = samples[-1]["python_current_bytes"] - samples[0]["python_current_bytes"]
    assert growth < 16 * 1024 * 1024, f"Python heap growth after warmup: {growth}"
    assert samples[-1]["archive_rows"]["decision_snapshots"] > 0
    saved_database = output_dir / database.name
    shutil.copyfile(database, saved_database)
    report = {"synthetic": True, "realtime": realtime, "source_hours": hours,
        "elapsed_real_seconds": round(time.monotonic() - started, 2), "frames_inspected": steps + 1,
        "python_growth_after_one_hour_bytes": growth, "samples": samples,
        "database": str(saved_database), "limits_passed": True,
        "limitations": "Synthetic 96x54 frames and labeled observations; no OCR, native video, EV solver or browser heap benchmark."}
    (output_dir / "soak-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    tracemalloc.stop()
    temporary_db.cleanup()
    return report


async def real_pipeline(seconds, output_dir):
    """Short real-clock check of workers, JPEGs, capture lifecycle and release."""
    import threading
    class Source(VideoSource):
        kind, name, capture_fps, sampling_mode = "synthetic", "Synthetic real-clock soak", 10, "adaptive"
        duration = seconds
        def start(self):
            self.started, self.number = time.monotonic(), 0
        def stop(self):
            pass
        def get_frame(self):
            elapsed = time.monotonic() - self.started
            if elapsed >= seconds:
                raise EndOfSource
            self.number += 1
            return Frame(self.number, elapsed, np.full((360, 640, 3), self.number % 200, np.uint8), 10)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="zeros-real-soak-") as directory:
        store = HandStore(path=Path(directory) / "isolated.sqlite")
        store.initialize()
        engine = CaptureEngine(hand_store=store, mode=Mode.TRAINING, buffer_seconds=30)
        tracemalloc.start()
        await engine.start(Source())
        started, samples = time.monotonic(), []
        try:
            while engine.state == "running":
                await asyncio.sleep(min(10, seconds))
                gc.collect()
                current, peak = tracemalloc.get_traced_memory()
                status = engine.status()
                health = status["session_health"]
                for key, value in health["retained"].items():
                    assert value <= health["limits"][key], (key, value)
                sample = {"elapsed_real_seconds": round(time.monotonic() - started, 2),
                    "python_current_bytes": current, "python_peak_bytes": peak, "health": health,
                    "buffer": status["pipeline"]["buffer"], "processed_frames": status["pipeline"]["processed_frames"]}
                samples.append(sample)
                print(json.dumps(sample), flush=True)
            await engine._task
            assert engine.state == "ended"
            assert samples[-1]["processed_frames"] > 0
            if len(samples) >= 6:
                assert samples[-1]["python_current_bytes"] - samples[3]["python_current_bytes"] < 16 * 1024 * 1024
        finally:
            await engine.close()
            tracemalloc.stop()
        assert not any(t.name.startswith(("zeros-capture", "zeros-process")) for t in threading.enumerate())
        report = {"mode": "real_clock_pipeline", "requested_seconds": seconds, "samples": samples,
                  "workers_released": True, "limits_passed": True,
                  "limitations": "Synthetic 640x360 source, real capture workers and JPEG encoding, no OCR or EV calculations."}
        (output_dir / "pipeline-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, choices=[2, 4, 8], default=8)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--realtime", action="store_true")
    parser.add_argument("--pipeline-seconds", type=int, choices=range(1, 601), metavar="1..600")
    args = parser.parse_args()
    output = args.output_dir or Path(tempfile.mkdtemp(prefix="zeros-soak-"))
    if args.pipeline_seconds:
        asyncio.run(real_pipeline(args.pipeline_seconds, output))
    else:
        asyncio.run(soak(args.hours, output, args.realtime))
