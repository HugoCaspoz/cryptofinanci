from dataclasses import replace
from itertools import combinations

import pytest

from app.game_state_engine.models import GameState, PlayerState
from app.poker_engine.engine import PokerEngine
from app.poker_engine.equity import simulate
from app.poker_engine.evaluator import evaluate
from app.poker_engine.models import PokerConfig
from app.poker_engine.ranges import expand_range


def state(**changes):
    return replace(GameState("scope", (
        PlayerState("hero", 1, stack="1000", current_bet="50", folded=False),
        PlayerState("villain", 2, stack="800", current_bet="150", folded=False),
    ), hand_id="hand", hand_status="active", street="flop", pot="300",
        hero_cards=("As", "Ah"), board=("2s", "7h", "Kd")), **changes)


def config(**changes):
    return PokerConfig(**({"hero_seat": 1, "opponents": [{"seat": 2, "range": "random"}],
                           "pot_includes_bets": True, "samples": 100} | changes))


@pytest.mark.parametrize("cards,rank", [
    ("As Ks Qs Js Ts 2d 3d", (8, 14)),
    ("As Ah Ac Ad Ks Qd 2c", (7, 14, 13)),
    ("Ks Kh Kc Qs Qh Qc 2d", (6, 13, 12)),
    ("As Js 9s 7s 4s 2s Kh", (5, 14, 11, 9, 7, 4)),
    ("As 2d 3h 4c 5s Kh Qh", (4, 5)),
    ("9s 8d 7h 6c 5s 4h 3h", (4, 9)),
    ("Qs Qh Qd As Kc 2d 3d", (3, 12, 14, 13)),
    ("As Ah Ks Kh Qs Qh 2d", (2, 14, 13, 12)),
    ("As Ah Ks Qh Js 9h 2d", (1, 14, 13, 12, 11)),
    ("As Kh Qd 9c 8s 4h 2d", (0, 14, 13, 12, 9, 8)),
])
def test_showdown_categories_and_best_five(cards, rank):
    cards = tuple(cards.split())
    assert evaluate(cards) == rank
    assert max(evaluate(combo) for combo in combinations(cards, 5)) == rank


@pytest.mark.parametrize("expression,count", [("random", 1326), ("AA", 6), ("AKs", 4),
    ("AKo", 12), ("AK", 16), ("AsKh", 1), ("AA:0.5,KK,AKs", 16)])
def test_range_expansion(expression, count):
    assert len(expand_range(expression)) == count


@pytest.mark.parametrize("expression", ["", "AA+", "AAs", "AsAs", "KA", "AK,AKs", "AA:0",
    "AA:nan", "AA:inf", "AA:-1", "random,AA", "AA:101"])
def test_bad_and_ambiguous_ranges_rejected(expression):
    with pytest.raises(ValueError):
        expand_range(expression)


def test_metrics_use_incremental_call_and_total_pot_not_bet_size():
    result = PokerEngine().analyze(state(), config())
    m = result["metrics"]
    assert m["pot_size"] == "300" and m["to_call"] == "100"
    assert m["pot_odds"] == 3 and m["required_equity"] == .25
    assert m["effective_stack"] == "800" and m["spr"] == pytest.approx(800 / 300)
    assert result["equity"]["samples"] == 100
    m = PokerEngine().analyze(state(), config(pot_includes_bets=False))["metrics"]
    assert m["pot_size"] == "500" and m["required_equity"] == pytest.approx(100 / 600)


def test_exact_decimal_amounts_unknown_and_mixed_units():
    original = state()
    players = (replace(original.players[0], current_bet="0.10", stack="1.00"),
               replace(original.players[1], current_bet="0.30", stack="2.00"))
    m = PokerEngine().analyze(replace(original, players=players, pot="0.60"), config())["metrics"]
    assert m["to_call"] == "0.20" and m["required_equity"] == .25
    m = PokerEngine().analyze(replace(original, pot_unit="BB"), config())["metrics"]
    assert m["spr"] is m["required_equity"] is None
    m = PokerEngine().analyze(replace(original, pot=None), config())["metrics"]
    assert m["pot_size"] is m["spr"] is None
    assert PokerEngine().analyze(original, config(pot_includes_bets=None))["metrics"]["pot_size"] is None
    players = (replace(original.players[0], current_bet=None), original.players[1])
    assert PokerEngine().analyze(replace(original, players=players), config())["metrics"]["to_call"] is None


def test_check_zero_pot_short_call_and_side_pots_do_not_invent_thresholds():
    original = state()
    for changed in [replace(original, pot="0"),
                    replace(original, players=(replace(original.players[0], stack="40"), original.players[1])),
                    replace(original, players=(replace(original.players[0], current_bet="150"), original.players[1]))]:
        assert PokerEngine().analyze(changed, config())["metrics"]["required_equity"] is None
    third = PlayerState("third", 3, stack="0", current_bet="30", all_in=True)
    multi = replace(original, players=original.players + (third,))
    settings = config(opponents=[{"seat": 2}, {"seat": 3}])
    result = PokerEngine().analyze(multi, settings)
    assert result["metrics"]["required_equity"] is None
    assert result["metrics"]["effective_by_seat"] == [{"seat": 2, "stack": "800"}, {"seat": 3, "stack": "0"}]
    assert result["equity"] is not None  # Showdown share is distinct from pot eligibility.


def test_incoherent_pot_smaller_than_known_bets_does_not_produce_ratios():
    result = PokerEngine().analyze(state(pot="100"), config())
    assert result["metrics"]["pot_size"] is None
    assert result["metrics"]["spr"] is result["metrics"]["required_equity"] is None
    assert any("incoherente" in warning for warning in result["warnings"])


def test_contributions_of_folded_players_still_belong_in_total_pot():
    original = state(pot="100")
    folded = PlayerState("folded", 3, current_bet="25", folded=True)
    result = PokerEngine().analyze(replace(original, players=original.players + (folded,)),
                                  config(pot_includes_bets=False))
    assert result["metrics"]["pot_size"] == "325"
    assert result["metrics"]["required_equity"] == pytest.approx(100 / 425)


def test_folded_opponents_removed_and_no_advice_generated():
    original = state()
    third = PlayerState("third", 3, folded=True)
    result = PokerEngine().analyze(replace(original, players=original.players + (third,)),
                                  config(opponents=[{"seat": 2}, {"seat": 3, "range": "AsAh"}]))
    assert len(result["equity"]["ranges"]) == 1
    assert "action" not in result and "sizing" not in result
    result = PokerEngine().analyze(replace(original, players=(replace(original.players[0], folded=True), original.players[1])), config())
    assert result["equity"] is result["metrics"] is None


def test_river_exact_weighted_ties_and_blockers():
    tied = simulate(("2c", "3d"), ("As", "Ks", "Qs", "Js", "Ts"), [(2, "random")])
    assert tied["method"] == "exact_river_heads_up" and tied["equity"] == .5
    assert tied["tie_probability"] == 1 and tied["ranges"][0]["available_combos"] == 990
    result = simulate(("As", "Ah"), ("2s", "3h", "7d", "9c", "Ks"), [(2, "KcKh:3,QcQh:1")])
    assert result["equity"] == .25 and result["interval_95"] == [.25, .25]


def test_monte_carlo_reference_reproducibility_and_three_way_split():
    result = simulate(("As", "Ah"), (), [(2, "KcKh")], 5000, 2026)
    assert .78 < result["equity"] < .85  # AA vs KK ~81%, independent known reference.
    assert result == simulate(("As", "Ah"), (), [(2, "KcKh")], 5000, 2026)
    tied = simulate(("2c", "3d"), ("As", "Ks", "Qs", "Js", "Ts"), [(2, "random"), (3, "random")], 100)
    assert tied["equity"] == pytest.approx(1 / 3)
    assert tied["tie_probability"] == 1 and tied["win_probability"] == 0
    assert tied["interval_95"][0] < tied["equity"] < tied["interval_95"][1]


def test_joint_ranges_reject_collisions_without_sequential_bias():
    # Exactly three equally weighted compatible deals: win, lose, lose.
    # Sequential range filtering would give Hero 1/2 instead of 1/3.
    result = simulate(("Ah", "Ac"), ("2s", "3h", "7d", "9c", "Ks"),
                      [(2, "KdKh,QdQh"), (3, "KdKc,JdJh")], 5000)
    assert result["equity"] == pytest.approx(1 / 3, abs=.035)


@pytest.mark.parametrize("hero,board,ranges", [
    (("As", "As"), (), [(2, "random")]),
    (("As", "Ah"), ("As", "2h", "3h"), [(2, "random")]),
    (("As", "Ah"), (), [(2, "AsKh")]),
    (("As", "Ah"), (), [(2, "KcKh"), (3, "KcKh")]),
])
def test_invalid_or_impossible_card_assignments_fail_bounded(hero, board, ranges):
    with pytest.raises(ValueError):
        simulate(hero, board, ranges, 100)
