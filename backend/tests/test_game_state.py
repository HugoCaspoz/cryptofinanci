from dataclasses import FrozenInstanceError
import json

import pytest

from app.card_detector.models import Card, CardObservation, RegionReading, SUITS
from app.game_state_engine import GameStateEngine
from app.ocr_engine.models import OcrObservation, TextReading
from app.vision_engine import VisionObservation


class Stream:
    def __init__(self):
        self.engine = GameStateEngine()
        self.frame = 0

    def send(self, *, hero=("As", "Jh"), board=(), pot="750", stack="12500", bet="0",
             nickname="Alice", blinds="50 / 100", unit=None, confidence=.99,
             count=3, ocr_status="ready"):
        def region(codes):
            return RegionReading() if codes is None else RegionReading(
                "known" if codes else "empty", tuple(Card(c[0], SUITS[c[1]], .98) for c in codes))
        for _ in range(count):
            self.frame += 1
            fields = [("pot", "amount", pot), ("players.0.stack", "amount", stack),
                      ("players.0.bet", "amount", bet), ("players.0.nickname", "nickname", nickname),
                      ("blinds", "blinds", blinds)]
            ocr = OcrObservation(ocr_status, ocr_status != "not_sampled", tuple(
                TextReading(key, kind, value or "", confidence, value, unit if kind != "nickname" else None)
                for key, kind, value in fields), "layout-a")
            self.engine.accept(VisionObservation(self.frame, self.frame * .6, 1920, 1080, True,
                CardObservation("ready", layout_revision="layout-a", hero=region(hero), board=region(board)), ocr))
        return self.engine.snapshot()["game_state"]


def test_initial_state_has_no_invented_hand_players_or_actions():
    state = GameStateEngine().snapshot()["game_state"]
    assert state["hand_id"] is state["pot"] is state["button_position"] is state["current_player"] is None
    assert state["street"] == "unknown" and state["revision"] == 0
    assert len(state["players"]) == 6
    assert all(p["nickname"] is p["folded"] is p["all_in"] is p["position"] is None for p in state["players"])


def test_unifies_confirmed_cards_amounts_and_blinds_and_deduplicates():
    stream = Stream()
    assert stream.send(count=2)["revision"] == 0
    state = stream.send(count=1)
    assert state["revision"] == 1 and state["street"] == "preflop"
    assert state["hero_cards"] == ("As", "Jh")
    assert state["pot"] == "750" and state["small_blind"] == "50" and state["big_blind"] == "100"
    assert state["players"][0]["current_bet"] == "0"
    assert state["evidence"]["pot"]["confirmed_frame_id"] == 3
    assert stream.send(count=20)["revision"] == 1


def test_changes_have_before_after_and_only_confirmed_values():
    stream = Stream()
    stream.send()
    assert stream.send(pot="1500", stack="12000", bet="500", count=2)["revision"] == 1
    state = stream.send(pot="1500", stack="12000", bet="500", count=1)
    event = state["events"][-1]
    assert event["type"] == "GAME_STATE_UPDATED" and event["frame_id"] == 6
    assert {d["field"]: (d["previous"], d["current"]) for d in event["changes"]} == {
        "pot": ("750", "1500"), "players.0.stack": ("12500", "12000"),
        "players.0.current_bet": ("0", "500")}
    assert state["players"][0]["all_in"] is None


def test_unknown_and_low_confidence_preserve_values_with_old_evidence():
    stream = Stream()
    before = stream.send()
    state = stream.send(hero=None, board=None, pot=None, stack="0", confidence=.3, count=8)
    assert state["pot"] == "750" and state["players"][0]["stack"] == "12500"
    assert state["revision"] == before["revision"] and state["street"] == "preflop"
    assert state["evidence"]["pot"]["status"] == "unknown"
    assert state["evidence"]["pot"]["confirmed_timestamp"] == before["evidence"]["pot"]["confirmed_timestamp"]
    assert state["evidence"]["hero_cards"]["status"] == "unknown"
    assert state["evidence"]["hero_cards"]["confirmed_frame_id"] == 3


def test_street_progression_and_clear_do_not_invent_hand_boundaries():
    stream = Stream()
    for codes, street in [((), "preflop"), (("Js", "7c", "4d"), "flop"),
                          (("Js", "7c", "4d", "2h"), "turn"),
                          (("Js", "7c", "4d", "2h", "Tc"), "river")]:
        assert stream.send(board=codes)["street"] == street
    state = stream.send(hero=(), board=())
    assert state["street"] == "unknown" and state["hand_id"] is not None
    assert stream.engine.hands.finished_count == 0  # Blank interval not yet sustained.
    assert all(e["type"] == "GAME_STATE_UPDATED" for e in state["events"])


def test_capture_starting_at_river_does_not_require_future_or_missing_streets():
    stream = Stream()
    state = stream.send(hero=None, board=("Js", "7c", "4d", "2h", "Tc"))
    assert state["street"] == "river" and state["hero_cards"] == () and state["hand_id"] is not None
    assert state["hand_status"] == "active" and stream.engine.hands.active["partial_start"]


def test_units_are_part_of_changes_and_zero_does_not_mean_all_in():
    stream = Stream()
    stream.send(stack="0", pot="0.1", unit="BB")
    state = stream.send(stack="0", pot="0.1", unit="$")
    assert state["pot"] == "0.1" and state["pot_unit"] == "$"
    assert state["players"][0]["all_in"] is None and state["players"][0]["folded"] is None
    assert "pot_unit" in [c["field"] for c in state["events"][-1]["changes"]]


def test_unsampled_or_failed_ocr_cannot_confirm_change():
    stream = Stream()
    stream.send()
    stream.send(pot="800", count=2)
    state = stream.send(pot="800", ocr_status="not_sampled", count=3)
    assert state["pot"] == "750"
    assert stream.send(ocr_status="engine_error")["evidence"]["pot"]["status"] == "unknown"
    assert stream.send(pot="800", count=2)["pot"] == "750"


def test_snapshots_and_previous_states_do_not_change_when_later_frames_arrive():
    stream = Stream()
    snapshot = stream.send()
    frozen = stream.engine.current_state
    with pytest.raises(FrozenInstanceError):
        frozen.pot = "999"
    stream.send(pot="900", nickname="Bruno")
    assert frozen.pot == "750" and snapshot["players"][0]["nickname"] == "Alice"
    snapshot["events"][0]["changes"][0]["current"] = "corrupt"
    assert "corrupt" not in json.dumps(stream.engine.snapshot())
    fresh = GameStateEngine().snapshot()["game_state"]
    assert fresh["players"][0]["player_id"] != frozen.players[0].player_id
    assert fresh["pot"] is None and fresh["events"] == []


@pytest.mark.parametrize("timestamp", [-1, 0.6, 0.1, float("nan"), float("inf")])
def test_rejects_invalid_time_before_mutating_any_state(timestamp):
    stream = Stream()
    stream.send(count=1)
    before = stream.engine.snapshot()
    with pytest.raises(ValueError):
        stream.engine.accept(VisionObservation(2, timestamp, 1920, 1080))
    assert stream.engine.snapshot() == before


def test_state_event_buffer_is_bounded():
    stream = Stream()
    for amount in range(55):
        state = stream.send(pot=str(amount))
    assert state["revision"] == 55 and len(state["events"]) == 40
    assert state["events"][0]["id"] == 16
