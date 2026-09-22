from app.card_detector.models import Card, CardObservation, RegionReading, SUITS
from app.game_state_engine import GameStateEngine
from app.vision_engine import VisionObservation


def reading(codes, confidence=.98):
    if codes is None:
        return RegionReading()
    return RegionReading("known" if codes else "empty", tuple(Card(c[0], SUITS[c[1]], confidence) for c in codes))


class Stream:
    def __init__(self):
        self.state = GameStateEngine()
        self.frame_id = 0
        self.timestamp = 0

    def send(self, hero=("As", "Jh"), board=(), count=1, status="ready", gap=.2):
        for _ in range(count):
            self.frame_id += 1
            self.timestamp += gap
            cards = CardObservation(status=status, hero=reading(hero), board=reading(board))
            self.state.accept(VisionObservation(self.frame_id, self.timestamp, 1920, 1080, status == "ready", cards))
        return self.state.snapshot()["cards"]


def test_stable_progression_emits_exactly_one_event_per_change():
    stream = Stream()
    state = stream.send(count=2)
    assert state["events"] == [] and state["hero"]["status"] == "pending"
    for board in [(), ("Js", "7c", "4d"), ("Js", "7c", "4d", "2h"), ("Js", "7c", "4d", "2h", "Tc")]:
        state = stream.send(board=board, count=20)
    assert [event["type"] for event in state["events"]] == ["HOLE_CARDS_DETECTED", "FLOP_DEALT", "TURN_DEALT", "RIVER_DEALT"]
    assert state["events"][0]["frame_id"] == 3
    assert state["events"][0]["timestamp"] == .2 * 3
    assert len(state["board"]["cards"]) == 5
    assert stream.send(hero=("Jh", "As"), board=board, count=10)["event_count"] == 4


def test_unknowns_and_brief_empty_reads_keep_confirmed_cards_without_duplicates():
    stream = Stream()
    stream.send(count=3)
    unknown = stream.send(hero=None, count=8)
    assert len(unknown["hero"]["cards"]) == 2 and unknown["hero"]["status"] == "unknown"
    assert stream.send(count=3)["event_count"] == 1
    assert len(stream.send(hero=(), count=2)["hero"]["cards"]) == 2
    assert stream.send(count=3)["event_count"] == 1
    assert stream.send(hero=(), count=3)["events"][-1]["type"] == "HERO_CARDS_CLEARED"
    assert stream.send(count=3)["event_count"] == 3


def test_uncertain_frames_and_time_gaps_break_confirmation_streaks():
    stream = Stream()
    stream.send(count=2)
    stream.send(hero=None)
    assert stream.send(count=2)["events"] == []
    stream.send(status="resolution_mismatch")
    assert stream.send(count=2)["events"] == []
    assert stream.send(gap=4)["events"] == []
    assert stream.send(count=2)["event_count"] == 1


def test_skipped_streets_and_corrections_do_not_invent_dealing_history():
    stream = Stream()
    state = stream.send(board=("Js", "7c", "4d", "2h", "Tc"), count=3)
    assert [e["type"] for e in state["events"]] == ["HOLE_CARDS_DETECTED", "BOARD_CARDS_UPDATED"]
    assert stream.send(board=("Js", "7c", "4d", "2h", "9c"), count=3)["events"][-1]["type"] == "BOARD_CARDS_UPDATED"


def test_duplicate_against_retained_cards_is_rejected_atomically():
    stream = Stream()
    stream.send(count=3)
    state = stream.send(hero=None, board=("As", "7c", "4d"), count=3)
    assert state["board"]["cards"] == []
    assert state["board"]["status"] == "conflict"
    assert state["event_count"] == 1


def test_event_history_is_bounded_and_new_capture_has_no_history():
    stream = Stream()
    for _ in range(30):
        stream.send(count=3)
        state = stream.send(hero=(), count=3)
    assert len(state["events"]) == 40 and state["event_count"] == 60
    assert state["events"][0]["id"] == 21
    assert GameStateEngine().snapshot()["cards"]["event_count"] == 0
