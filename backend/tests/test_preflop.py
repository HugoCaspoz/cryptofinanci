from dataclasses import replace
from decimal import Decimal

import pytest

from app.game_state_engine.models import GameState, PlayerState
from app.strategy_engine.defaults import default_rules
from app.strategy_engine.history import positions, replay
from app.strategy_engine.models import PreflopConfig, PreflopRule, PriorAction
from app.strategy_engine.preflop import PreflopEngine


def settings(**changes):
    return PreflopConfig(**({"hand_id": "hand", "hero_seat": 3, "button_seat": 6,
        "seats": (1, 2, 3, 4, 5, 6), "ante_total_bb": "0", "pot_includes_bets": True,
        "history_confirmed": True, "prior_actions": (), "rules": default_rules()} | changes))


def state(config=None, cards=("As", "Kh"), history=None, stack_bb=100):
    config = config or settings()
    history = config.prior_actions if history is None else history
    context = replay(config, history, Decimal("0.5"))
    players = tuple(PlayerState(f"p{seat}", seat,
        stack=str((Decimal(stack_bb) - context.bets.get(seat, 0)) * 100),
        current_bet=str(context.bets.get(seat, 0) * 100),
        folded=True if seat in context.folded else None) for seat in range(1, 7))
    return GameState("scope", players, hand_id="hand", hand_status="active", street="preflop",
        hero_cards=cards, pot=str((sum(context.bets.values()) + config.ante_total_bb) * 100),
        small_blind="50", big_blind="100", current_player=f"p{context.pending[0]}" if context.pending else None)


def action(seat, kind, total=None):
    return PriorAction(seat=seat, action=kind, total_bb=total)


def analyze(config=None, current=None):
    config = config or settings()
    return PreflopEngine().analyze(current or state(config), config, config.prior_actions)


def test_unopened_raise_is_total_and_confidence_is_not_invented():
    result = analyze()
    assert result.action == "RAISE" and result.sizing_bb == 2.5 and result.additional_bb == 2.5
    assert result.confidence is None and result.context["position"] == "UTG"
    assert result.context["effective_stack_bb"] == 100
    assert analyze(current=state(cards=("7s", "2h"))).action == "FOLD"


def test_position_changes_range_for_same_cards():
    assert analyze(current=state(cards=("As", "5s"))).action == "FOLD"
    config = settings(hero_seat=6, prior_actions=[action(s, "FOLD") for s in (3, 4, 5)])
    assert analyze(config, state(config, cards=("As", "5s"))).action == "RAISE"


def test_headsup_button_posts_small_blind_and_acts_first():
    config = settings(hero_seat=2, button_seat=2, seats=(2, 5))
    result = analyze(config)
    assert result.context["position"] == "BTN/SB" and result.context["players_dealt"] == 2
    assert result.sizing_bb == 2.5 and result.additional_bb == 2
    labels, order, small, big = positions((1, 3, 5, 6), 5)
    assert labels == {5: "BTN", 6: "SB", 1: "BB", 3: "CO"} and order == [3, 5, 6, 1]


def test_limped_big_blind_checks_weak_hand_and_isolates_value():
    history = [action(3, "CALL", 1), action(4, "FOLD"), action(5, "FOLD"), action(6, "FOLD"), action(1, "FOLD")]
    config = settings(hero_seat=2, prior_actions=history)
    weak = analyze(config, state(config, cards=("7s", "2h")))
    assert weak.action == "CHECK" and weak.sizing_bb is None
    result = analyze(config)
    assert result.action == "RAISE" and result.sizing_bb == 4 and result.additional_bb == 3


def test_facing_raise_uses_prior_actions_opener_and_incremental_call():
    config = settings(hero_seat=1, prior_actions=[action(3, "RAISE", 3)] + [action(s, "FOLD") for s in (4, 5, 6)])
    result = analyze(config)
    assert result.action == "RAISE" and result.sizing_bb == 9 and result.additional_bb == 8.5
    assert result.context["opener_position"] == "UTG"
    result = analyze(config, state(config, cards=("Js", "Jh")))
    assert result.action == "CALL" and result.sizing_bb == 3 and result.additional_bb == 2.5
    assert analyze(config, state(config, cards=("7s", "2h"))).action == "FOLD"


def test_minimum_raise_and_stack_cap_are_respected():
    config = settings(hero_seat=4, prior_actions=[action(3, "RAISE", 3)], rules=[
        PreflopRule(id="short", scenario="single_raise", positions=("HJ",), min_stack_bb=1, raise_range="AK", raise_multiplier=2)])
    result = analyze(config, state(config, stack_bb=5))
    assert result.action == "ALL_IN" and result.sizing_bb == 5
    assert analyze(config, state(config, stack_bb=2)).action is None


@pytest.mark.parametrize("changed", [
    {"ante_total_bb": "1"}, {"rules": [r.model_copy(update={"min_players": 2, "max_players": 5}) for r in default_rules()]},
    {"rules": [r.model_copy(update={"max_stack_bb": 50}) for r in default_rules()]},
    {"rules": [*default_rules(), default_rules()[0].model_copy(update={"id": "duplicate-domain"})]},
])
def test_missing_or_ambiguous_table_never_guesses(changed):
    result = analyze(settings(**changed))
    assert result.status == "unavailable" and result.action is None


def test_configured_ante_and_stack_bands_and_opener_filters():
    rule = default_rules()[0].model_copy(update={"min_ante_bb": 1, "max_ante_bb": 1, "open_to_bb": 3})
    config = settings(ante_total_bb="1", rules=[rule])
    assert analyze(config).sizing_bb == 3
    config = settings(hero_seat=4, prior_actions=[action(3, "RAISE", 3)], rules=[
        default_rules()[-1].model_copy(update={"opener_positions": ("BTN",)})])
    assert analyze(config).action is None
    config = config.model_copy(update={"rules": (config.rules[0].model_copy(update={"opener_positions": ("UTG",)}),)})
    assert analyze(config).action == "RAISE"


@pytest.mark.parametrize("changes", [
    {"street": "flop", "board": ("2s", "3h", "4d")}, {"hand_status": "incomplete"},
    {"hand_id": "next"}, {"current_player": None}, {"current_player": "p4"},
    {"hero_cards": ()}, {"hero_cards": ("As", "As")}, {"big_blind": None},
    {"pot": "999"}, {"blinds_unit": "BB"},
])
def test_unknown_stale_wrong_hand_or_inconsistent_state_abstains(changes):
    assert analyze(current=replace(state(), **changes)).action is None


@pytest.mark.parametrize("history", [
    [action(4, "FOLD")], [action(3, "CHECK")], [action(3, "CALL", 2)], [action(3, "RAISE", 1.5)],
    [action(3, "ALL_IN", 100)],
])
def test_invalid_history_and_short_all_in_reopening_not_supported(history):
    config = settings(prior_actions=history)
    assert analyze(config, state()).action is None


def test_no_second_hero_decision_or_multiple_raises():
    config = settings(prior_actions=[action(3, "CALL", 1), action(4, "RAISE", 3)] +
                      [action(s, "FOLD") for s in (5, 6, 1, 2)])
    assert analyze(config).action is None
    config = settings(hero_seat=5, prior_actions=[action(3, "RAISE", 3), action(4, "RAISE", 9)])
    assert analyze(config).action is None


def test_pot_excluding_bets_and_manual_history_must_match_observation():
    config = settings(pot_includes_bets=False)
    assert analyze(config, replace(state(config), pot="0")).action == "RAISE"
    current = state()
    players = list(current.players)
    players[0] = replace(players[0], current_bet="100")
    assert analyze(current=replace(current, players=tuple(players))).action is None


@pytest.mark.parametrize("changes", [
    {"history_confirmed": False}, {"seats": [1, 1]}, {"seats": [1, 7, 3, 6]},
    {"ante_total_bb": "NaN"}, {"rules": []}, {"mode": "TRAINING"},
])
def test_invalid_context_rejected(changes):
    with pytest.raises(ValueError):
        settings(**changes)


def test_rule_ranges_reject_weights_overlap_and_inverted_bounds():
    for changes in [{"raise_range": "AA:0.5"}, {"raise_range": "AA", "call_range": "AA"},
                    {"min_stack_bb": 200, "max_stack_bb": 20}]:
        with pytest.raises(ValueError):
            PreflopRule(id="bad", scenario="unopened", positions=("UTG",), **changes)
