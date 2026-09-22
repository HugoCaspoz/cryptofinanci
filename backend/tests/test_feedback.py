from dataclasses import asdict, replace
import json

import pytest
from fastapi.testclient import TestClient

from app.config import FeedbackRelease, Mode, Settings
from app.event_engine.models import PokerEvent
from app.main import create_app
from app.decision_engine.evaluation import DecisionEvaluator
from test_decision_evaluation import archive_job, link


def seed(client, release=FeedbackRelease.SESSION_FINISHED, mode=Mode.LIVE_REAL_MONEY):
    store = client.app.state.hand_store
    frozen, action = archive_job(store, mode)
    state = frozen.request().state
    store.start_review_session(state.scope_id, "capture", mode, release)
    record = {"hand_id": state.hand_id, "scope_id": state.scope_id, "status": "active", "number": 1,
        "started_timestamp": 1., "partial_start": False, "state": asdict(state)}
    context = {"mode": mode, "capture_id": "capture", "name": "test"}
    store.save([record], [], context)
    result = DecisionEvaluator().evaluate(frozen, link(frozen, action))
    store.save_evaluation(frozen.id, result)
    store.save_strategy({"id": "strategy", "hand_id": state.hand_id, "scope_id": state.scope_id,
                         "frame_id": 100, "mode": mode, "result": result["strategy_result"]})
    return store, frozen, action, record, context


def end_hand(data, status="finished", emit=True):
    store, frozen, action, record, context = data
    state = replace(frozen.request().state, hand_status=status)
    events = [PokerEvent(type="HAND_FINISHED" if status == "finished" else "CAPTURE_ENDED",
        sequence=action.sequence + 1, scope_id=state.scope_id, hand_id=state.hand_id,
        frame_id=102, timestamp=102., state_after=state)] if emit else []
    store.save([record | {"status": status, "state": asdict(state)}], events, context)


def assert_access(client, frozen, expected):
    for url in (f"/api/decisions?hand_id=hand", f"/api/decisions/{frozen.id}",
                f"/api/decisions/{frozen.id}/evaluation", "/api/strategy/archive?hand_id=hand"):
        response = client.get(url)
        assert response.status_code == expected, (url, response.text)
        assert response.headers["cache-control"] == "no-store, private"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "review.sqlite"))
    with TestClient(create_app(Settings(mode=Mode.LIVE_REAL_MONEY))) as current:
        yield current


def test_hand_policy_needs_persisted_finish_and_is_revoked_by_any_new_active_hand(client):
    data = seed(client, FeedbackRelease.HAND_FINISHED)
    store, frozen, *_ = data
    assert_access(client, frozen, 403)
    end_hand(data, emit=False)
    assert_access(client, frozen, 403)  # A status alone is insufficient.
    end_hand(data)
    assert_access(client, frozen, 200)
    capture = client.app.state.capture
    capture.state = "running"
    capture.observation_state.hands.finished_count = 1
    capture.observation_state.current_state = replace(capture.observation_state.current_state, hand_id="next", hand_status="active")
    assert_access(client, frozen, 403)
    capture.observation_state.current_state = replace(capture.observation_state.current_state, hand_id=None, hand_status="unidentified")
    assert_access(client, frozen, 200)
    capture.state = "stopped"


def test_session_policy_does_not_unlock_on_hand_finish_or_capture_stop(client):
    data = seed(client)
    store, frozen, *_ = data
    end_hand(data)
    assert_access(client, frozen, 403)
    store.stop_review_capture("scope")
    assert_access(client, frozen, 403)
    assert client.post("/api/feedback/sessions/scope/finish", json={"session_finished": False}).status_code == 422
    for _ in range(2):
        assert client.post("/api/feedback/sessions/scope/finish", json={"session_finished": True}).status_code == 200
    assert_access(client, frozen, 200)
    with store.connection() as db:
        rows = db.execute("SELECT payload FROM review_session_events").fetchall()
    assert len(rows) == 1 and json.loads(rows[0][0])["type"] == "SESSION_FINISHED"
    assert store.get_decision(frozen.id) == frozen.record()
    assert client.get("/api/strategy").json()["result"] is None  # Live paths stay private even after release.


def test_partial_capture_requires_explicit_session_finish_even_under_hand_policy(client):
    data = seed(client, FeedbackRelease.HAND_FINISHED)
    store, frozen, *_ = data
    end_hand(data, status="incomplete")
    store.stop_review_capture("scope")
    assert_access(client, frozen, 403)
    assert client.post("/api/feedback/sessions/scope/finish", json={"session_finished": True}).status_code == 200
    assert_access(client, frozen, 200)
    assert store.get("hand")["hand"]["status"] == "incomplete"


def test_finish_rejected_while_running_and_config_only_affects_future_captures(client):
    data = seed(client)
    store, frozen, *_ = data
    capture = client.app.state.capture
    capture.state = "running"
    assert client.put("/api/feedback/config", json={"release": "HAND_FINISHED"}).status_code == 409
    assert client.post("/api/feedback/sessions/scope/finish", json={"session_finished": True}).status_code == 409
    capture.state = "stopped"
    assert client.put("/api/feedback/config", json={"release": "HAND_FINISHED"}).status_code == 200
    assert store.review_session("scope")["release_policy"] == "SESSION_FINISHED"
    assert client.post("/api/feedback/sessions/scope/finish", json={"session_finished": True}).status_code == 409
    store.stop_review_capture("scope")
    assert client.post("/api/feedback/sessions/scope/finish", json={"session_finished": True}).status_code == 409  # Stored hand still active.
    assert_access(client, frozen, 403)


def test_restarts_keep_policy_and_never_treat_crash_as_session_finish(tmp_path, monkeypatch):
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "restart.sqlite"))
    with TestClient(create_app(Settings(mode=Mode.LIVE_REAL_MONEY))) as first:
        data = seed(first)
        frozen = data[1]
        end_hand(data)
    with TestClient(create_app(Settings(mode=Mode.LIVE_REAL_MONEY, feedback_release=FeedbackRelease.HAND_FINISHED))) as second:
        session = second.app.state.hand_store.review_session("scope")
        assert session["status"] == "interrupted" and session["release_policy"] == "SESSION_FINISHED"
        assert_access(second, frozen, 403)
        assert second.post("/api/feedback/sessions/scope/finish", json={"session_finished": True}).status_code == 200
    with TestClient(create_app(Settings(mode=Mode.LIVE_REAL_MONEY))) as third:
        assert_access(third, frozen, 200)
    with TestClient(create_app(Settings(mode=Mode.TRAINING))) as training:
        assert_access(training, frozen, 403)
        assert training.post("/api/feedback/sessions/scope/finish", json={"session_finished": True}).status_code == 409


def test_legacy_archives_require_explicit_closure(client):
    data = seed(client, FeedbackRelease.HAND_FINISHED)
    store, frozen, *_ = data
    end_hand(data)
    with store.connection() as db:
        db.execute("DELETE FROM review_sessions")
    store.initialize()
    assert store.review_session("scope")["release_policy"] == "SESSION_FINISHED"
    assert_access(client, frozen, 403)


def test_finish_retries_capture_closure_after_persistence_failure(client):
    data = seed(client)
    store, frozen, *_ = data
    end_hand(data, status="incomplete")
    capture = client.app.state.capture
    capture.state = "stopped"
    capture.observation_state.current_state = replace(capture.observation_state.current_state, scope_id="scope")
    assert store.review_session("scope")["status"] == "capturing"
    assert client.get("/api/feedback/hands/hand").json()["can_finish"] is True
    assert_access(client, frozen, 403)
    assert client.post("/api/feedback/sessions/scope/finish", json={"session_finished": True}).status_code == 200
    assert_access(client, frozen, 200)
    assert store.get("hand")["hand"]["status"] == "incomplete"


def test_real_mode_descriptive_statistics_have_no_ranges_or_advice(client):
    capture = client.app.state.capture
    from test_strategy import cbet_spot, stream
    source = cbet_spot(stream())
    capture.opponents.model = source.model
    observed = client.get("/api/opponents").json()
    assert observed["analysis"] is None
    assert set(observed["observations"]) == {"profiles", "coverage", "event_sequence", "timestamp"}
    assert observed["observations"]["profiles"][0]["stats"]["vpip"]["opportunities"] >= 1
    with client.websocket_connect("/ws/live") as ws:
        ws.receive_json()
        ws.send_json({"type": "capture.subscribe"})
        payload = ws.receive_json()["payload"]["capture"]
        assert payload["strategy"]["result"] is None
        assert payload["decisions"]["recent"] == []
        assert payload["opponents"]["analysis"] is None
        assert "profiles" in payload["opponents"]["observations"]


def test_training_can_review_while_hand_is_active(tmp_path, monkeypatch):
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "training.sqlite"))
    with TestClient(create_app(Settings(mode=Mode.TRAINING))) as training:
        data = seed(training, mode=Mode.TRAINING)
        capture = training.app.state.capture
        capture.state = "running"
        capture.observation_state.current_state = data[1].request().state
        assert_access(training, data[1], 200)
        capture.state = "stopped"
        capture.observation_state.current_state = replace(capture.observation_state.current_state, hand_status="incomplete")


@pytest.mark.parametrize("method,url", [
    ("list_decisions", "/api/decisions?hand_id=hand"),
    ("get_evaluation", "/api/decisions/{identity}/evaluation"),
    ("list_strategy", "/api/strategy/archive?hand_id=hand"),
])
def test_new_hand_during_archive_read_revokes_response(client, monkeypatch, method, url):
    data = seed(client, FeedbackRelease.HAND_FINISHED)
    store, frozen, *_ = data
    end_hand(data)
    capture = client.app.state.capture
    original = getattr(store, method)
    def slow_read(*args):
        result = original(*args)
        capture.observation_state.current_state = replace(capture.observation_state.current_state, hand_status="active", hand_id="new")
        return result
    monkeypatch.setattr(store, method, slow_read)
    assert client.get(url.format(identity=frozen.id)).status_code == 403


def test_postgres_feedback_policy_if_configured():
    import os
    from uuid import uuid4
    from app.hand_reconstructor.store import HandStore
    from test_decision_evaluation import spot
    url = os.getenv("HAND_TEST_POSTGRES")
    if not url:
        pytest.skip("Requiere PostgreSQL exclusivo de pruebas")
    _, request, _ = spot()
    identity = uuid4().hex
    state = replace(request.state, scope_id=identity, hand_id=identity, hand_status="finished")
    event = PokerEvent(sequence=1, scope_id=identity, hand_id=identity, state_after=state,
                       type="HAND_FINISHED", timestamp=1., frame_id=1)
    store = HandStore(database_url=url)
    store.initialize()
    store.start_review_session(identity, identity, Mode.LIVE_REAL_MONEY, FeedbackRelease.HAND_FINISHED)
    store.save([{"scope_id": identity, "hand_id": identity, "status": "finished", "started_timestamp": 0.,
                 "state": asdict(state)}], [event], {"mode": Mode.LIVE_REAL_MONEY})
    assert store.review_hand(identity)["finished_confirmed"] is True
    store.stop_review_capture(identity)
    store.finish_review_session(identity, Mode.LIVE_REAL_MONEY)
    store.finish_review_session(identity, Mode.LIVE_REAL_MONEY)
    store.initialize()
    assert store.review_session(identity)["status"] == "finished"


@pytest.mark.parametrize("value", ["NOW", "", "HAND_STARTED"])
def test_invalid_feedback_policy_is_rejected(client, value, monkeypatch):
    assert client.put("/api/feedback/config", json={"release": value}).status_code == 422
    monkeypatch.setenv("FEEDBACK_RELEASE", value)
    with pytest.raises(ValueError):
        Settings.from_env()
