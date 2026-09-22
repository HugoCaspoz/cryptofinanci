from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.opponent_model.models import HandContext
from app.tournament_context.models import TournamentContext
from test_adaptive_ranges import pool, seeded, summary
from test_opponents import initial


def tournament(**changes):
    return TournamentContext(**({"buy_in": "5.00", "currency": "EUR", "tournament_type": "mtt",
        "starting_stack": 20000, "players": 100, "remaining_players": 20,
        "prize_structure": [{"first_place": 1, "last_place": 1, "amount": "10.10"},
                            {"first_place": 2, "last_place": 3, "amount": "4.95"}]} | changes))


def test_currency_normalization_exact_prizes_and_unknown_is_not_zero():
    value = tournament(currency=" eur ")
    assert value.buy_in == Decimal("5.00") and value.currency == "EUR"
    assert value.summary()["prize_pool"] == "20.00"
    assert value.summary()["paid_places"] == 3
    assert value.model_dump(mode="json")["buy_in"] == "5.00"
    assert TournamentContext.model_validate_json(value.model_dump_json()) == value
    # Buy-in * players is deliberately NOT required to equal the payout pool (fees/guarantees).
    assert tournament(buy_in=0).summary()["prize_pool"] == "20.00"
    unknown = tournament(prize_structure=None).summary()
    assert unknown["prize_pool"] is unknown["paid_places"] is None
    assert tournament(prize_structure=[{"first_place": 1, "last_place": 20, "amount": "50"}],
                      tournament_type="satellite").summary()["prize_pool"] == "1000"


@pytest.mark.parametrize("changes", [
    {"buy_in": -1}, {"buy_in": "NaN"}, {"buy_in": "Infinity"}, {"buy_in": "5.001"},
    {"currency": "€"}, {"tournament_type": "unrecognized"}, {"starting_stack": 0},
    {"starting_stack": 1.5}, {"players": 1}, {"remaining_players": 101},
    {"prize_structure": []},
    {"prize_structure": [{"first_place": 2, "last_place": 3, "amount": "10"}]},
    {"prize_structure": [{"first_place": 1, "last_place": 101, "amount": "10"}]},
    {"prize_structure": [{"first_place": 1, "last_place": 1, "amount": "0"}]},
    {"prize_structure": [{"first_place": 1, "last_place": 1, "amount": "10"},
                         {"first_place": 1, "last_place": 2, "amount": "5"}]},
    {"prize_structure": [{"first_place": 1, "last_place": 1, "amount": "10"},
                         {"first_place": 3, "last_place": 3, "amount": "5"}]},
    {"prize_structure": [{"first_place": 1, "last_place": 1, "amount": "10"},
                         {"first_place": 2, "last_place": 2, "amount": "11"}]},
    {"population_prior": {"label": " "}}, {"population_prior": {"label": "test", "strength": 31}},
    {"population_prior": {"label": "test", "strength": 0}},
    {"population_prior": {"label": "test", "pfr": .9}},
    {"population_prior": {"label": "test", "vpip": float("nan")}},
    {"population_prior": {"label": "test", "three_bet": 2}},
    {"population_prior": {"label": "test", "mode": "TRAINING"}},
])
def test_bad_tournament_inputs_rejected(changes):
    with pytest.raises(ValidationError):
        tournament(**changes)


def test_different_denominators_and_participant_count_validation():
    assert tournament(population_prior={"label": "study", "three_bet": .5, "pfr": .1}).population_prior.three_bet == .5
    with pytest.raises(ValidationError):
        HandContext(hand_id="h", seats=(1, 2, 3), button_seat=1, start_confirmed=True,
                    tournament=tournament(remaining_players=2))


def test_metadata_alone_has_no_effect_on_ranges_and_does_not_replace_observed_money():
    generic = seeded()
    with_context = seeded(tournament=tournament(buy_in="500", starting_stack=20000))
    original = with_context.state
    for s in (generic, with_context):
        s.action(1, "RAISED", 300)
        s.action(2, "RAISED", 900)
    assert pool(generic) == pool(with_context)
    assert summary(with_context)["last_update"]["evidence"]["prior_source"] == {"kind": "generic"}
    assert with_context.state.players[0].stack == original.players[0].stack == "9900"
    assert original.small_blind == "50" and original.pot == "150"


def test_population_prior_changes_ranges_and_its_influence_vanishes_with_data():
    differences = []
    for n in (0, 10, 1000):
        estimates = []
        for rate in (.01, .45):
            ctx = tournament(population_prior={"label": "5 EUR study", "strength": 10, "three_bet": rate})
            s = seeded(hits=n // 10, n=n, tournament=ctx)
            s.action(1, "RAISED", 300)
            s.action(2, "RAISED", 900)
            evidence = summary(s)["last_update"]["evidence"]
            assert evidence["rate"] == pytest.approx((n // 10 + 10 * rate) / (n + 10))
            assert evidence["data_weight"] == pytest.approx(n / (n + 10))
            assert evidence["prior_weight"] == pytest.approx(10 / (n + 10))
            assert evidence["prior_source"]["buy_in"] == "5.00"
            assert evidence["prior_source"]["policy"] == "explicit-population-v1"
            estimates.append((evidence["rate"], pool(s)))
        assert estimates[0][1] != estimates[1][1]
        differences.append(estimates[1][0] - estimates[0][0])
    assert differences[0] > differences[1] > differences[2] > 0
    assert differences[2] < .005


def test_prior_is_immutable_and_current_hand_only_trains_next_hand():
    ctx = tournament(population_prior={"label": "Study", "strength": 10, "three_bet": .01})
    s = seeded(tournament=ctx)
    s.action(1, "RAISED", 300)
    s.action(2, "RAISED", 900)
    evidence = summary(s)["last_update"]["evidence"]
    frozen = s.model.snapshot()
    assert evidence["opportunities"] == 0 and evidence["prior_weight"] == 1
    with pytest.raises(ValidationError):
        ctx.population_prior.three_bet = .9
    with pytest.raises(ValueError, match="ya tiene contexto"):
        s.model.configure(HandContext(**(s.config.model_dump() | {"tournament": tournament(buy_in="500")})), s.state)
    s.action(1, "FOLDED")
    s.finish()
    s.state = initial(hand="next")
    s.emit("HAND_STARTED")
    s.model.configure(HandContext(**(s.config.model_dump() | {"hand_id": "next", "tournament": ctx})), s.state)
    s.action(1, "RAISED", 300)
    s.action(2, "RAISED", 900)
    updated = summary(s)["last_update"]["evidence"]
    assert updated["opportunities"] == 1
    assert updated["prior_weight"] == pytest.approx(10 / 11)
    assert updated["rate"] == pytest.approx(1.1 / 11)
    assert frozen["adaptive"]["history"][-1]["evidence"]["opportunities"] == 0
    assert frozen["context"]["tournament"]["buy_in"] == "5.00"


def test_postflop_and_fold_to_three_bet_keep_generic_prior():
    s = seeded(tournament=tournament(population_prior={"label": "Preflop only", "strength": 1}))
    s.action(1, "RAISED", 300)
    s.action(2, "RAISED", 900)
    s.action(1, "CALLED", 900)
    before = summary(s, 1)["last_update"]["evidence"]
    assert before["statistic"] == "fold_to_three_bet" and before["prior_source"]["kind"] == "generic"
    s.street("flop")
    s.action(2, "BET", 300)
    after = summary(s)["last_update"]["evidence"]
    assert after["statistic"] == "cbet"
    assert after["prior_strength"] == 30 and after["prior_source"]["kind"] == "generic"
