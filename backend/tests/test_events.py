from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.event_engine.engine import EventEngine
from app.event_engine.models import Checkpoint, EventBatch, PokerEvent
from app.event_engine.replay import EventReplay, replay_batch
from app.game_state_engine import GameState, PlayerState
from app.main import create_app
from test_game_state import Stream


def initial():
    return GameState("capture-a", tuple(PlayerState(f"capture-a:seat:{i}", i) for i in range(1, 7)))


def replay_export(exported):
    return replay_batch(EventBatch.model_validate(exported))


def test_video_observations_emit_only_confirmed_facts_and_replay_exactly():
    stream = Stream()
    stream.send(count=2)
    assert stream.engine.event_engine.summary()["event_count"] == 0
    stream.send(count=1)
    for board in [("Js", "7c", "4d"), ("Js", "7c", "4d", "2h"), ("Js", "7c", "4d", "2h", "Tc")]:
        stream.send(board=board)
    events = stream.engine.event_engine
    assert [e.type for e in events.events if e.type not in {"GAME_STATE_UPDATED", "HAND_STARTED"}] == [
        "HOLE_CARDS_DETECTED", "FLOP_DEALT", "TURN_DEALT", "RIVER_DEALT"]
    assert all(e.confidence == .98 for e in events.events if e.type not in {"GAME_STATE_UPDATED", "HAND_STARTED"})
    assert replay_export(events.export()).state == stream.engine.current_state
    count = events.replay.sequence
    stream.send(board=board, count=20)
    assert events.replay.sequence == count
    stream.send(hero=None, board=None, pot=None, confidence=.1)
    assert events.replay.sequence == count


def test_action_contract_can_reconstruct_a_hand_without_vision():
    state = initial()
    engine = EventEngine(state)
    state = replace(state, hand_id="hand-1", street="preflop")
    engine.emit("HAND_STARTED", state, 1, 0, confidence=.99)
    actions = [("PLAYER_CHECKED", None), ("PLAYER_BET", "100"),
               ("PLAYER_CALLED", "100"), ("PLAYER_RAISED", "450"),
               ("PLAYER_ALL_IN", "1000"), ("PLAYER_FOLDED", None)]
    for frame, (kind, amount) in enumerate(actions, start=2):
        seat_index = frame - 2
        player = state.players[seat_index]
        player = replace(player, current_bet=amount if amount is not None else player.current_bet,
                         bet_unit="BB" if amount is not None else player.bet_unit,
                         folded=True if kind == "PLAYER_FOLDED" else player.folded,
                         all_in=True if kind == "PLAYER_ALL_IN" else player.all_in)
        players = list(state.players)
        players[seat_index] = player
        state = replace(state, players=tuple(players))
        engine.emit(kind, state, frame, frame / 5, player_id=player.player_id,
                    amount=amount, unit="BB" if amount is not None else None, confidence=.94)
    engine.emit("HAND_FINISHED", state, 8, 2, confidence=.99)
    exported = engine.export()
    reconstructed = replay_export(exported)
    assert reconstructed.state == state and reconstructed.sequence == 8
    # A past prefix knows only its own state, irrespective of later actions.
    prefix = {**exported, "events": exported["events"][:2], "last_sequence": 2}
    assert replay_export(prefix).state.players[0].current_bet is None
    assert replay_export(prefix).state.players[0].folded is None


def test_same_frame_retransmission_is_idempotent_but_conflicts_are_rejected():
    state = replace(initial(), pot="10")
    engine = EventEngine(initial())
    event = engine.emit("GAME_STATE_UPDATED", state, 1, .2)
    assert engine.emit("GAME_STATE_UPDATED", state, 1, .2) == event
    with pytest.raises(ValueError):
        engine.emit("GAME_STATE_UPDATED", replace(state, pot="20"), 1, .2)
    assert engine.replay.sequence == 1 and len(engine.events) == 1
    engine.replay.apply(event)
    assert engine.replay.sequence == 1


def test_retention_checkpoint_and_cursor_never_hide_a_gap():
    engine = EventEngine(initial())
    for i in range(1, 65):
        engine.emit("GAME_STATE_UPDATED", replace(initial(), pot=str(i)), i, i / 5)
    summary = engine.summary()
    assert len(summary["events"]) == 40 and summary["dropped_events"] == 24
    assert all("state_after" not in item for item in summary["events"])
    exported = engine.export()
    assert exported["gap"] is True and exported["checkpoint"]["sequence"] == 24
    assert replay_export(exported).state.pot == "64"
    tail = engine.export(after=60)
    assert tail["gap"] is False and len(tail["events"]) == 4
    assert replay_export(tail).state.pot == "64"
    assert engine.export(64)["events"] == []
    with pytest.raises(ValueError):
        engine.export(65)
    exported["events"][0]["state_after"]["pot"] = "corrupt"
    assert engine.export()["events"][0]["state_after"]["pot"] == "25"


@pytest.mark.parametrize("change", [
    {"sequence": 2}, {"frame_id": 0}, {"timestamp": float("nan")},
    {"confidence": 1.1}, {"scope_id": "wrong"}, {"hand_id": "wrong"},
    {"type": "FLOP_DEALT"}, {"type": "PLAYER_CHECKED"},
    {"amount": "NaN"}, {"schema_version": 2}, {"player_id": "missing"},
])
def test_invalid_contract_or_sequence_is_rejected_without_mutation(change):
    engine = EventEngine(initial())
    data = dict(sequence=1, type="GAME_STATE_UPDATED", scope_id="capture-a", frame_id=1,
                timestamp=.2, state_after=initial())
    data.update(change)
    with pytest.raises(ValueError):
        engine.replay.apply(PokerEvent(**data))
    assert engine.replay.sequence == 0


@pytest.mark.parametrize("amount", ["-1", "1e3", "NaN", "0.001", "1,5", "200"])
def test_action_amount_must_match_exact_visible_total(amount):
    state = initial()
    state = replace(state, hand_id="h1", players=(replace(state.players[0], current_bet="100"), *state.players[1:]))
    with pytest.raises(ValidationError):
        PokerEvent(sequence=1, type="PLAYER_RAISED", scope_id="capture-a", hand_id="h1",
                   player_id=state.players[0].player_id, amount=amount, confidence=.9,
                   state_after=state, frame_id=1, timestamp=0)


def test_replay_rejects_reordering_and_mixed_captures():
    engine = EventEngine(initial())
    first = engine.emit("GAME_STATE_UPDATED", replace(initial(), pot="1"), 2, 1)
    with pytest.raises(ValueError):
        engine.emit("GAME_STATE_UPDATED", replace(initial(), pot="2"), 1, 2)
    with pytest.raises(ValueError):
        engine.emit("GAME_STATE_UPDATED", replace(initial(), pot="2"), 3, .5)
    other = replace(initial(), scope_id="other")
    with pytest.raises(ValueError):
        engine.replay.apply(PokerEvent(sequence=2, type="GAME_STATE_UPDATED", scope_id="other",
                                       state_after=other, frame_id=3, timestamp=2))
    assert engine.replay.last_event == first


def test_export_api_scope_validation_and_restart():
    with TestClient(create_app()) as client:
        engine = client.app.state.capture.observation_state
        scope = engine.current_state.scope_id
        response = client.get("/api/events", params={"scope_id": scope})
        assert response.status_code == 200 and response.json()["events"] == []
        assert client.get("/api/events").status_code == 422
        assert client.get("/api/events", params={"scope_id": scope, "after": -1}).status_code == 422
        assert client.get("/api/events", params={"scope_id": scope, "after": 1}).status_code == 422
        assert client.get("/api/events", params={"scope_id": "old"}).status_code == 409
        client.post("/api/capture/screen", json={})
        assert client.get("/api/events", params={"scope_id": scope}).status_code == 409
        current = client.get("/api/capture").json()["observation_state"]["event_stream"]
        assert current["event_count"] == 0 and current["scope_id"] != scope


@pytest.mark.parametrize("change", [
    {"board": ("As", "As", "Jh"), "street": "flop"},
    {"board": ("As", "9c", "Jh"), "street": "river"},
    {"hero_cards": ("XX", "7h")}, {"pot": "NaN"},
    {"current_player": "absent"}, {"button_position": 8}, {"players": ()},
])
def test_checkpoint_rejects_corrupt_states(change):
    with pytest.raises(ValueError):
        Checkpoint(sequence=0, frame_id=0, timestamp=0, state=replace(initial(), **change))


def test_serialized_events_are_immutable_and_replay_rejects_changed_retransmission():
    from dataclasses import FrozenInstanceError
    engine = EventEngine(initial())
    event = engine.emit("GAME_STATE_UPDATED", replace(initial(), pot="1"), 1, .2)
    with pytest.raises(ValidationError):
        event.sequence = 2
    with pytest.raises(FrozenInstanceError):
        event.state_after.players[0].nickname = "changed"
    altered = PokerEvent.model_validate({**event.model_dump(mode="json"), "timestamp": .3})
    with pytest.raises(ValueError):
        engine.replay.apply(altered)
    assert engine.replay.timestamp == .2


def test_export_cannot_silently_lose_its_final_event_or_gap_marker():
    engine = EventEngine(initial())
    engine.emit("GAME_STATE_UPDATED", replace(initial(), pot="10"), 1, .2)
    exported = engine.export()
    with pytest.raises(ValueError):
        replay_export({**exported, "events": []})
    with pytest.raises(ValueError):
        replay_export({**exported, "gap": True})


def test_standalone_replay_script_uses_only_exported_data(tmp_path):
    import json
    from pathlib import Path
    import subprocess
    import sys
    engine = EventEngine(initial())
    engine.emit("GAME_STATE_UPDATED", replace(initial(), pot="12.5", pot_unit="BB"), 1, .2)
    path = tmp_path / "events.json"
    path.write_text(json.dumps(engine.export()), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "scripts" / "replay_events.py"
    result = subprocess.run([sys.executable, str(script), str(path)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout)
    assert state["sequence"] == 1 and state["state"]["pot"] == "12.5"
    path.write_text("{}", encoding="utf-8")
    result = subprocess.run([sys.executable, str(script), str(path)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
