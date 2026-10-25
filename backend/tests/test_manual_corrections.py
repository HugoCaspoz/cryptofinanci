import asyncio
from dataclasses import asdict, replace
import os
import time
from uuid import uuid4

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Mode
from app.main import create_app
from app.game_state_engine import GameStateEngine
from app.game_state_engine.corrections import CorrectionRequest, corrected_game
from app.hand_reconstructor.store import HandStore
from app.pipeline_engine.pipeline import FramePipeline
from app.vision_engine import VisionObservation
from test_pipeline import SyntheticSource, GatedProcessor, wait_until, assert_accounted
from test_capture import make_video, wait_state
from app.capture_engine.file_source import FileVideoSource


def body(frame=1, revision=1, **patch):
    return {"id": str(uuid4()), "expected_frame_id": frame, "expected_revision": revision,
            "reason": "Lectura corregida", **patch}


def game():
    result = GameStateEngine()
    result.accept(VisionObservation(1, .1, 64, 32))
    return result


def test_manual_labels_seed_trackers_and_preserve_identity():
    original = game()
    value = CorrectionRequest(**body(hero_cards=["As", "Kd"], board=["2h", "3c", "4d"], players=[{
        "seat": 1, "nickname": "Hero", "stack": {"value": "100.25", "unit": "$"},
        "bet": {"value": "5.50", "unit": "$"}, "action": "ACTIVE"}]))
    changed, event = corrected_game(original, value)
    assert original.current_state.hero_cards == ()
    assert changed.current_state.scope_id == original.current_state.scope_id
    assert changed.current_state.hand_id == original.current_state.hand_id
    assert changed.current_state.hero_cards == ("As", "Kd") and changed.current_state.street == "flop"
    assert changed.current_state.players[0].stack == "100.25"
    assert changed.current_state.players[0].observed_action == "ACTIVE"
    assert changed.evidence["hero_cards"].source == changed.evidence["players.0.stack"].source == "manual"
    assert changed.ocr.fields["players.0.stack"].value == "100.25"
    assert event.type == "MANUAL_CORRECTION" and event.correction_id == str(value.id)
    assert changed.last_observation == original.last_observation
    # Unknown subsequent observations retain the corrected value, without claiming fresh evidence.
    changed.accept(VisionObservation(2, .2, 64, 32))
    assert changed.current_state.hero_cards == ("As", "Kd")
    assert changed.evidence["hero_cards"].status == "unknown"


@pytest.mark.parametrize("patch", [
    {"hero_cards": ["As"]}, {"hero_cards": ["As", "As"]},
    {"hero_cards": ["As", "Kd"], "board": ["As", "2h", "3c"]},
    {"board": ["2h", "3c"]}, {"board": ["bad", "3c", "4s"]},
    {"players": [{"seat": 7, "nickname": "x"}]},
    {"players": [{"seat": 1, "stack": {"value": "-1"}}]},
    {"players": [{"seat": 1, "stack": {"value": "NaN"}}]},
    {"players": [{"seat": 1, "nickname": "x"}, {"seat": 1, "action": "FOLD"}]},
    {"players": [{"seat": 1, "action": "ACTIVE"}, {"seat": 2, "action": "ACTIVE"}]},
    {"players": [{"seat": 1}]}, {},
])
def test_invalid_patch_does_not_mutate_state(patch):
    original = game()
    before = original.snapshot()
    with pytest.raises(ValueError):
        corrected_game(original, CorrectionRequest(**body(**patch)))
    assert original.snapshot() == before


def start_and_pause(client):
    started = client.post("/api/capture/screen", json={"capture_fps": 10}).json()
    identity = started["capture_id"]
    jpeg = cv2.imencode(".jpg", np.zeros((32, 64, 3), np.uint8))[1].tobytes()
    client.post(f"/api/capture/{identity}/screen-frame", content=jpeg)
    wait_state(client, lambda s: s["frame"] is not None)
    paused = client.post(f"/api/capture/{identity}/analysis/pause").json()
    return identity, paused, jpeg


def test_api_pause_atomic_dataset_idempotency_and_resume(monkeypatch):
    with TestClient(create_app()) as client:
        identity, paused, jpeg = start_and_pause(client)
        prefix = f"/api/capture/{identity}"
        frame = paused["frame"]["frame_id"]
        revision = paused["analysis_control"]["revision"]
        request = body(frame, revision, hero_cards=["As", "Kd"], players=[{
            "seat": 2, "nickname": "Villain", "stack": {"value": "99"}, "bet": {"value": "2"}, "action": "FOLD"}])
        before = client.app.state.capture.observation_state.snapshot()
        for _ in range(3):
            client.post(prefix + "/screen-frame", content=jpeg)
            time.sleep(.04)
        assert client.app.state.capture.observation_state.snapshot() == before
        store = client.app.state.hand_store
        save = store.save_correction
        def fail(*args):
            raise OSError("Storage unavailable")
        monkeypatch.setattr(store, "save_correction", fail)
        assert client.post(prefix + "/corrections", json=request).status_code == 503
        assert client.app.state.capture.observation_state.snapshot() == before
        assert store.corrections(identity, 0, 20) == []
        monkeypatch.setattr(store, "save_correction", save)
        changed = client.post(prefix + "/corrections", json=request)
        assert changed.status_code == 200
        assert changed.json()["capture_id"] == identity
        assert changed.json()["analysis_control"]["paused"] is True
        assert changed.json()["observation_state"]["game_state"]["players"][1]["folded"] is True
        assert client.post(prefix + "/corrections", json=request).status_code == 200
        assert client.post(prefix + "/corrections", json={**request, "reason": "different"}).status_code == 409
        assert client.post(prefix + "/corrections", json=body(frame, revision, board=[])).status_code == 409
        exported = client.get(prefix + "/corrections")
        assert exported.headers["cache-control"] == "no-store"
        records = exported.json()["records"]
        assert len(records) == 1 and records[0]["before"]["hero_cards"] == []
        assert records[0]["after"]["hero_cards"] == ["As", "Kd"]
        assert records[0]["observation"]["frame_id"] == frame
        image = client.get(prefix + f'/corrections/{request["id"]}/frame')
        assert image.status_code == 200 and image.headers["x-frame-id"] == str(frame)
        assert cv2.imdecode(np.frombuffer(image.content, np.uint8), cv2.IMREAD_COLOR).shape == (32, 64, 3)
        resumed = client.post(prefix + "/analysis/resume")
        assert resumed.status_code == 200 and not resumed.json()["analysis_control"]["paused"]
        assert client.post(prefix + "/corrections", json=request).status_code == 409
        client.post(prefix + "/screen-frame", content=jpeg)
        running = wait_state(client, lambda s: s["frame"]["frame_id"] > frame)
        assert running["capture_id"] == identity
        assert client.post(prefix + "/analysis/pause").status_code == 200
        assert client.post(prefix + "/analysis/resume").status_code == 200
        assert client.post(prefix + "/stop").status_code == 200
        assert client.post(prefix + "/analysis/resume").status_code == 409
        next_capture = client.post("/api/capture/screen", json={}).json()
        assert not next_capture["analysis_control"]["paused"]
        assert next_capture["analysis_control"]["revision"] == 0
        assert client.post(prefix + "/analysis/pause").status_code == 409
        assert len(client.get(prefix + "/corrections").json()["records"]) == 1


def test_pause_waits_for_native_processing_and_stop_wakes_paused_workers():
    async def run():
        source = SyntheticSource(total=100)
        source.start()
        processor = GatedProcessor()
        pipeline = FramePipeline(source, processor, lambda result: None)
        running = asyncio.create_task(pipeline.run())
        await wait_until(processor.started.is_set)
        paused = asyncio.create_task(pipeline.pause())
        await asyncio.sleep(.03)
        assert not paused.done()
        processor.release.set()
        await paused
        before = pipeline.snapshot()["processed_frames"]
        await asyncio.sleep(.04)
        assert pipeline.snapshot()["processed_frames"] == before
        assert_accounted(pipeline.snapshot())
        pipeline.request_stop()
        await asyncio.wait_for(running, 2)
        assert_accounted(pipeline.snapshot())
    asyncio.run(run())


def test_file_pause_does_not_advance_source_clock(tmp_path):
    clock = [0.0]
    source = FileVideoSource(make_video(tmp_path / "video.avi"), "video.avi", clock=lambda: clock[0])
    source.start()
    try:
        assert source.get_frame().timestamp == 0
        clock[0] = .2
        assert source.get_frame().timestamp == .2
        source.pause()
        clock[0] = 100
        assert source.get_frame() is None
        source.resume()
        clock[0] += .2
        assert .3 <= source.get_frame().timestamp <= .4
    finally:
        source.stop()


def test_correction_does_not_rewrite_or_reopen_frozen_decision(tmp_path):
    from test_decisions import setup, freeze, event_for
    from app.decision_engine.tracker import DecisionTracker
    from app.decision_engine.evaluation import resolve_action
    s, request = setup()
    tracker = DecisionTracker()
    snapshot = freeze(tracker, s, request)
    frozen_event = event_for(s, snapshot, request)
    store = HandStore(path=tmp_path / "archive.sqlite")
    store.initialize()
    store.save_decision(snapshot.record(), frozen_event)
    before = store.get_decision(snapshot.id)
    state = replace(request.state, players=tuple(replace(p, stack="999") if p.seat == 1 else p for p in request.state.players))
    event = s.bus.emit("MANUAL_CORRECTION", state, 100, 100,
                       correction_id=str(uuid4()), action_evidence=("manual_label",))
    record = {"id": event.correction_id, "capture_id": "capture", "scope_id": state.scope_id, "revision": 1}
    store.save_correction(record, event, None, b"jpeg")
    assert store.get_decision(snapshot.id) == before
    assert resolve_action(snapshot.record(), [event.model_dump(mode="json")])["link_status"] == "unavailable"
    assert freeze(tracker, s, replace(request, state=state, sequence=event.sequence)) is None
    assert tracker.active is None


@pytest.mark.skipif(not os.getenv("HAND_TEST_POSTGRES"), reason="Dedicated PostgreSQL database required")
def test_dataset_postgres_persists_labels_and_image():
    store = HandStore(database_url=os.environ["HAND_TEST_POSTGRES"])
    store.initialize()
    original = game()
    request = CorrectionRequest(**body(hero_cards=["As", "Kd"]))
    trial, event = corrected_game(original, request)
    identity = str(request.id)
    record = {"id": identity, "capture_id": uuid4().hex, "scope_id": original.current_state.scope_id,
              "revision": 1, "before": asdict(original.current_state), "after": asdict(trial.current_state)}
    store.save_correction(record, event, None, b"jpeg fixture")
    assert store.correction(identity)["after"]["hero_cards"] == ["As", "Kd"]
    assert store.correction(identity, image=True) == b"jpeg fixture"
