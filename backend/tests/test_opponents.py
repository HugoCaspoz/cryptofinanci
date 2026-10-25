from dataclasses import replace

import pytest

from app.event_engine.engine import EventEngine
from app.game_state_engine.models import GameState, PlayerState
from app.opponent_model.engine import OpponentModel
from app.opponent_model.models import HandContext
from app.opponent_model.statistics import statistic


def initial(hand="hand", scope="scope"):
    return GameState(scope, tuple(PlayerState(f"p{s}", s, nickname=f"Player{s}",
        stack="9900", current_bet="50" if s == 1 else "100" if s == 2 else "0") for s in range(1, 7)),
        hand_id=hand, hand_status="active", street="preflop", pot="150",
        small_blind="50", big_blind="100", hero_cards=("As", "Kh"))


class Stream:
    def __init__(self, configure=True):
        self.state = initial()
        self.bus = EventEngine(self.state)
        self.model = OpponentModel("scope")
        self.config = HandContext(hand_id="hand", seats=(1, 2), button_seat=1, start_confirmed=True)
        self.events = []
        if configure:
            self.model.configure(self.config, self.state)

    def emit(self, kind, **kwargs):
        sequence = self.bus.replay.sequence + 1
        event = self.bus.emit(kind, self.state, sequence, float(sequence), **kwargs)
        self.events.append(event)
        self.model.consume(event)
        return event

    def action(self, seat, action, total=None):
        players = list(self.state.players)
        player = players[seat - 1]
        players[seat - 1] = replace(player, current_bet=str(total) if total is not None else player.current_bet,
            folded=True if action == "FOLDED" else player.folded,
            all_in=True if action == "ALL_IN" else player.all_in)
        self.state = replace(self.state, players=tuple(players))
        return self.emit(f"PLAYER_{action}", player_id=f"p{seat}", confidence=.99,
            **({"amount": str(total), "unit": None} if total is not None else {}))

    def street(self, street):
        board = {"flop": ("Js", "7c", "4d"), "turn": ("Js", "7c", "4d", "2h"),
                 "river": ("Js", "7c", "4d", "2h", "9s")}[street]
        self.state = replace(self.state, street=street, board=board,
            players=tuple(replace(p, current_bet="0") for p in self.state.players))
        return self.emit(f"{street.upper()}_DEALT")

    def finish(self):
        self.state = replace(self.state, hand_status="finished")
        return self.emit("HAND_FINISHED")

    def stat(self, seat, name):
        return next(p for p in self.model.snapshot()["profiles"] if p["seat"] == seat and p["active"])["stats"][name]

    def raised_pot(self):
        self.action(1, "RAISED", 300)
        self.action(2, "CALLED", 300)
        self.street("flop")


def test_preflop_finalized_once_after_last_response_and_updates_three_bet_immediately():
    s = Stream()
    s.action(1, "RAISED", 300)
    assert s.stat(1, "vpip")["value"] is None  # Do not count an unfinished preflop as a negative.
    event = s.action(2, "RAISED", 900)
    assert s.stat(2, "three_bet")["value"] == 1
    s.model.consume(event)
    assert s.stat(2, "three_bet")["opportunities"] == 1
    s.action(1, "CALLED", 900)
    assert s.stat(1, "fold_to_three_bet")["value"] == 0
    for seat in (1, 2):
        assert s.stat(seat, "vpip")["hits"] == s.stat(seat, "pfr")["opportunities"] == 1
    s.street("flop")
    assert s.stat(1, "vpip")["opportunities"] == 1


def test_limp_check_and_walk_do_not_count_blinds_as_voluntary_money():
    s = Stream()
    s.action(1, "CALLED", 100)
    s.action(2, "CHECKED")
    assert s.stat(1, "vpip")["value"] == 1 and s.stat(2, "vpip")["value"] == 0
    assert s.stat(1, "pfr")["value"] == s.stat(2, "pfr")["value"] == 0
    s = Stream()
    s.action(1, "FOLDED")
    assert s.stat(2, "vpip")["value"] == 0
    assert s.stat(2, "three_bet")["value"] is None


def test_fold_to_three_bet_is_only_original_raiser_response():
    s = Stream()
    s.action(1, "RAISED", 300)
    s.action(2, "RAISED", 900)
    s.action(1, "FOLDED")
    assert s.stat(1, "fold_to_three_bet")["hits"] == 1
    assert s.stat(2, "fold_to_three_bet")["opportunities"] == 0


def test_cbet_opportunity_after_check_and_fold_response():
    s = Stream()
    s.raised_pot()
    s.action(2, "CHECKED")
    assert s.stat(1, "cbet")["value"] is None
    s.action(1, "BET", 300)
    assert s.stat(1, "cbet")["value"] == 1
    s.action(2, "FOLDED")
    assert s.stat(2, "fold_to_cbet")["value"] == 1
    s.finish()
    assert s.stat(1, "wtsd")["value"] == s.stat(2, "wtsd")["value"] == 0
    assert not s.model.pending_showdowns


def test_donk_bet_removes_cbet_opportunity_and_check_back_is_declined_cbet():
    s = Stream()
    s.raised_pot()
    s.action(2, "BET", 300)
    s.action(1, "CALLED", 300)
    assert s.stat(1, "cbet")["value"] is None
    assert s.stat(1, "fold_to_cbet")["value"] is None
    s = Stream()
    s.raised_pot()
    s.action(2, "CHECKED")
    s.action(1, "CHECKED")
    assert s.stat(1, "cbet")["value"] == 0


def test_raise_over_cbet_is_not_a_second_cbet_and_caller_of_raise_not_cbet_response():
    s = Stream()
    s.raised_pot()
    s.action(2, "CHECKED")
    s.action(1, "BET", 300)
    s.action(2, "RAISED", 900)
    s.action(1, "FOLDED")
    assert s.stat(2, "fold_to_cbet")["value"] == 0
    assert s.stat(1, "fold_to_cbet")["value"] is None
    assert s.stat(1, "cbet")["opportunities"] == 1


def test_river_does_not_imply_showdown_and_confirmation_is_exactly_once():
    s = Stream()
    s.raised_pot()
    for street in ("flop", "turn", "river"):
        if street != "flop":
            s.street(street)
        s.action(2, "CHECKED")
        s.action(1, "CHECKED")
    assert s.stat(1, "wtsd")["value"] is None
    with pytest.raises(ValueError):
        s.model.confirm_showdown("hand")
    s.finish()
    assert s.stat(1, "wtsd")["value"] is None
    s.model.confirm_showdown("hand")
    assert s.stat(1, "wtsd")["value"] == s.stat(2, "wtsd")["value"] == 1
    with pytest.raises(ValueError):
        s.model.confirm_showdown("hand")
    s.finish()
    assert not s.model.pending_showdowns


def test_partial_history_updates_raw_af_but_not_contextual_rates_and_classifies_all_in_call():
    s = Stream(configure=False)
    s.street("flop")
    s.action(1, "BET", 500)
    s.action(2, "ALL_IN", 500)
    assert s.stat(1, "aggression_factor")["reason"] == "no_calls"
    assert s.stat(2, "aggression_factor")["value"] == 0
    assert s.stat(2, "aggression_factor")["calls"] == 1
    assert s.stat(1, "vpip")["value"] is None
    assert s.stat(1, "cbet")["value"] is None


def test_postflop_af_counts_bets_raises_and_calls_only():
    s = Stream(configure=False)
    s.street("flop")
    s.action(1, "BET", 300)
    s.action(2, "RAISED", 900)
    s.action(1, "CALLED", 900)
    s.action(2, "CHECKED")
    af = s.stat(1, "aggression_factor")
    assert af["value"] == 1 and af["aggressive_actions"] == af["calls"] == 1


def test_multiway_squeeze_and_preflop_fold_excluded_from_wtsd():
    s = Stream(configure=False)
    s.config = s.config.model_copy(update={"seats": (1, 2, 3), "button_seat": 3})
    s.model.configure(s.config, s.state)
    s.action(3, "RAISED", 300)
    s.action(1, "CALLED", 300)
    s.action(2, "RAISED", 900)
    assert s.stat(2, "three_bet")["value"] == 1
    s.action(3, "CALLED", 900)
    s.action(1, "FOLDED")
    assert s.stat(1, "fold_to_three_bet")["value"] is None
    assert s.stat(3, "fold_to_three_bet")["value"] == 0
    s.street("flop")
    s.action(2, "BET", 300)
    s.action(3, "FOLDED")
    s.finish()
    assert s.stat(2, "cbet")["value"] == 1
    assert s.stat(1, "wtsd")["opportunities"] == 0
    assert s.stat(3, "wtsd")["opportunities"] == 1


def test_zero_stack_raise_also_suspends_context_even_without_all_in_label():
    s = Stream()
    s.state = replace(s.state, players=tuple(replace(p, stack="0") if p.seat == 1 else p for p in s.state.players))
    s.action(1, "RAISED", 900)
    assert not s.model.hand["valid"]
    assert s.stat(1, "vpip")["value"] is None


@pytest.mark.parametrize("bad", ["missing", "all_in", "wrong_turn", "unknown_bet"])
def test_incomplete_history_never_fills_missing_opportunities(bad):
    s = Stream()
    if bad == "missing":
        s.action(1, "RAISED", 300)
        s.street("flop")
    elif bad == "all_in":
        s.action(1, "ALL_IN", 9950)
    elif bad == "wrong_turn":
        s.action(2, "RAISED", 300)
    else:
        s.state = replace(s.state, players=tuple(replace(p, current_bet=None) if p.seat == 2 else p for p in s.state.players))
        s.action(1, "RAISED", 300)
    assert not s.model.snapshot()["context_valid"]
    assert s.stat(1, "vpip")["opportunities"] == 0
    assert s.stat(2, "cbet")["value"] is None


def test_gap_invalidates_context_and_duplicate_event_does_not_increment_raw_counts():
    s = Stream()
    event = s.action(1, "RAISED", 300)
    s.model.consume(event)
    p = s.model.profiles[s.model.active[1]]
    assert p["actions"] == 1
    s.model.consume(event.model_copy(update={"sequence": 4}))
    assert not s.model.hand["valid"] and p["actions"] == 1


def test_name_changes_isolate_profiles_and_same_names_at_different_seats_do_not_merge():
    s = Stream()
    old = s.model.active[1]
    s.action(1, "RAISED", 300)
    s.state = replace(s.state, players=tuple(replace(p, nickname="Replacement") if p.seat == 1 else p for p in s.state.players))
    s.emit("GAME_STATE_UPDATED")
    assert s.model.active[1] != old and not s.model.profiles[old]["active"]
    assert s.model.profiles[s.model.active[1]]["actions"] == 0
    assert not s.model.hand["valid"]


@pytest.mark.parametrize("change", [{"pot": "200"}, {"big_blind": None}, {"hand_status": "finished"}, {"street": "unknown"}])
def test_context_requires_known_initial_blinds_and_no_antes(change):
    s = Stream(configure=False)
    with pytest.raises(ValueError):
        s.model.configure(s.config, replace(s.state, **change))


def test_new_hand_requires_new_context_and_never_reuses_old_button():
    s = Stream()
    s.action(1, "FOLDED")
    s.finish()
    s.state = initial(hand="next")
    s.emit("HAND_STARTED")
    assert s.model.hand is None
    s.action(1, "RAISED", 300)
    assert s.stat(1, "vpip")["opportunities"] == 1
    with pytest.raises(ValueError):
        s.model.configure(s.config.model_copy(update={"hand_id": "next"}), s.state)


@pytest.mark.parametrize("hits,n,level", [(0, 0, "none"), (0, 1, "low"), (30, 30, "medium"), (50, 100, "high")])
def test_sample_confidence_and_wilson_interval_do_not_claim_certainty(hits, n, level):
    result = statistic(hits, n)
    assert result["confidence"] == level
    if n:
        lo, hi = result["interval_95"]
        assert lo <= hits / n + 1e-10 and hi >= hits / n - 1e-10 and hi > lo
    else:
        assert result["value"] is result["interval_95"] is None
