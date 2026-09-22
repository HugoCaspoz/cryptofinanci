import asyncio
from dataclasses import replace
import json

import pytest

from app.config import Mode, Settings
from app.decision_engine.evaluation import DecisionEvaluator, actual_option, resolve_action
from app.decision_engine.evaluation_service import EvaluationService
from app.decision_engine.models import DecisionSnapshot
from app.decision_engine.tracker import DecisionTracker
from app.event_engine.models import PokerEvent
from app.hand_reconstructor.store import HandStore
from app.strategy_engine.engine import StrategyEngine
from test_decisions import setup, freeze, event_for
from test_strategy import facing_bet


def spot(facing=False, mode=Mode.TRAINING):
    s, request = setup(facing_bet) if facing else setup()
    frozen = freeze(DecisionTracker(), s, request, mode=mode)
    return s, request, frozen


def observed(frozen, kind="FOLDED", amount=None):
    request, payload = frozen.request(), frozen.payload()
    hero = next(p for p in request.state.players if p.seat == request.poker.hero_seat)
    changes = {"folded": kind == "FOLDED", "all_in": kind == "ALL_IN"}
    if amount is not None:
        changes.update(current_bet=str(amount), stack=str(int(hero.stack) - (amount - int(hero.current_bet))))
    after = replace(request.state, players=tuple(replace(p, **changes) if p == hero else p for p in request.state.players))
    return PokerEvent(sequence=payload["event_sequence"] + 1, scope_id=after.scope_id, hand_id=after.hand_id,
        frame_id=request.frame_id + 1, timestamp=request.timestamp + 1, type="PLAYER_" + kind,
        player_id=hero.player_id, confidence=.96, amount=str(amount) if amount is not None else None,
        unit=after.blinds_unit if amount is not None else None, action_evidence=("visual_label", "money_delta"), state_after=after)


def link(frozen, event):
    return resolve_action(frozen.record(), [event.model_dump(mode="json")])


def test_fold_delta_uses_old_strategy_and_never_realized_pot_or_later_board():
    _, request, frozen = spot(True)
    event = observed(frozen)
    original = frozen.payload_json
    result = DecisionEvaluator().evaluate(frozen, link(frozen, event))
    reference = StrategyEngine().analyze(request)
    assert result["status"] == "ready"
    for name, key in (("baseline", "baseline_strategy"), ("exploitative", "exploitative_strategy")):
        assert result[name]["actual_ev_bb"] == 0
        assert result[name]["ev_difference_bb"] == pytest.approx(-reference[key]["highest_ev"]["ev_bb"])
        assert result["strategy_result"][key] == reference[key]
    assert result["confidence"]["value"] is None
    assert result["actual_action"]["observation_confidence"] == .96
    assert frozen.payload_json == original
    # The evaluator receives only the action's descriptive facts, never state_after.
    saved_link = link(frozen, event)
    assert "state_after" not in saved_link["actual_event"]
    assert DecisionEvaluator().evaluate(frozen, saved_link) == result


@pytest.mark.parametrize("kind,amount,facing", [("CHECKED", None, False), ("CALLED", 300, True),
    ("BET", 350, False), ("RAISED", 1050, True), ("ALL_IN", 9700, True)])
def test_exact_actual_sizes_and_original_menu_remain_separate(kind, amount, facing):
    _, request, frozen = spot(facing)
    if kind == "ALL_IN":
        amount = int(request.state.players[0].stack) + int(request.state.players[0].current_bet)
    event = observed(frozen, kind, amount)
    result = DecisionEvaluator().evaluate(frozen, link(frozen, event))
    assert result["status"] == "ready", result["reason"]
    reference = StrategyEngine().analyze(request)
    assert result["strategy_result"]["baseline_strategy"] == reference["baseline_strategy"]
    if amount is not None:
        assert result["actual_action"]["total_bb"] == amount / 100
    if kind in {"BET", "RAISED", "ALL_IN"}:
        assert result["baseline"]["size_in_original_menu"] is False
    assert result["baseline"]["actual_ev_bb"] is not None


@pytest.mark.parametrize("kind,amount,change", [
    ("CHECKED", None, {}), ("CALLED", 200, {}), ("RAISED", 400, {}), ("BET", 500, {}),
    ("ALL_IN", 900, {}), ("CALLED", 300, {"unit": "BB"}), ("CALLED", 300, {"amount": "20000"}),
    ("FOLDED", None, {"scope_id": "other"}), ("FOLDED", None, {"sequence": 1}),
])
def test_incoherent_action_is_not_given_an_ev(kind, amount, change):
    _, _, frozen = spot(True)
    event = observed(frozen, kind, amount).model_dump(mode="json") | change
    with pytest.raises(ValueError):
        actual_option(frozen.request(), event)


def test_short_allin_call_is_a_call_not_a_raise():
    s, request, _ = spot(True)
    request = replace(request, state=replace(request.state, players=(replace(request.state.players[0], stack="200"), *request.state.players[1:])))
    frozen = freeze(DecisionTracker(), s, request)
    event = observed(frozen, "ALL_IN", 200)
    result = DecisionEvaluator().evaluate(frozen, link(frozen, event))
    assert result["status"] == "ready"
    assert result["actual_action"]["action"] == "CALL" and result["actual_action"]["all_in"] is True


@pytest.mark.parametrize("cause", ["rival", "gap", "board", "hand", "new_decision", "end"])
def test_ambiguous_link_never_skips_ahead_to_a_later_hero_action(cause):
    _, _, frozen = spot(True)
    event = observed(frozen).model_dump(mode="json")
    if cause == "rival": event["player_id"] = "p2"
    if cause == "gap": event["sequence"] += 1
    if cause == "board": event["state_after"]["board"].append("2h")
    if cause == "hand": event["hand_id"] = "another"
    if cause == "new_decision": event["type"] = "HERO_DECISION_REQUIRED"
    if cause == "end": event["type"] = "CAPTURE_ENDED"
    resolved = resolve_action(frozen.record(), [event, observed(frozen).model_dump(mode="json")])
    assert resolved["link_status"] == "unavailable" and resolved["actual_event"] is None
    assert DecisionEvaluator().evaluate(frozen, resolved)["baseline"] is None


def test_preflop_compares_table_without_inventing_ev_or_confidence():
    s, request, _ = spot()
    table = {"status": "ready", "hand_id": "hand", "reason": "", "action": "FOLD", "sizing_bb": None,
             "additional_bb": 0, "rule_id": "test", "id": "table", "frame_id": 1, "timestamp": 1., "context": {}}
    request = replace(request, state=replace(request.state, street="preflop", board=()), decision=None,
                      preflop={"hero_seat": 1, "result": table})
    frozen = freeze(DecisionTracker(), s, request)
    result = DecisionEvaluator().evaluate(frozen, link(frozen, observed(frozen)))
    assert result["status"] == "table_only"
    assert result["baseline"]["recommendation"]["action"] == "FOLD"
    assert result["baseline"]["ev_difference_bb"] is None and result["confidence"]["value"] is None


def test_missing_model_or_mismatched_version_keeps_actual_action_without_ev():
    s, request, frozen = spot(True)
    unknown = freeze(DecisionTracker(), s, replace(request, decision=None))
    result = DecisionEvaluator().evaluate(unknown, link(unknown, observed(unknown)))
    assert result["status"] == "unavailable" and result["actual_action"]["action"] == "FOLD"
    assert result["baseline"] is None
    data = frozen.payload() | {"ev_model_version": "older-version"}
    old = DecisionSnapshot(frozen.id, json.dumps(data))
    assert "versión" in DecisionEvaluator().evaluate(old, link(old, observed(old)))["reason"]


def test_missing_action_stays_waiting_until_capture_ends():
    _, _, frozen = spot()
    assert resolve_action(frozen.record(), []) is None
    assert resolve_action(frozen.record(), [], ended=True)["link_status"] == "unavailable"
    assert resolve_action(frozen.record(), [], truncated=True)["actual_event"] is None


def archive_job(store, mode=Mode.TRAINING):
    s, request, frozen = spot(True, mode)
    store.save_decision(frozen.record(), event_for(s, frozen, request))
    event = observed(frozen)
    store.save([], [event], {})
    return frozen, event


def test_atomic_link_retry_restart_and_immutable_evaluation(tmp_path):
    store = HandStore(path=tmp_path / "evaluations.sqlite")
    store.initialize()
    frozen, event = archive_job(store)
    store.save([], [event], {})
    assert store.get_evaluation(frozen.id)["status"] == "pending"
    assert store.next_evaluation(Mode.LIVE_REAL_MONEY) is None
    reopened = HandStore(path=store.path)
    reopened.initialize()
    record, resolved = reopened.next_evaluation(Mode.TRAINING)
    assert record["id"] == frozen.id
    result = DecisionEvaluator().evaluate(frozen, resolved)
    reopened.save_evaluation(frozen.id, result)
    reopened.save_evaluation(frozen.id, result)
    with pytest.raises(ValueError):
        reopened.save_evaluation(frozen.id, result | {"status": "changed"})
    assert reopened.next_evaluation(Mode.TRAINING) is None
    assert reopened.get_evaluation(frozen.id)["result"] == result
    assert reopened.get_decision(frozen.id) == frozen.record()


def test_restart_recovers_saved_actions_without_a_job(tmp_path):
    store = HandStore(path=tmp_path / "recover.sqlite")
    store.initialize()
    frozen, _ = archive_job(store)
    with store.connection() as db:
        db.execute("DELETE FROM decision_evaluations")  # Simulate a pre-phase-21 archive.
    store.initialize()
    assert store.get_evaluation(frozen.id)["status"] == "pending"


def test_evaluation_worker_keeps_durable_job_after_failure_and_retries(tmp_path):
    async def run():
        store = HandStore(path=tmp_path / "retry.sqlite")
        store.initialize()
        frozen, _ = archive_job(store)
        real_save = store.save_evaluation
        def fail(*args): raise OSError("unavailable")
        store.save_evaluation = fail
        worker = EvaluationService(Mode.TRAINING, store, lambda: None)
        worker.kick()
        await worker.task
        assert worker.storage_error and store.get_evaluation(frozen.id)["status"] == "pending"
        store.save_evaluation = real_save
        await worker.close()
        assert worker.storage_error is None and worker.revision == 1
        assert store.get_evaluation(frozen.id)["status"] == "complete"
    asyncio.run(run())


def test_postgres_evaluation_if_configured():
    import os
    from uuid import uuid4
    from app.event_engine.engine import EventEngine
    url = os.getenv("HAND_TEST_POSTGRES")
    if not url:
        pytest.skip("Requiere PostgreSQL exclusivo de pruebas")
    s, request, _ = spot(True)
    identity = uuid4().hex
    request = replace(request, state=replace(request.state, scope_id=identity, hand_id=identity),
        sequence=0, decision=replace(request.decision, scope_id=identity, hand_id=identity, event_sequence=0))
    s.bus = EventEngine(request.state)
    frozen = DecisionSnapshot.create(request, mode=Mode.TRAINING, decision_key=identity, actions=[],
        history_complete=False, evidence={}, opponents=None, preflop_config=None)
    store = HandStore(database_url=url)
    store.initialize()
    store.save_decision(frozen.record(), event_for(s, frozen, request))
    event = observed(frozen)
    store.save([], [event], {})
    result = DecisionEvaluator().evaluate(frozen, link(frozen, event))
    store.save_evaluation(frozen.id, result)
    assert store.get_evaluation(frozen.id)["result"] == result
    assert result["status"] == "ready"


def test_training_api_returns_evaluation_and_preserves_snapshot(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "training.sqlite"))
    with TestClient(create_app(Settings(mode=Mode.TRAINING))) as client:
        store = client.app.state.hand_store
        frozen, event = archive_job(store)
        url = f"/api/decisions/{frozen.id}"
        assert client.get(url + "/evaluation").json()["status"] == "pending"
        result = DecisionEvaluator().evaluate(frozen, link(frozen, event))
        store.save_evaluation(frozen.id, result)
        assert client.get(url + "/evaluation").json()["result"] == result
        assert client.get(url).json() == frozen.record()


@pytest.mark.parametrize("mode", list(Mode))
def test_evaluation_api_privacy_and_websocket_do_not_leak_real_results(mode, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "api.sqlite"))
    with TestClient(create_app(Settings(mode=mode))) as client:
        store = client.app.state.hand_store
        frozen, _ = archive_job(store, Mode.LIVE_REAL_MONEY)
        assert client.get(f"/api/decisions/{frozen.id}/evaluation").status_code == 403
        assert client.get("/api/decisions/missing/evaluation").status_code == (404 if mode == Mode.TRAINING else 403)
        with client.websocket_connect("/ws/live") as ws:
            ws.receive_json()
            ws.send_json({"type": "capture.subscribe"})
            status = ws.receive_json()["payload"]["capture"]["evaluations"]
            assert "result" not in status
            if mode == Mode.LIVE_REAL_MONEY:
                assert status["revision"] == 0
