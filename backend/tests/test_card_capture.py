import time

import cv2
import pytest
from fastapi.testclient import TestClient

from app.card_detector.demo import render_table
from app.config import Mode, Settings
from app.main import create_app
from app.table_detector.store import LayoutStore


@pytest.mark.parametrize("mode", list(Mode))
def test_real_video_pipeline_publishes_cards_and_deduplicated_events(tmp_path, mode):
    path = tmp_path / "cards.avi"
    layout = LayoutStore().read()[0]
    # Each street must remain visible long enough for three processed frames,
    # including on hosts where the bounded queue legitimately drops frames.
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 5, (1920, 1080))
    assert writer.isOpened()
    boards = [(), ("Js", "7c", "4d"), ("Js", "7c", "4d", "2h"), ("Js", "7c", "4d", "2h", "Tc")]
    for board in boards:
        image = render_table(layout, ("As", "Jh"), board)
        for _ in range(15):
            writer.write(image)
    writer.release()
    with TestClient(create_app(Settings(mode=mode))) as client:
        response = client.post("/api/capture/file", files={"file": ("cards.avi", path.read_bytes())}, data={"capture_fps": "5"})
        assert response.status_code == 201
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = client.get("/api/capture").json()
            if result["state"] in {"ended", "error"}:
                break
            time.sleep(.04)
        assert result["state"] == "ended", result
        assert result["observation_state"]["recognition_available"]
        state = result["observation_state"]["cards"]
        assert len(state["hero"]["cards"]) == 2 and len(state["board"]["cards"]) == 5
        assert [e["type"] for e in state["events"]] == ["HOLE_CARDS_DETECTED", "FLOP_DEALT", "TURN_DEALT", "RIVER_DEALT"]
        assert all(event["frame_id"] <= result["frame"]["frame_id"] for event in state["events"])
        stream = result["observation_state"]["event_stream"]
        exported = client.get("/api/events", params={"scope_id": stream["scope_id"]}).json()
        assert [e["type"] for e in exported["events"] if e["type"] not in {"GAME_STATE_UPDATED", "HAND_STARTED", "HAND_FINISHED", "CAPTURE_ENDED"}] == [
            "HOLE_CARDS_DETECTED", "FLOP_DEALT", "TURN_DEALT", "RIVER_DEALT"]
        from app.event_engine.models import Checkpoint, PokerEvent
        from app.event_engine.replay import EventReplay
        replay = EventReplay(Checkpoint.model_validate(exported["checkpoint"]))
        for event in exported["events"]:
            replay.apply(PokerEvent.model_validate(event))
        assert replay.state == client.app.state.capture.observation_state.current_state
        with client.websocket_connect("/ws/live") as ws:
            assert ws.receive_json()["payload"]["strategy_available"] == (mode == Mode.TRAINING)
        client.post(f'/api/capture/{result["capture_id"]}/stop')
        restarted = client.post("/api/capture/screen", json={}).json()
        assert restarted["observation_state"]["cards"]["events"] == []
