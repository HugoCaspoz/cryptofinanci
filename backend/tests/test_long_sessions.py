import asyncio
from dataclasses import replace
import os
from uuid import uuid4

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.capture_engine.engine import CaptureEngine
from app.config import Mode
from app.event_engine.engine import EventEngine
from app.game_state_engine.models import GameState, PlayerState
from app.hand_reconstructor.store import HandStore
from app.main import create_app
from app.opponent_model.engine import OpponentModel
from app.pipeline_engine.processor import FrameProcessor, ProcessedFrame
from test_capture import wait_state
from test_pipeline import SyntheticSource


def initial():
    return GameState(uuid4().hex, tuple(PlayerState(f"p{i}", i, nickname=f"P{i}") for i in range(1, 7)))


def test_thousands_of_same_frame_corrections_bound_all_event_references():
    state = initial()
    engine = EventEngine(state)
    for i in range(10000):
        engine.emit("MANUAL_CORRECTION", state, 1, 0, correction_id=str(uuid4()))
    assert len(engine.events) == len(engine._frame_keys) == 40
    assert engine.checkpoint.sequence == 9960
    assert engine.replay.sequence == 10000
    assert engine.export()["gap"] is True


def test_identity_churn_evicts_inactive_profiles_without_stopping_or_reusing_ids():
    state, model = initial(), OpponentModel("scope")
    for i in range(1000):
        state = replace(state, players=tuple(replace(p, nickname=f"P{p.seat}_{i}") for p in state.players))
        model.identities(state)
        assert len(model.profiles) <= 128
        assert all(model.profiles[key]["active"] for key in model.active.values())
    assert model.identities_created == 6000
    assert model.snapshot()["evicted_profiles"] == 6000 - 128
    assert len(set(model.active.values())) == 6


def test_pending_showdown_profiles_remain_pinned_during_churn():
    state, model = initial(), OpponentModel("scope")
    model.identities(state)
    protected = dict(model.active)
    model.pending_showdowns.append({"hand_id": "h", "profiles": protected, "saw_flop": [1, 2], "remaining": [1, 2]})
    for i in range(200):
        state = replace(state, players=tuple(replace(p, nickname=f"P{p.seat}_{i}") for p in state.players))
        model.identities(state)
    assert all(key in model.profiles for key in protected.values())
    model.confirm_showdown("h")
    assert model.profiles[protected[1]]["counts"]["wtsd"] == [1, 1]


def test_old_profiles_survive_eviction_in_paged_sql_archive(tmp_path):
    store = HandStore(path=tmp_path / "profiles.sqlite")
    store.initialize()
    state, model = initial(), OpponentModel("scope")
    for i in range(30):
        state = replace(state, players=tuple(replace(p, nickname=f"P{p.seat}_{i}") for p in state.players))
        model.identities(state)
        record = model.snapshot() | {"mode": Mode.TRAINING}
        store.save_opponents(record)
        if i == 0:
            old_record = record
    store.save_opponents(old_record)
    first = store.list_opponent_profiles("scope", Mode.TRAINING, 100)
    second = store.list_opponent_profiles("scope", Mode.TRAINING, 100, 100)
    assert len(first) + len(second) == 180
    assert len([p for p in first + second if p["active"]]) == 6
    assert all(p["nickname"].endswith("_29") for p in first + second if p["active"])
    assert any(p["nickname"] == "P1_0" for p in first + second)
    assert store.list_opponent_profiles("scope", Mode.LIVE_REAL_MONEY) == []


def test_decision_turn_keys_abstain_at_limit_without_forgetting_deduplication():
    from test_decisions import setup, freeze
    from app.decision_engine.tracker import DecisionTracker
    stream, request = setup()
    tracker = DecisionTracker()
    assert freeze(tracker, stream, request) is not None
    tracker.seen = {f"old-{i}" for i in range(tracker.MAX_TURN_KEYS)}
    assert freeze(tracker, stream, request) is None
    assert len(tracker.seen) == 512
    assert "Límite" in tracker.reason


def test_error_image_is_archived_and_normal_frames_are_not():
    class Broken(FrameProcessor):
        def process(self, frame):
            raise RuntimeError("synthetic failure")
    with TestClient(create_app()) as client:
        capture = client.app.state.capture
        identity = client.post("/api/capture/screen", json={}).json()["capture_id"]
        jpeg = cv2.imencode(".jpg", np.zeros((32, 64, 3), np.uint8))[1].tobytes()
        client.post(f"/api/capture/{identity}/screen-frame", content=jpeg)
        wait_state(client, lambda s: s["frame"] is not None)
        assert client.get(f"/api/capture/{identity}/important-frames").json()["items"] == []
        client.post(f"/api/capture/{identity}/stop")
        capture.processor_factory = Broken
        identity = client.post("/api/capture/screen", json={}).json()["capture_id"]
        client.post(f"/api/capture/{identity}/screen-frame", content=jpeg)
        stopped = wait_state(client, lambda s: s["state"] == "error")
        prefix = f"/api/capture/{identity}/important-frames"
        response = client.get(prefix)
        assert response.headers["cache-control"] == "no-store"
        rows = response.json()["items"]
        assert len(rows) == 1 and rows[0]["kind"] == "processing_error"
        assert rows[0]["error_type"] == "vision:RuntimeError"
        image = client.get(prefix + "/" + rows[0]["id"])
        assert image.headers["cache-control"] == "no-store"
        assert cv2.imdecode(np.frombuffer(image.content, np.uint8), cv2.IMREAD_COLOR).shape == (32, 64, 3)
        assert stopped["session_health"]["important_frames_saved"] == 1
        for key, count in stopped["session_health"]["retained"].items():
            assert count <= stopped["session_health"]["limits"][key]
        assert client.get(prefix + "?limit=101").status_code == 422
        assert client.get(f"/api/capture/wrong/important-frames/{rows[0]['id']}").status_code == 404


def test_boundaries_saved_selectively_and_failed_image_write_retries(tmp_path, monkeypatch):
    from scripts.soak_session import observation
    from app.capture_engine.source import Frame
    store = HandStore(path=tmp_path / "boundaries.sqlite")
    store.initialize()
    async def run():
        capture = CaptureEngine(hand_store=store, mode=Mode.TRAINING)
        capture.capture_id = "synthetic"
        capture.source = SyntheticSource()
        jpeg = cv2.imencode(".jpg", np.zeros((54, 96, 3), np.uint8))[1].tobytes()
        for i in range(41):
            frame = Frame(i + 1, i / 2, np.zeros((54, 96, 3), np.uint8), 2)
            result = ProcessedFrame({"frame_id": i + 1, "timestamp": i / 2}, jpeg, observation(frame, True))
            await capture._publish(result)
        rows = store.important_frames("synthetic", Mode.TRAINING)["items"]
        assert {r["kind"] for r in rows} == {"hand_started", "hand_finished"}
        assert len(rows) == 2 and all(r["hand_id"] for r in rows)
        save = store.save_important_frame
        def fail(*args):
            raise OSError("synthetic disk failure")
        monkeypatch.setattr(store, "save_important_frame", fail)
        with pytest.raises(OSError):
            await capture._archive_frame({"frame_id": 100, "timestamp": 50}, "processing_error", jpeg)
        assert len(capture.pending_important) == 1
        monkeypatch.setattr(store, "save_important_frame", save)
        await capture._flush_important()
        assert not capture.pending_important
        assert len(store.important_frames("synthetic", Mode.TRAINING)["items"]) == 3
        await capture.close()
    asyncio.run(run())


def test_slow_subscriber_is_latest_only_and_disconnects_release_queues():
    from app.websocket_engine.capture_hub import CaptureHub
    hub = CaptureHub()
    for _ in range(200):
        subscriber = hub.subscribe()
        for i in range(100):
            hub.publish({"value": i})
        assert subscriber.qsize() == 1 and subscriber.get_nowait() == {"value": 99}
        hub.unsubscribe(subscriber)
    assert not hub.subscribers


def test_large_legacy_migration_stays_conservative_and_strategy_lookup_pages(tmp_path):
    import json
    from dataclasses import asdict
    store = HandStore(path=tmp_path / "legacy.sqlite")
    store.initialize()
    state = asdict(initial())
    with store.connection() as db:
        for i in range(620):
            scope = "training" if i < 310 else "mixed"
            mode = "TRAINING" if i < 619 else "LIVE_REAL_MONEY"
            record = {"context": {"capture_id": scope, "mode": mode}, "state": state, "status": "finished"}
            db.execute("INSERT INTO observed_hands(hand_id,scope_id,status,started_at,created_at,payload) VALUES (?,?,?,?,?,?)",
                       (f"h{i:04}", scope, "finished", i, "today", json.dumps(record)))
        for i in range(205):
            payload = {"mode": "TRAINING", "scope_id": "s", "input": {"decision_snapshot_id": "target" if i == 204 else "other"},
                       "result": {"value": i}}
            db.execute("INSERT INTO strategy_results(id,hand_id,scope_id,frame_id,payload) VALUES (?,?,?,?,?)",
                       (f"id{i:04}", "h", "s", 1, json.dumps(payload)))
    store.initialize()
    assert store.review_session("training")["status"] == "interrupted"
    assert store.review_session("mixed") is None
    result = store.get_decision_strategy({"id": "target", "hand_id": "h", "scope_id": "s", "frame_id": 1, "mode": "TRAINING"})
    assert result == {"value": 204}


@pytest.mark.skipif(not os.getenv("HAND_TEST_POSTGRES"), reason="Dedicated PostgreSQL database required")
def test_selective_archive_postgres_idempotency_and_mode_separation():
    store = HandStore(database_url=os.environ["HAND_TEST_POSTGRES"])
    store.initialize()
    capture_id = uuid4().hex
    record = {"id": uuid4().hex, "capture_id": capture_id, "scope_id": capture_id, "mode": Mode.TRAINING,
              "frame_id": 1, "kind": "processing_error"}
    store.save_important_frame(record, b"jpeg")
    store.save_important_frame(record, b"different")
    assert len(store.important_frames(capture_id, Mode.TRAINING)["items"]) == 1
    assert store.important_frame(record["id"], capture_id, Mode.TRAINING) == b"jpeg"
    assert store.important_frame(record["id"], capture_id, Mode.LIVE_REAL_MONEY) is None

    latest = {"scope_id": capture_id, "revision": 2, "mode": Mode.TRAINING,
              "profiles": [{"id": capture_id + ":p", "active": True, "nickname": "new"}]}
    store.save_opponents(latest)
    store.save_opponents(latest | {"revision": 1, "profiles": [{"id": capture_id + ":p", "active": True, "nickname": "old"}]})
    assert store.list_opponent_profiles(capture_id, Mode.TRAINING)[0]["nickname"] == "new"
