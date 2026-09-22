from dataclasses import replace

import pytest

from app.poker_engine.engine import PokerEngine
from app.poker_engine.models import PokerConfig
from app.poker_engine.postflop import board_texture, draws, hand_strength
from app.poker_engine.range_analysis import compare_ranges
from app.poker_engine.service import confirmed_state
from test_poker import config, state
from test_poker_service import evidence


def cards(value):
    return tuple(value.split())


@pytest.mark.parametrize("hero,board,category,detail", [
    ("As Ah", "Ac 7d 2h", "three_of_a_kind", "set"),
    ("As Kh", "Ac Ad 2h", "three_of_a_kind", "trips"),
    ("As Kh", "7c 7d 7h", "three_of_a_kind", "board_trips"),
    ("As Ah", "Kc 7d 2h", "pair", "overpair"),
    ("2s 2h", "Kc 7d 3h", "pair", "underpair"),
    ("7s 7h", "Kc 5d 3h", "pair", "pocket_pair"),
    ("As Kh", "Ac 7d 2h", "pair", "top_pair"),
    ("7s Kh", "Ac 7d 2h", "pair", "middle_pair"),
    ("2s Kh", "Ac 7d 2h", "pair", "bottom_pair"),
    ("As Kh", "7c 7d 2h", "pair", "board_pair"),
    ("As Kh", "Ac Kd 2h", "two_pair", "two_pair"),
    ("As Ah", "Ac 7d 7h", "full_house", "full_house"),
    ("As Ah", "Ac Ad 7h", "four_of_a_kind", "four_of_a_kind"),
    ("As Ks", "Qs Js Ts", "straight_flush", "straight_flush"),
])
def test_made_hands(hero, board, category, detail):
    result = hand_strength(cards(hero), cards(board))
    assert result["category"] == category and result["detail"] == detail


def test_board_only_best_five_and_kicker_contribution():
    result = hand_strength(cards("2s 3h"), cards("As Kd Qc Jh Ts"))
    assert result["plays_board"] and result["minimum_hole_cards_used"] == 0
    result = hand_strength(cards("As 3h"), cards("Ks Kd Qc Jh 2s"))
    assert not result["plays_board"] and result["detail"] == "board_pair"


@pytest.mark.parametrize("hero,board,kind,count", [
    ("9s 8h", "7d 6c As", "open_ended", 8),
    ("9s 8h", "6d 5c As", "gutshot", 4),
    ("Js 9h", "8d 7c 5s", "double_gutshot", 8),
    ("As 2h", "3d 4c Ks", "one_ended", 4),
    ("As 3h", "4d 5c Ks", "gutshot", 4),
    ("2s 3h", "4d 5c Ks", "open_ended", 8),
    ("As Kh", "Qd Jc 2s", "one_ended", 4),
])
def test_straight_draws_include_wheel_and_distinguish_gutshots(hero, board, kind, count):
    result = draws(cards(hero), cards(board))["straight"]
    assert result["kind"] == kind and result["count"] == count


def test_combo_draw_has_fifteen_unique_completions_and_backdoors_are_separate():
    result = draws(cards("9s 8s"), cards("7s 6c As"))
    assert result["flush"]["count"] == 9
    assert result["straight"]["count"] == 8
    assert result["completion_count"] == 15
    assert len(set(result["completion_cards"])) == 15
    result = draws(cards("As 2s"), cards("7s Kd 9c"))
    assert result["flush"] is None and result["backdoor_flush_suits"] == ["s"]
    assert draws(cards("As 2s"), cards("7s Kd 9c 3h"))["backdoor_flush_suits"] == []


def test_made_hands_river_and_board_only_draws():
    assert draws(cards("As Ks"), cards("7s 6s 2s"))["flush"] is None
    assert draws(cards("9s 8h"), cards("7d 6c 5s"))["straight"] is None
    result = draws(cards("As Ks"), cards("7s 6c 2s 4d 9h"))
    assert result["completion_count"] == 0 and not result["backdoor_straight"]
    result = draws(cards("2s 3h"), cards("9s Th Jd Qc"))
    assert result["straight"] is None  # Both completing ranks play the board.
    assert draws(cards("As Kh"), cards("7s 6s 2s"))["flush"]["count"] == 9
    assert draws(cards("Ad Kh"), cards("7s 6s 2s"))["flush"] is None


@pytest.mark.parametrize("board,pairing,pattern,texture", [
    ("As 8h 2d", "unpaired", [1, 1, 1], "dry"),
    ("As 8s 2d", "unpaired", [2, 1], "semi_coordinated"),
    ("9s 8h 7d", "unpaired", [1, 1, 1], "coordinated"),
    ("As 8s 2s", "unpaired", [3], "coordinated"),
    ("As Ah 2d", "paired", [1, 1, 1], "dry"),
    ("As Ah 2d 2s", "two_pair", [2, 1, 1], "semi_coordinated"),
    ("As Ah Ad 2s 2h", "full_house", [2, 2, 1], "semi_coordinated"),
])
def test_texture_is_reproducible_and_exposes_its_features(board, pairing, pattern, texture):
    result = board_texture(cards(board))
    assert (result["pairing"], result["suit_pattern"], result["texture"]) == (pairing, pattern, texture)


def test_exact_weighted_range_equity_and_absolute_nuts_densities():
    result = compare_ranges(cards("As Kd Qc Jh 2s"), "Ts9s:3,3c4c", "8d7d", 100, 9)
    assert result["hero_equity"] == .75 and result["interval_95"] == [.75, .75]
    assert result["hero"]["current_nuts_fraction"] == .75
    assert result["opponent"]["current_nuts_fraction"] == 0
    assert result["nut_advantage_proxy"] == result["range_advantage"] == "hero"
    assert result["method"] == "exact_river_joint"


def test_board_nuts_are_shared_by_all_ranges():
    result = compare_ranges(cards("As Ks Qs Js Ts"), "2c3c", "4h5h", 100)
    assert result["hero_equity"] == .5
    assert result["hero"]["current_nuts_fraction"] == result["opponent"]["current_nuts_fraction"] == 1
    assert result["nut_advantage_proxy"] == "equal" and result["range_advantage"] == "undetermined"


def test_exact_joint_distribution_conditions_whole_deals_on_collisions():
    result = compare_ranges(cards("As Kd Qc Jh 2s"), "Ts9s:3,3c4c", "Ts8d,7d6d", 100)
    assert result["hero_equity"] == .6  # Legal joint weights 3, 1, 1; not sequential renormalization.
    assert result["samples"] == 3 and result["attempts"] == 4
    assert result["hero"]["current_nuts_fraction"] == .75  # Independent board-conditioned density.


def test_joint_collision_rejection_reproducible_and_blocked_ranges_fail():
    board = cards("As 7h 2d")
    first = compare_ranges(board, "AA,KK", "KK,QQ", 100, 2)
    assert first == compare_ranges(board, "AA,KK", "KK,QQ", 100, 2)
    assert first["hero"]["available_combos"] == 9  # Only the board blocks Hero's range.
    assert first["attempts"] > first["samples"] == 100
    assert first["interval_95"][0] < first["interval_95"][1]
    for hero, opponent in [("AsAh", "KK"), ("KsKh", "KsKh")]:
        with pytest.raises(ValueError):
            compare_ranges(board, hero, opponent, 100)


def test_random_range_preserves_every_unblocked_combo_regardless_of_card_order():
    result = compare_ranges(cards("As 7h 2d"), "random", "random", 100)
    assert result["hero"]["available_combos"] == result["opponent"]["available_combos"] == 1176
    river = compare_ranges(cards("As Ks Qs Js Ts"), "2c3c", "random", 100)
    assert river["opponent"]["available_combos"] == 1081
    assert river["hero_equity"] == .5
    assert river["opponent"]["current_nuts_fraction"] == 1


def test_context_is_hand_bound_and_multiway_does_not_claim_heads_up_advantage():
    settings = config(postflop_context={"hand_id": "hand", "hero_range": "AA,KK", "button_seat": 1})
    result = PokerEngine().analyze(state(), settings)["postflop"]
    assert result["position"]["relative"] == "in_position"
    assert result["position"]["action_order"] == [2, 1]
    assert result["range_comparison"] is not None
    newer = PokerEngine().analyze(state(hand_id="new"), settings)["postflop"]
    assert newer["position"] is newer["range_comparison"] is None
    third = replace(state().players[1], player_id="third", seat=3)
    multi = config(opponents=[{"seat": 2}, {"seat": 3}], postflop_context=settings.postflop_context)
    result = PokerEngine().analyze(state(players=state().players + (third,)), multi)
    assert result["equity"] is not None and result["postflop"]["range_comparison"] is None
    assert result["postflop"]["warnings"]


def test_observed_sizing_uses_start_pot_and_requires_every_contribution():
    result = PokerEngine().analyze(state(), config())["postflop"]["bet_sizing"]
    assert result["street_start_pot"] == "100"
    assert [p["pot_fraction"] for p in result["by_seat"]] == [.5, 1.5]
    for changed in [state(pot="200"), state(pot=None), state(pot_unit="BB"),
                    state(players=(replace(state().players[0], current_bet=None), state().players[1]))]:
        assert PokerEngine().analyze(changed, config())["postflop"]["bet_sizing"] is None


@pytest.mark.parametrize("change", [{"stack": "invalid"}, {"stack": "0"}, {"all_in": True}])
def test_invalid_money_and_all_in_do_not_publish_action_position(change):
    current = state(players=(replace(state().players[0], **change), state().players[1]))
    settings = config(postflop_context={"hand_id": "hand", "button_seat": 1})
    result = PokerEngine().analyze(current, settings)
    assert result["postflop"]["position"] is None
    assert result["postflop"]["hand_strength"]["detail"] == "overpair"


def test_unknown_or_invalid_cards_do_not_produce_postflop_features():
    for changed in [state(hero_cards=()), state(board=("As", "7h", "Kd")),
                    state(street="turn"), state(board=(), street="preflop")]:
        assert PokerEngine().analyze(changed, config())["postflop"] is None
    current = state()
    clean = confirmed_state(current, evidence(current), 4)
    assert PokerEngine().analyze(clean, config())["postflop"] is None


def test_postflop_configuration_rejects_invalid_ranges_and_button():
    for context in [{"hand_id": ""}, {"hand_id": "hand", "hero_range": "AA+"},
                    {"hand_id": "hand", "button_seat": 7}]:
        with pytest.raises(ValueError):
            PokerConfig(postflop_context=context)
