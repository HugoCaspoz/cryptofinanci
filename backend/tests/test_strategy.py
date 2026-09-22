from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.opponent_model.models import HandContext
from app.poker_engine.models import PokerConfig
from app.strategy_engine.engine import StrategyEngine, StrategyRequest
from app.strategy_engine.ev import Spot, called, candidates, evaluate, logit, risky, split
from app.strategy_engine.models import StrategyConfig
from app.tournament_context.models import TournamentContext
from app.tournament_context.stage import stage
from test_opponents import Stream

POKER = PokerConfig(hero_seat=1, opponents=[{"seat": 2}], pot_includes_bets=True, samples=400)


def spot(**changes):
    return replace(Spot("flop", 10, 0, 0, 100, 100, 1, "in_position"), **changes)


def stream(counts=None, tournament=None):
    s = Stream(configure=False)
    s.model.identities(s.state)
    for stat, value in (counts or {}).items():
        s.model.profiles[s.model.active[2]]["counts"][stat] = value
    config = s.config if tournament is None else HandContext(**(s.config.model_dump() | {"tournament": tournament}))
    s.model.configure(config, s.state)
    s.pot = 150
    return s


def cbet_spot(s):
    s.action(1, "RAISED", 300)
    s.action(2, "CALLED", 300)
    s.street("flop")
    s.pot = 600
    s.action(2, "CHECKED")
    return s


def facing_bet(s, bet=300):
    s.action(1, "RAISED", 300)
    s.action(2, "CALLED", 300)
    s.street("flop")
    s.pot = 600
    s.action(2, "BET", bet)
    return s


def analyze(s, cards=("7s", "2h"), config=StrategyConfig(), poker=POKER, turn="p1", frame=100, preflop=None):
    state = replace(s.state, current_player=turn, hero_cards=cards,
                    pot=str(sum(int(p.current_bet or 0) for p in s.state.players) + s.pot))
    return StrategyEngine().analyze(StrategyRequest(state, poker, config, s.model.strategy_input(state),
                                                    preflop, frame, float(frame), s.model.cursor))


def frequencies(strategy):
    return {(o["action"], o["sizing_pot"]): o["frequency"] for o in strategy["options"]}


def test_legal_options_depend_on_the_amount_to_call_and_stack():
    config = StrategyConfig()
    assert [o["action"] for o in candidates(spot(), config)] == ["CHECK", "BET", "BET"]
    facing = candidates(spot(pot=14, villain_bet=4), config)
    assert [o["action"] for o in facing] == ["FOLD", "CALL", "RAISE"]
    assert facing[2]["total_bb"] == 12 and facing[2]["added_bb"] == 12
    short = candidates(spot(hero_stack=5), StrategyConfig(bet_sizes=(0.75, 1.5)))
    assert [o["action"] for o in short] == ["CHECK", "ALL_IN"]  # Two sizes over the stack collapse into one.
    covered = candidates(spot(pot=14, villain_bet=4, hero_stack=3), config)
    assert [(o["action"], o["all_in"]) for o in covered] == [("FOLD", False), ("CALL", True)]
    # Villain can only call part of an overbet: Hero's uncovered chips return.
    assert called(spot(villain_stack=4), 8) == (4, 18, True)


def test_break_even_bluff_logit_and_tournament_risk():
    s = spot(pot=10)
    options = candidates(s, StrategyConfig(bet_sizes=(0.5,)))
    result = evaluate(s, options, .05, 0.0, lambda balanced: balanced, (), lambda pool: 0.0, (), ())
    bet = result["options"][1]
    assert bet["fold_probability"] == pytest.approx(5 / 15)
    assert bet["ev_bb"] == pytest.approx(0) and result["options"][0]["ev_bb"] == 0
    assert sum(o["frequency"] for o in result["options"]) == pytest.approx(1)
    assert result["summary"]["CHECK"] == pytest.approx(.5)
    assert logit([0, 10], 1)[1] > .99 and logit([3, 3], 1) == [.5, .5]
    assert risky(.5, 20, 5, 1, 1.3) < risky(.5, 20, 5, 1, 1) == 5


def test_villain_cut_ignores_hero_cards_then_blockers_change_the_fold_rate():
    board = ("Js", "7c", "4d")
    pool = ((("Ac", "Ad"), .25), (("Jc", "Kc"), .25), (("2s", "3s"), .25), (("5c", "6c"), .25))
    # Villain continues with AA and JK (top half) whatever Hero holds.
    neutral = split(pool, board, ("9h", "8h"), .5)
    assert neutral["fold"] == pytest.approx(.5) and [c for c, _ in neutral["continuing"]] == [("Ac", "Ad"), ("Jc", "Kc")]
    blocking = split(pool, board, ("Kc", "Qh"), .5)  # Blocks JK, a continuing combo: more folds.
    assert blocking["fold"] == pytest.approx(2 / 3) and blocking["continuing"] == ((("Ac", "Ad"), 1.0),)
    unblocking = split(pool, board, ("5c", "Qh"), .5)  # Blocks 56, a folding combo: fewer folds.
    assert unblocking["fold"] == pytest.approx(1 / 3) and unblocking["range_fold"] == .5
    partial = split(pool, board, ("9h", "8h"), .6)  # Boundary combo split between both parts.
    assert partial["fold"] == pytest.approx(.6) and dict(partial["weak"])[("Jc", "Kc")] == pytest.approx(.1)
    assert split(pool[1:2], board, ("Kc", "Qh"), 0) is None and split((), board, (), .5) is None


def test_waiting_until_hero_acts_and_nothing_is_recommended():
    s = cbet_spot(stream())
    for result in [analyze(s, turn="p2"), analyze(replace_hero_folded(s))]:
        assert result["status"] == "waiting"
        assert result["baseline_strategy"] is None and result["exploitative_strategy"] is None


def replace_hero_folded(s):
    players = (replace(s.state.players[0], folded=True), *s.state.players[1:])
    s.state = replace(s.state, players=players)
    return s


def test_exploit_equals_baseline_without_observations_then_follows_the_sample():
    empty = analyze(cbet_spot(stream()), cards=("5h", "6h"))
    assert empty["status"] == "ready"
    assert frequencies(empty["baseline_strategy"]) == frequencies(empty["exploitative_strategy"])
    assert empty["adjustments"][1]["statistic"] == "fold_to_cbet" and empty["adjustments"][1]["data_weight"] == 0
    shifts = []
    for counts in ([7, 10], [70, 100]):
        result = analyze(cbet_spot(stream({"fold_to_cbet": counts})), cards=("5h", "6h"))
        base, exploit = result["baseline_strategy"], result["exploitative_strategy"]
        assert base == empty["baseline_strategy"]  # Observations never touch the baseline.
        bet = exploit["options"][1]
        assert bet["balanced_fold_probability"] < bet["range_fold_probability"] < .7
        shifts.append(exploit["summary"]["CHECK"] - base["summary"]["CHECK"])
        assert result["adjustments"][1]["opportunities"] == counts[1]
    assert shifts[1] < shifts[0] <= 0  # More opportunities, larger deviation toward betting.
    assert sum(exploit["summary"].values()) == pytest.approx(1)


def test_fold_statistic_only_applies_to_a_flop_cbet_by_the_preflop_aggressor():
    result = analyze(facing_bet(stream({"fold_to_cbet": [70, 100]})), cards=("Jh", "Jd"))
    assert [o["action"] for o in result["baseline_strategy"]["options"]] == ["FOLD", "CALL", "RAISE"]
    assert result["adjustments"][1]["applied"] is False and result["adjustments"][1]["statistic"] == "wtsd_proxy"
    raise_option = result["exploitative_strategy"]["options"][2]
    assert raise_option["range_fold_probability"] == raise_option["balanced_fold_probability"]
    assert raise_option["fold_probability"] != raise_option["range_fold_probability"]  # Hero's jacks block calls.
    assert result["baseline_strategy"]["summary"]["RAISE"] > .5  # A set on J-7-4 builds the pot.
    assert result["decision"]["position"] == "in_position" and result["decision"]["to_call_bb"] == 3


def test_tournament_population_prior_moves_exploit_ranges_not_baseline():
    tournament = {"buy_in": "5", "currency": "EUR", "tournament_type": "sit_and_go", "starting_stack": 10000,
                  "players": 6, "remaining_players": 6,
                  "population_prior": {"label": "Estudio", "strength": 10, "vpip": .6, "pfr": .5, "three_bet": .3}}
    plain, prior = analyze(cbet_spot(stream())), analyze(cbet_spot(stream(tournament=tournament)))
    assert plain["baseline_strategy"] == prior["baseline_strategy"]
    ranges = prior["adjustments"][0]
    assert ranges["baseline"]["effective_combos"] != ranges["exploit"]["effective_combos"]
    assert prior["tournament"]["stage"] == "unknown" and prior["tournament"]["risk_factor"] == 1


def test_bubble_risk_factor_makes_marginal_calls_less_frequent():
    tournament = {"buy_in": "5", "currency": "EUR", "tournament_type": "sit_and_go", "starting_stack": 10000,
                  "players": 6, "remaining_players": 4, "prize_structure": [
                      {"first_place": 1, "last_place": 1, "amount": "15"},
                      {"first_place": 2, "last_place": 2, "amount": "9"},
                      {"first_place": 3, "last_place": 3, "amount": "6"}]}
    on, off = (analyze(facing_bet(stream(tournament=tournament), 600), cards=("7s", "2h"), config=StrategyConfig(
        tournament_adjustment=enabled)) for enabled in (True, False))
    assert on["tournament"]["stage"] == "bubble" and on["tournament"]["applied"] is True
    assert on["decision"]["risk_factor"] == 1.3 and off["decision"]["risk_factor"] == 1
    assert on["baseline_strategy"]["summary"]["FOLD"] > off["baseline_strategy"]["summary"]["FOLD"]


@pytest.mark.parametrize("remaining,prizes,kind,expected,factor", [
    (None, [3], "mtt", "unknown", 1.0),
    (100, [10], "mtt", "early", 1.0),
    (15, [10], "mtt", "approaching_money", 1.1),
    (11, [10], "mtt", "bubble", 1.3),
    (10, [10], "mtt", "in_the_money", 1.15),
    (11, [10], "satellite", "bubble", 1.6),
    (9, [10], "satellite", "in_the_money", 1.0),
])
def test_stage_boundaries_and_satellite_survival(remaining, prizes, kind, expected, factor):
    paid = prizes[0]
    tiers = [{"first_place": 1, "last_place": paid, "amount": "10"}] if kind == "satellite" else [
        {"first_place": 1, "last_place": 1, "amount": "100"},
        {"first_place": 2, "last_place": paid, "amount": "10"}]
    context = TournamentContext(buy_in="5", currency="EUR", tournament_type=kind, starting_stack=1000,
                                players=200, remaining_players=remaining, prize_structure=tiers)
    result = stage(context)
    assert result["stage"] == expected and result["risk_factor"] == factor and result["paid_places"] == paid
    assert stage(None) is None


def test_unsupported_or_stale_contexts_abstain():
    s = cbet_spot(stream())
    assert analyze(s, frame=1)["reason"].startswith("Historial de rivales posterior")
    assert "Asigna Hero" in analyze(s, poker=PokerConfig())["reason"]
    unknown_pot = analyze(s, poker=PokerConfig(hero_seat=1, opponents=[{"seat": 2}]))
    assert unknown_pot["status"] == "unavailable" and unknown_pot["baseline_strategy"] is None
    state = replace(s.state, current_player="p1", hero_cards=("7s", "2h"), board=("Js", "7c", "4d", "2d"),
                    street="turn")
    stale = StrategyEngine().analyze(StrategyRequest(state, POKER, StrategyConfig(), s.model.strategy_input(s.state),
                                                     None, 100, 100.0, s.model.cursor))
    assert "no corresponde" in stale["reason"]
    missing = StrategyEngine().analyze(StrategyRequest(state, POKER, StrategyConfig(), None, None, 100, 100.0, 0))
    assert "Modelo de rivales" in missing["reason"]


def test_multiway_and_all_in_are_outside_this_version():
    s = Stream(configure=False)
    config = HandContext(**(s.config.model_dump() | {"seats": (1, 2, 3), "button_seat": 3}))
    s.model.configure(config, s.state)
    s.pot = 150
    s.action(3, "CALLED", 100)
    s.action(1, "CALLED", 100)
    s.action(2, "CHECKED")
    s.street("flop")
    s.pot = 300
    assert "heads-up" in analyze(s)["reason"]
    s = facing_bet(stream())
    s.action(1, "ALL_IN", 9900)
    assert analyze(s)["status"] == "unavailable"


def test_preflop_baseline_is_the_confirmed_table_without_invented_frequencies():
    s = stream()
    table = {"status": "ready", "reason": "", "action": "RAISE", "sizing_bb": 2.5, "additional_bb": 2.0,
             "rule_id": "open-late", "id": "abc", "hand_id": "hand", "frame_id": 10, "timestamp": 10.0,
             "context": {"position": "BTN/SB", "effective_stack_bb": 99}}
    result = analyze(s, cards=("As", "Kh"), preflop={"hero_seat": 1, "result": table})
    assert result["status"] == "ready"
    assert result["baseline_strategy"]["summary"] == {"RAISE": 1.0}
    assert result["exploitative_strategy"]["options"] == result["baseline_strategy"]["options"]
    assert result["adjustments"][0]["applied"] is False and result["provenance"]["preflop_result_id"] == "abc"
    assert "Estrategia preflop" in analyze(s, cards=("As", "Kh"))["reason"]
    assert "no coinciden" in analyze(s, cards=("As", "Kh"), preflop={"hero_seat": 3, "result": table})["reason"]
    future = table | {"frame_id": 200}
    assert "posterior" in analyze(s, cards=("As", "Kh"), preflop={"hero_seat": 1, "result": future})["reason"]


@pytest.mark.parametrize("changes", [{"bet_sizes": ()}, {"bet_sizes": (0.05,)}, {"bet_sizes": (0.5, 0.5)},
                                     {"raise_multiplier": 1.5}, {"temperature": 0}, {"mode": "TRAINING"},
                                     {"bet_sizes": (float("nan"),)}])
def test_invalid_strategy_config_rejected(changes):
    with pytest.raises(ValidationError):
        StrategyConfig(**changes)


def test_neutral_reference_ignores_observations_and_counts_are_frozen_at_hand_start():
    plain, observed = stream(), stream({"three_bet": [40, 100]})
    for s in (plain, observed):
        s.action(1, "RAISED", 300)
        s.action(2, "RAISED", 900)
    p, o = plain.model.strategy_input(plain.state), observed.model.strategy_input(observed.state)
    assert p.neutral_pools == o.neutral_pools == p.exploit_pools
    assert o.exploit_pools != o.neutral_pools
    assert observed.stat(2, "three_bet")["opportunities"] == 101  # Counted for future hands only.
    assert ("three_bet", 40, 100) in dict(o.counts)[2]
    assert o.pending == (1,) and o.high_bb == 9 and o.increment_bb == 6 and o.preflop_aggressor is None
