import shutil

import cv2
import pytest

from app.action_engine.demo import DURATION, render_action_table
from app.capture_engine.source import Frame
from app.event_engine.replay import EventReplay
from app.event_engine.models import Checkpoint, PokerEvent
from app.game_state_engine import GameStateEngine
from app.hand_reconstructor.store import HandStore
from app.table_detector.store import LayoutStore
from app.vision_engine import VisionEngine


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Requiere Tesseract real en Docker")
def test_pixels_to_six_actions_persist_replay_and_keep_fold_allin(tmp_path):
    layouts = LayoutStore()
    layout = layouts.read()[0]
    vision, game = VisionEngine(layouts), GameStateEngine()
    archive = HandStore(path=tmp_path / "actions.sqlite3")
    archive.initialize()
    sequence = 0
    video = tmp_path / "actions.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 1, (1920, 1080))
    assert writer.isOpened()
    for index in range(DURATION):
        writer.write(render_action_table(layout, index))
    writer.release()
    reader = cv2.VideoCapture(str(video))
    for index in range(DURATION):
        timestamp = float(index)
        decoded, image = reader.read()
        assert decoded
        game.accept(vision.observe(Frame(index + 1, timestamp, image, 5)))
        events = [e for e in game.event_engine.events if e.sequence > sequence]
        archive.save(game.hands.pending_records, events, {"name": "actions-demo"})
        sequence = game.event_engine.replay.sequence
    reader.release()
    saved = archive.get(game.current_state.hand_id)
    actions = [e for e in saved["events"] if e["type"].startswith("PLAYER_")]
    assert [e["type"] for e in actions] == ["PLAYER_CHECKED", "PLAYER_BET", "PLAYER_CALLED",
                                           "PLAYER_RAISED", "PLAYER_FOLDED", "PLAYER_ALL_IN"]
    assert [e["amount"] for e in actions] == [None, "500", "500", "1000", None, "1000"]
    assert [e["player_id"] for e in actions] == [p.player_id for p in game.current_state.players]
    assert game.current_state.players[4].folded and game.current_state.players[5].all_in
    exported = game.event_engine.export()
    replay = EventReplay(Checkpoint.model_validate(exported["checkpoint"]))
    for event in exported["events"]:
        replay.apply(PokerEvent.model_validate(event))
    assert replay.state == game.current_state
