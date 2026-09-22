import asyncio
from dataclasses import FrozenInstanceError, replace

import pytest
from pydantic import ValidationError

from app.config import Mode
from app.opponent_model.adaptive import AdaptiveInput, normalize, smoothed
from app.opponent_model.models import HandContext
from app.poker_engine.engine import PokerEngine
from app.poker_engine.service import PokerService
from test_opponents import Stream
from test_poker import config, state
from test_poker_service import evidence


def pool(s, seat=2):
    return dict(s.model.adaptive_input(s.state).pools)[seat]


def summary(s, seat=2):
    return next(r for r in s.model.snapshot()["adaptive"]["ranges"] if r["seat"] == seat)


def seeded(stat="three_bet", hits=0, n=0, **changes):
    s = Stream(configure=False)
    s.model.identities(s.state)
    s.model.profiles[s.model.active[2]]["counts"][stat] = [hits, n]
    s.model.configure(HandContext(**(s.config.model_dump() | changes)), s.state)
    return s


def test_prior_pseudocounts_and_monotonic_observation_weight():
    no_data = smoothed(0, 0, .2, 30)
    assert no_data["rate"] == .2 and no_data["data_weight"] == 0
    small, large = smoothed(1, 2, .2, 30), smoothed(50, 100, .2, 30)
    assert .2 < small["rate"] < large["rate"] < .5
    assert 0 < small["data_weight"] < large["data_weight"] < 1
    assert smoothed(50, 100, .2, 300)["data_weight"] < large["data_weight"]


def test_action_and_sample_size_change_distribution_without_hard_excluding_bluffs():
    tight, loose, sparse = seeded(hits=1, n=100), seeded(hits=42, n=100), seeded(hits=1, n=2)
    effective = []
    for s in (tight, loose, sparse):
        initial = pool(s)
        s.action(1, "RAISED", 300)
        assert pool(s) == initial  # The other actor cannot narrow this player's range.
        s.action(2, "RAISED", 900)
        values = pool(s)
        assert len(values) == 1326 and all(w > 0 for _, w in values)
        assert sum(w for _, w in values) == pytest.approx(1)
        assert dict(values)[tuple(sorted(("As", "Ah")))] > dict(values)[tuple(sorted(("7s", "2h")))]
        effective.append(summary(s)["effective_combos"])
    assert effective[0] < effective[2] < effective[1]


def test_current_hand_does_not_train_its_own_likelihood_or_mutate_old_inputs():
    s = Stream()
    before = s.model.adaptive_input(s.state)
    s.action(1, "RAISED", 300)
    s.action(2, "RAISED", 900)
    frozen = s.model.adaptive_input(s.state)
    history = s.model.snapshot()["adaptive"]
    assert s.stat(2, "three_bet")["opportunities"] == 1
    assert summary(s)["last_update"]["evidence"]["opportunities"] == 0
    s.action(1, "CALLED", 900)
    s.street("flop")
    s.action(2, "BET", 300)
    last = summary(s)["last_update"]
    assert last["evidence"]["statistic"] == "cbet"
    assert last["evidence"]["opportunities"] == 0
    assert before.board == frozen.board == ()
    assert before.pools != frozen.pools
    assert history["board"] == [] and len(history["history"]) == 2
    with pytest.raises(FrozenInstanceError):
        frozen.board = ("As",)
    # Changing a returned summary must not mutate the inference state.
    history["history"][0]["evidence"]["rate"] = 0
    assert s.model.snapshot()["adaptive"]["history"][0]["evidence"]["rate"] > 0


def test_board_blockers_and_checks_do_not_guess_weakness():
    s = Stream()
    s.raised_pot()
    assert len(pool(s)) == 1176
    assert all(not set(c).intersection(s.state.board) for c, _ in pool(s))
    before = pool(s)
    s.action(2, "CHECKED")
    assert pool(s) == before
    s.action(1, "CHECKED")
    s.street("turn")
    assert len(pool(s)) == 1128 and sum(w for _, w in pool(s)) == pytest.approx(1)


def test_prior_weights_and_empty_support_never_expand_to_random():
    s = seeded(range_priors=[{"seat": 2, "range": "JsJh:3,JsJd"}])
    assert sorted(w for _, w in pool(s)) == [.25, .75]
    s.raised_pot()
    assert pool(s) == () and summary(s)["status"] == "empty"
    result = PokerEngine().analyze(s.state, config(range_source="adaptive"), s.model.adaptive_input(s.state))
    assert result["equity"] is None
    assert "compatible" in result["warnings"][-1]


@pytest.mark.parametrize("changes", [
    {"prior_strength": 0}, {"prior_strength": 1001},
    {"range_priors": [{"seat": 3}]},
    {"range_priors": [{"seat": 2}, {"seat": 2}]},
    {"range_priors": [{"seat": 2, "range": "AA,AsAh"}]},
])
def test_invalid_prior_configuration_rejected(changes):
    with pytest.raises(ValidationError):
        seeded(**changes)


@pytest.mark.parametrize("problem", ["gap", "all_in", "identity", "ended", "wrong_action"])
def test_invalid_history_disables_adaptive_equity(problem):
    s = Stream()
    if problem == "all_in":
        s.action(1, "ALL_IN", 9900)
    elif problem == "identity":
        changed = replace(s.state, players=(replace(s.state.players[0], nickname="Other"), *s.state.players[1:]))
        s.model.identities(changed)
    elif problem == "ended":
        s.emit("CAPTURE_ENDED")
    elif problem == "wrong_action":
        s.action(2, "RAISED", 300)
    else:
        event = s.action(1, "RAISED", 300)
        s.model.consume(event.model_copy(update={"sequence": 5}))
    assert s.model.adaptive_input(s.state) is None
    assert summary(s)["status"] == "invalid"
    result = PokerEngine().analyze(s.state, config(range_source="adaptive"))
    assert result["equity"] is None


def test_fold_and_finished_ranges_cannot_be_reused_for_another_hand():
    s = Stream()
    s.action(1, "FOLDED")
    assert summary(s, 1)["status"] == "folded"
    s.finish()
    assert s.model.adaptive_input(s.state) is None
    assert summary(s)["status"] == "finished"
    assert s.model.adaptive_input(replace(s.state, hand_id="new")) is None


def test_exact_weighted_equity_and_range_comparison_use_same_adaptive_pool():
    current = state(street="river", board=("2s", "7h", "Kd", "3c", "4d"))
    weights = normalize([(("Ks", "Kh"), 3), (("Qs", "Qh"), 1)])
    adaptive = AdaptiveInput("scope", "hand", current.board, 7, 10, 1,
                             ((1, ((current.hero_cards, 1.),)), (2, weights)))
    cfg = config(range_source="adaptive", opponents=[{"seat": 2, "range": "AA"}],
                 postflop_context={"hand_id": "hand", "hero_range": "AsAh"})
    result = PokerEngine().analyze(current, cfg, adaptive)
    assert result["equity"]["equity"] == pytest.approx(.25)
    assert result["postflop"]["range_comparison"]["hero_equity"] == pytest.approx(.25)
    assert result["equity"]["ranges"][0]["range"] == "adaptive"
    assert result["range_provenance"]["event_sequence"] == 7
    for stale in (replace(adaptive, hand_id="old"), replace(adaptive, scope_id="old"),
                  replace(adaptive, board=current.board[:3]), replace(adaptive, pools=adaptive.pools[:1]),
                  replace(adaptive, pools=(*adaptive.pools, (3, weights)))):
        assert PokerEngine().analyze(current, cfg, stale)["equity"] is None
    assert PokerEngine().analyze(current, cfg, None)["equity"] is None


def test_adaptive_service_discards_future_input_and_recomputes_when_only_weights_change():
    async def run():
        s = Stream()
        service = PokerService(Mode.TRAINING, lambda: None)
        service.configure(config(range_source="adaptive"))
        first = s.model.adaptive_input(s.state)
        service.submit(s.state, evidence(s.state), 10, 1, first)
        await service.task
        assert service.result["equity"] is not None
        generation = service.generation
        weighted = replace(first, pools=((1, pool(s, 1)), (2, ((("Ks", "Kc"), 1.),))))
        service.submit(s.state, evidence(s.state), 10, 1, weighted)
        await service.task
        assert service.generation > generation
        assert service.result["equity"]["ranges"][0]["available_combos"] == 1
        service.submit(s.state, evidence(s.state), 10, 1, replace(weighted, timestamp=2))
        await service.task
        assert service.result["equity"] is None
        await service.close()
    asyncio.run(run())
