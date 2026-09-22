from dataclasses import replace

import cv2
import pytest

from app.action_engine.engine import ActionEngine
from app.action_engine.vision import ActionObservation, ActionReading, ActionVision, LABELS, render_badge
from app.capture_engine.source import Frame
from app.card_detector.demo import render_table
from app.event_engine.engine import EventEngine
from app.game_state_engine.models import GameState, PlayerState, FieldEvidence
from app.table_detector.store import LayoutStore


def state(bets=None, stacks=None, pot="1000", hand="hand", street="flop"):
    return GameState("scope", tuple(PlayerState(f"p{i}", i + 1, stack=(stacks or ["15000"] * 6)[i],
                     current_bet=(bets or ["0"] * 6)[i]) for i in range(6)), hand_id=hand,
                     hand_status="active", street=street, pot=pot, board=("Js", "7c", "4d"))


class Stream:
    def __init__(self):
        self.engine = ActionEngine()
        self.time = 0
        self.events = []
        self.bus = EventEngine(state())

    def send(self, value, label=None, actor=0, count=3, stale=False, other=None):
        for _ in range(count):
            self.time += .6
            readings = [ActionReading() for _ in range(6)]
            readings[actor] = ActionReading(label, .98)
            if other is not None:
                readings[other] = ActionReading("ACTIVE", .98)
            evidence = {k: FieldEvidence("confirmed", .99, round(self.time * 10),
                        self.time - 10 if stale else self.time, "layout") for k in self.engine.keys()}
            self.current, events = self.engine.update(value, ActionObservation("ready", tuple(readings)), evidence, self.time)
            for kind, details in events:
                self.events.append(self.bus.emit(kind, self.current, round(self.time * 10), self.time, **details))
        return self.current


@pytest.mark.parametrize("label,bets,stack,target,pot", [
    ("BET", ["0"] * 6, "14500", "500", "1500"),
    ("CALL", ["0", "500", "0", "0", "0", "0"], "14500", "500", "1500"),
    ("RAISE", ["100", "500", "0", "0", "0", "0"], "14100", "1000", "1900"),
    ("ALL-IN", ["0"] * 6, "0", "15000", "16000"),
    ("CHECK", ["0"] * 6, "15000", "0", "1000"),
    ("FOLD", ["0", "500", "0", "0", "0", "0"], "15000", "0", "1000"),
])
def test_six_actions_require_turn_label_and_consistent_money_and_do_not_repeat(label, bets, stack, target, pot):
    stream = Stream()
    before = state(bets=bets)
    assert stream.send(before, "ACTIVE").current_player == "p0"
    after = state(bets=[target, *bets[1:]], stacks=[stack, *["15000"] * 5], pot=pot)
    stream.send(after, label, count=15)
    assert len(stream.events) == 1
    event = stream.events[0]
    assert event.player_id == "p0" and event.hand_id == "hand"
    assert len(event.action_evidence) == 5
    assert event.amount == (None if label in {"CHECK", "FOLD"} else target)
    assert event.state_after.players[0].folded is (True if label == "FOLD" else None)
    assert event.state_after.players[0].all_in is (True if label == "ALL-IN" else None)


def test_amounts_alone_labels_alone_and_one_frame_labels_never_produce_actions():
    stream = Stream()
    before, after = state(), state(bets=["500", *["0"] * 5], stacks=["14500", *["15000"] * 5], pot="1500")
    stream.send(before)
    stream.send(after, "BET", count=8)
    assert not stream.events
    stream.send(before, "ACTIVE")
    stream.send(after, "BET", count=1)
    stream.send(after, count=8)
    assert not stream.events


@pytest.mark.parametrize("case", ["pot", "stack", "other", "unit", "stale", "label", "hand", "street"])
def test_inconsistent_or_ambiguous_evidence_is_not_attributed(case):
    stream = Stream()
    stream.send(state(), "ACTIVE")
    after = state(bets=["500", *["0"] * 5], stacks=["14500", *["15000"] * 5], pot="1500")
    if case == "pot": after = replace(after, pot="1750")
    if case == "stack": after = replace(after, players=(replace(after.players[0], stack="14000"), *after.players[1:]))
    if case == "other": after = replace(after, players=(after.players[0], replace(after.players[1], current_bet="200"), *after.players[2:]))
    if case == "unit": after = replace(after, pot_unit="BB")
    if case == "hand": after = replace(after, hand_id="new")
    if case == "street": after = replace(after, street="turn", board=(*after.board, "2h"))
    stream.send(after, "CALL" if case == "label" else "BET", stale=case == "stale", count=10)
    assert not stream.events


def test_delayed_ocr_confirms_once_and_unknown_does_not_count_as_a_vote():
    stream = Stream()
    stream.send(state(), "ACTIVE")
    stream.send(state(), "BET")  # Label arrives before amounts.
    assert not stream.events
    stream.send(state(), None, count=1)
    stream.send(state(bets=["500", *["0"] * 5], stacks=["14500", *["15000"] * 5], pot="1500"), "BET")
    assert len(stream.events) == 1


def test_two_active_players_and_unknown_check_facing_a_bet_are_rejected():
    stream = Stream()
    stream.send(state(), "ACTIVE", other=1)
    stream.send(state(), "CHECK")
    assert not stream.events
    stream = Stream()
    before = state(bets=["0", "500", *["0"] * 4])
    stream.send(before, "ACTIVE")
    stream.send(before, "CHECK")
    assert not stream.events


def test_fold_is_retained_across_streets_but_resets_between_hands():
    stream = Stream()
    stream.send(state(), "ACTIVE")
    stream.send(state(), "FOLD")
    assert stream.send(replace(state(), street="turn", board=("Js", "7c", "4d", "2h"))).players[0].folded
    assert stream.send(state(hand="next")).players[0].folded is None


def test_fractional_raise_amount_is_total_wager_not_increment():
    stream = Stream()
    before = state(bets=["0.25", "0.5", *["0"] * 4], stacks=["10"] * 6, pot="1")
    stream.send(before, "ACTIVE")
    after = state(bets=["1.25", "0.5", *["0"] * 4], stacks=["9", *["10"] * 5], pot="2")
    stream.send(after, "RAISE")
    assert stream.events[0].amount == "1.25"


@pytest.mark.parametrize("label", LABELS)
def test_visual_templates_recognize_compressed_pixels_and_ignore_other_profiles(label):
    layout, revision = LayoutStore().read()
    detector = ActionVision(layout, revision)
    image = render_table(layout)
    for p in layout.players:
        r = p.action
        image[r.y:r.y+r.height, r.x:r.x+r.width] = render_badge(r.width, r.height, label)
    image = cv2.imdecode(cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])[1], cv2.IMREAD_COLOR)
    result = detector.observe(Frame(1, 0, image, 5))
    assert [r.label for r in result.readings] == [label] * 6
    unknown = ActionVision(layout.model_copy(update={"platform": "Other"}), revision)
    assert unknown.observe(Frame(1, 0, image, 5)).status == "unsupported_profile"


def test_blank_or_obscured_pixels_do_not_mean_fold_or_check():
    layout, revision = LayoutStore().read()
    detector = ActionVision(layout, revision)
    image = render_table(layout)
    assert all(r.label is None for r in detector.observe(Frame(1, 0, image, 5)).readings)
    image[:] = 0
    assert all(r.label is None for r in detector.observe(Frame(2, 1, image, 5)).readings)
