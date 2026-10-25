import json
import os
from uuid import uuid4
from dataclasses import asdict, replace

import pytest
from fastapi.testclient import TestClient

from app.config import Mode, Settings
from app.main import create_app
from app.session_dashboard import summarize
from app.hand_reconstructor.store import HandStore
from app.session_statistics import preflop_statistics
from test_feedback import seed, end_hand
from test_opponents import Stream


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "sessions.sqlite"))
    with TestClient(create_app(Settings(mode=Mode.LIVE_REAL_MONEY))) as current:
        yield current


def test_summary_requires_explicit_session_finish_and_is_private(client):
    data = seed(client)
    end_hand(data)
    store = data[0]
    store.stop_review_capture("scope")
    response = client.get("/api/sessions/scope")
    assert response.headers["cache-control"] == "no-store, private"
    assert response.json()["summary"] is None
    assert client.post("/api/feedback/sessions/scope/finish", json={"session_finished": True}).status_code == 200
    summary = client.get("/api/sessions/scope").json()["summary"]
    assert summary["hands_observed"] == summary["decisions"] == summary["comparable"] == 1
    assert summary["ev_loss_bb"] >= 0
    assert summary["hero_statistics"]["vpip"]["value"] is None  # Missing earlier actions are not folds.
    capture = client.app.state.capture
    capture.state = "running"
    assert client.get("/api/sessions/scope").json()["summary"] is None
    capture.state = "stopped"


def test_access_rechecked_after_summary_computation(client, monkeypatch):
    import app.session_dashboard as module
    data = seed(client)
    end_hand(data)
    data[0].stop_review_capture("scope")
    data[0].finish_review_session("scope", Mode.LIVE_REAL_MONEY)
    original = module.summarize
    def revoke(*args):
        result = original(*args)
        client.app.state.capture.state = "running"
        return result
    monkeypatch.setattr(module, "summarize", revoke)
    assert client.get("/api/sessions/scope").json()["summary"] is None
    client.app.state.capture.state = "stopped"


def test_session_list_pagination_and_mode_isolation(client):
    store = client.app.state.hand_store
    for index in range(23):
        store.start_review_session(f"scope-{index}", "capture", Mode.LIVE_REAL_MONEY, "SESSION_FINISHED")
    store.start_review_session("foreign", "capture", Mode.TRAINING, "SESSION_FINISHED")
    first = client.get("/api/sessions").json()
    last = client.get("/api/sessions?offset=20").json()
    assert first["total"] == 23 and len(first["items"]) == 20 and len(last["items"]) == 3
    assert not ({s["scope_id"] for s in first["items"]} & {s["scope_id"] for s in last["items"]})
    assert client.get("/api/sessions/foreign").status_code == 404
    assert client.get("/api/sessions?offset=-1").status_code == 422


@pytest.mark.parametrize("delta", [None, True, float("nan"), float("inf"), "-2"])
def test_no_comparable_ev_is_unknown_not_zero(client, delta):
    store, frozen, *_ = seed(client)
    p = store.marker
    with store.connection() as db:
        value = json.loads(db.execute(f"SELECT result FROM decision_evaluations WHERE snapshot_id={p}", (frozen.id,)).fetchone()[0])
        value["baseline"]["ev_difference_bb"] = delta
        db.execute(f"UPDATE decision_evaluations SET result={p} WHERE snapshot_id={p}", (json.dumps(value), frozen.id))
    result = summarize(store, "scope", Mode.LIVE_REAL_MONEY)
    assert result["ev_loss_bb"] is None and result["comparable"] == 0


def test_rankings_span_sql_pages_and_cap_at_ten(client):
    store, frozen, *_ = seed(client)
    p = store.marker
    with store.connection() as db:
        raw, evaluation = db.execute(f"SELECT d.payload,e.result FROM decision_snapshots d JOIN decision_evaluations e ON e.snapshot_id=d.id WHERE d.id={p}", (frozen.id,)).fetchone()
        for index in range(105):
            identity = f"synthetic-{index:03}"
            payload, value = json.loads(raw), json.loads(evaluation)
            payload["id"] = identity
            value["baseline"]["ev_difference_bb"] = -float(index)
            db.execute(f"INSERT INTO decision_snapshots VALUES ({p},{p},{p},{p},{p},{p})", (identity, "scope", "hand", 1000 + index, Mode.LIVE_REAL_MONEY, json.dumps(payload)))
            db.execute(f"INSERT INTO decision_evaluations VALUES ({p},{p},{p},{p},{p},{p},{p})", (identity, "scope", "hand", 1000 + index, Mode.LIVE_REAL_MONEY, "{}", json.dumps(value)))
    result = summarize(store, "scope", Mode.LIVE_REAL_MONEY)
    assert result["comparable"] == 106
    assert len(result["top_costs"]) == len(result["best_decisions"]) == 10
    assert result["top_costs"][0]["id"] == "synthetic-104"


@pytest.mark.parametrize("scenario,hero,expected", [
    ("limp", 1, (True, False, None)), ("limp", 2, (False, False, None)),
    ("three_bet", 2, (True, True, True)), ("raise_call", 2, (True, False, False)),
    ("walk", 2, (False, False, None)), ("incomplete", 1, None), ("gap", 1, None),
])
def test_preflop_denominators_require_complete_legal_round(client, scenario, hero, expected):
    stream = Stream()
    stream.emit("HAND_STARTED")
    if scenario == "walk":
        stream.action(1, "FOLDED")
    elif scenario == "limp":
        stream.action(1, "CALLED", 100)
        stream.action(2, "CHECKED")
    else:
        stream.action(1, "RAISED", 300)
        if scenario not in {"incomplete", "gap"}:
            stream.action(2, "RAISED" if scenario == "three_bet" else "CALLED", 900 if scenario == "three_bet" else 300)
            if scenario == "three_bet":
                stream.action(1, "CALLED", 900)
    events = stream.events[1:] if scenario == "gap" else stream.events
    store = client.app.state.hand_store
    store.save([], events, {"mode": Mode.LIVE_REAL_MONEY})
    with store.connection() as db:
        result = preflop_statistics(store, db, "hand", stream.config, hero)
    assert (tuple(result.values()) if result else None) == expected


def test_training_stopped_summary_and_conflicting_hero_assignments(tmp_path, monkeypatch):
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "training.sqlite"))
    with TestClient(create_app(Settings(mode=Mode.TRAINING))) as client:
        data = seed(client, mode=Mode.TRAINING)
        end_hand(data)
        store, _, _, record, context = data
        store.stop_review_capture("scope")
        assert client.get("/api/sessions/scope").json()["allowed"]
        store.save([record], [], context | {"hero_seat": 2})
        result = summarize(store, "scope", Mode.TRAINING)
        assert result["hero_statistics"]["hands_played"] is None


@pytest.mark.parametrize("postgres", [False, True])
def test_confirmed_context_and_hero_survive_without_any_decision_snapshot(tmp_path, postgres):
    if postgres and not os.getenv("HAND_TEST_POSTGRES"):
        pytest.skip("Dedicated PostgreSQL database required")
    store = HandStore(database_url=os.getenv("HAND_TEST_POSTGRES") if postgres else None, path=tmp_path / "stats.sqlite")
    store.initialize()
    stream = Stream()
    stream.emit("HAND_STARTED")
    stream.action(1, "RAISED", 300)
    stream.action(2, "RAISED", 900)
    stream.action(1, "CALLED", 900)
    stream.finish()
    hand, scope = uuid4().hex, uuid4().hex
    events = [event.model_copy(update={"scope_id": scope, "hand_id": hand,
              "state_after": replace(event.state_after, scope_id=scope, hand_id=hand)}) for event in stream.events]
    context = stream.config.model_copy(update={"hand_id": hand})
    store.save_opponents({"scope_id": scope, "revision": 1, "mode": Mode.TRAINING,
                          "profiles": [], "context": context.model_dump(mode="json"), "context_valid": True})
    store.save([{"hand_id": hand, "scope_id": scope, "status": "finished", "started_timestamp": 1,
                 "state": asdict(events[-1].state_after)}], events, {"mode": Mode.TRAINING, "hero_seat": 2})
    result = summarize(store, scope, Mode.TRAINING)
    hero = result["hero_statistics"]
    assert hero["hands_played"] == hero["complete_preflop_hands"] == 1
    assert hero["vpip"]["value"] == hero["pfr"]["value"] == hero["three_bet"]["value"] == 1
    assert result["ev_loss_bb"] is None


@pytest.mark.parametrize("action,equity,classification,gain,expected", [
    ("FOLD", .1, "bluff", 2, "missed_bluffs"),
    ("FOLD", .1, "bluff", -2, None),
    ("RAISE", .2, "value", 2, "costly_aggression"),
    ("RAISE", .8, "value", 2, None),
])
def test_bluff_categories_use_saved_model_values_only(client, action, equity, classification, gain, expected):
    store, frozen, *_ = seed(client)
    p = store.marker
    with store.connection() as db:
        value = json.loads(db.execute(f"SELECT result FROM decision_evaluations WHERE snapshot_id={p}", (frozen.id,)).fetchone()[0])
        value["baseline"]["ev_difference_bb"] = -2
        value["actual_action"]["action"] = action
        value["strategy_result"] = {
            "bluff": {"baseline_strategy": {"bluff_candidate": True, "classification": classification, "ev_gain_bb": gain}},
            "actual_evaluation": {"baseline_strategy": {"equity_when_called": equity}}}
        db.execute(f"UPDATE decision_evaluations SET result={p} WHERE snapshot_id={p}", (json.dumps(value), frozen.id))
    result = summarize(store, "scope", Mode.LIVE_REAL_MONEY)
    for key in ("missed_bluffs", "costly_aggression"):
        assert len(result[key]) == int(key == expected)
