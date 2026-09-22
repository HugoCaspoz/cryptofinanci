from dataclasses import replace

import pytest

from app.strategy_engine.bluff import card_effects, perceived_ranges
from app.strategy_engine.ev import split
from test_strategy import analyze, cbet_spot, facing_bet, stream

FIELDS = {"bluff_candidate", "recommended_sizing", "estimated_fold_frequency", "blockers", "unblockers",
          "reason", "baseline_strategy", "exploit_strategy", "showdown_value", "draws", "board_texture", "spr",
          "player_tendencies", "range_advantage"}


def test_equal_strength_combos_split_proportionally_without_suit_order_bias():
    from app.poker_engine.ranges import expand_range
    pool = expand_range("AA")
    board = ("2s", "7h", "Kd")
    for ace in ("As", "Ah", "Ac", "Ad"):
        parts = split(pool, board, (ace, "Qh"), .5)
        assert parts["fold"] == pytest.approx(.5)
        assert dict(parts["strong"]) == dict(parts["weak"])
        assert split(tuple(reversed(pool)), board, (ace, "Qh"), .5)["fold"] == pytest.approx(.5)


def river_spot(s):
    s.action(1, "RAISED", 300)
    s.action(2, "CALLED", 300)
    s.street("flop")
    s.pot = 600
    for street in ("turn", "river"):
        s.action(2, "CHECKED")
        s.action(1, "CHECKED")
        s.street(street)
    s.action(2, "CHECKED")
    return s


def test_card_effects_separate_blockers_from_cards_that_leave_folds_intact():
    board = ("Js", "7c", "4d")
    pool = ((("Ac", "Ad"), .25), (("Jc", "Kc"), .25), (("2s", "3s"), .25), (("5c", "6c"), .25))
    parts = split(pool, board, ("Kc", "2s"), .5)
    blockers, unblockers = card_effects(parts, ("Kc", "2s"), board)
    assert [e["card"] for e in blockers] == ["Kc"] and blockers[0]["continuing_removed"] == pytest.approx(.5)
    assert [e["card"] for e in unblockers] == ["Kc"]  # 2s removes half of the folding weight.
    assert unblockers[0]["random_card_reference"] == pytest.approx(2 / 49)


def test_value_hands_are_never_labelled_bluffs():
    bluff = analyze(river_spot(stream()), cards=("Jh", "Jd"))["bluff"]
    assert FIELDS <= set(bluff) and bluff["applicable"] is True
    for side in ("baseline_strategy", "exploit_strategy"):
        assert bluff[side]["classification"] == "value" and bluff[side]["bluff_candidate"] is False
        assert bluff[side]["bluff_frequency"] == 0
    assert bluff["showdown_value"]["category"] == "high" and bluff["reason"].startswith("Apuesta de valor")


def test_showdown_value_gives_up_the_bluff_and_says_why():
    bluff = analyze(river_spot(stream()), cards=("Ah", "3h"))["bluff"]
    assert bluff["bluff_candidate"] is False and bluff["exploit_strategy"]["classification"] == "bluff"
    assert bluff["exploit_strategy"]["ev_gain_bb"] < 0 and bluff["exploit_strategy"]["passive_action"] == "CHECK"
    assert "valor de showdown" in bluff["reason"] and bluff["showdown_value"]["category"] == "medium"
    assert bluff["baseline_strategy"] == bluff["exploit_strategy"] | {"fold_source": bluff["baseline_strategy"]["fold_source"]}


def test_fold_to_cbet_sample_turns_a_give_up_into_an_exploit_bluff():
    plain = analyze(cbet_spot(stream()), cards=("Ah", "3h"))["bluff"]
    assert plain["baseline_strategy"]["bluff_candidate"] is plain["exploit_strategy"]["bluff_candidate"] is False
    foldy = analyze(cbet_spot(stream({"fold_to_cbet": [70, 100]})), cards=("Ah", "3h"))["bluff"]
    base, exploit = foldy["baseline_strategy"], foldy["exploit_strategy"]
    assert base["bluff_candidate"] is False and exploit["bluff_candidate"] is True
    assert exploit["fold_source"]["statistic"] == "fold_to_cbet" and exploit["fold_source"]["opportunities"] == 100
    assert exploit["estimated_fold_frequency"] > exploit["required_fold_frequency"]
    assert foldy["bluff_candidate"] is True and foldy["recommended_sizing"] == exploit["recommended_sizing"]
    assert foldy["player_tendencies"]["statistics"]["fold_to_cbet"]["data_weight"] == pytest.approx(100 / 130)
    assert exploit["bluff_frequency"] > base["bluff_frequency"]


def test_draws_make_semi_bluffs_but_not_on_the_river():
    flop = analyze(cbet_spot(stream()), cards=("5h", "6h"))["bluff"]
    assert flop["exploit_strategy"]["classification"] == "semi_bluff" and flop["bluff_candidate"] is True
    assert flop["draws"]["straight"] == "open_ended" and flop["draws"]["completion_count"] == 8
    river = analyze(river_spot(stream()), cards=("5h", "6h"))["bluff"]
    assert river["exploit_strategy"]["classification"] == "bluff" and river["draws"]["completion_count"] == 0
    # 5-6 blocks the missed straight draws that fold: no unblockers to offer.
    assert river["unblockers"] == []


def test_wtsd_proxy_lowers_the_exploit_fold_estimate_only_with_a_sample():
    plain = analyze(river_spot(stream()), cards=("Kc", "Qc"))["bluff"]
    assert plain["exploit_strategy"]["estimated_fold_frequency"] == plain["baseline_strategy"]["estimated_fold_frequency"]
    station = analyze(river_spot(stream({"wtsd": [45, 100]})), cards=("Kc", "Qc"))["bluff"]
    source = station["exploit_strategy"]["fold_source"]
    assert source["statistic"] == "wtsd_proxy" and source["scale"] < 1
    assert station["exploit_strategy"]["range_fold_frequency"] < station["baseline_strategy"]["range_fold_frequency"]
    assert station["estimated_fold_frequency"] < station["baseline_strategy"]["estimated_fold_frequency"]


def test_blockers_shift_the_estimated_fold_away_from_the_range_rate():
    bluff = analyze(facing_bet(stream()), cards=("Jh", "Jd"))["bluff"]
    exploit = bluff["exploit_strategy"]
    assert exploit["fold_shift_from_blockers"] == pytest.approx(
        exploit["estimated_fold_frequency"] - exploit["range_fold_frequency"])
    assert exploit["fold_shift_from_blockers"] > 0 and {e["card"] for e in bluff["blockers"]} == {"Jh", "Jd"}
    assert exploit["recommended_sizing"]["action"] == "RAISE" and 0 < exploit["commitment"] < 1


def test_perceived_ranges_compare_what_each_player_represents():
    bluff = analyze(river_spot(stream()), cards=("Ah", "3h"))["bluff"]
    ranges = bluff["range_advantage"]["baseline"]
    assert 0 < ranges["hero_equity"] < 1 and ranges["range_advantage"] in {"hero", "opponent", "undetermined"}
    assert "sin las cartas reales" in ranges["basis"]
    assert perceived_ranges(("Js", "7c", "4d"), (), ((("Ac", "Ad"), 1.0),), 100, 1) is None


def test_no_bet_or_raise_available_means_not_applicable():
    s = facing_bet(stream())
    s.state = replace(s.state, players=(replace(s.state.players[0], stack="200"), *s.state.players[1:]))
    result = analyze(s, cards=("5h", "6h"))
    assert [o["action"] for o in result["baseline_strategy"]["options"]] == ["FOLD", "CALL"]
    assert result["bluff"]["applicable"] is False and result["bluff"]["bluff_candidate"] is False


def test_preflop_and_non_decisions_carry_no_bluff_advice():
    table = {"status": "ready", "reason": "", "action": "FOLD", "sizing_bb": None, "additional_bb": 0,
             "rule_id": "open-late", "id": "x", "hand_id": "hand", "frame_id": 1, "timestamp": 1.0,
             "context": {"position": "BTN/SB"}}
    preflop = analyze(stream(), cards=("7s", "2h"), preflop={"hero_seat": 1, "result": table})
    assert preflop["bluff"]["applicable"] is False and "postflop" in preflop["bluff"]["reason"]
    assert analyze(cbet_spot(stream()), turn="p2")["bluff"] is None
    assert analyze(cbet_spot(stream()), frame=1)["bluff"] is None
