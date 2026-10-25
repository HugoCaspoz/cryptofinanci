from dataclasses import replace
import ctypes
import io
import json
import os
from uuid import uuid4
import zipfile

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Mode, Settings
from app.main import create_app
from app.auth import COOKIE
from app.card_detector.profiles import CardProfiles
from app.card_detector.demo import render_card
from app.card_detector.models import RANKS, SUITS
from app.capture_engine.source import Frame
from app.decision_engine.tracker import DecisionTracker
from app.opponent_model.engine import OpponentModel
from app.table_detector.layout import TableLayout
from app.table_detector.store import DEFAULT_LAYOUT_PATH, LayoutStore
from app.vision_engine import VisionEngine
from test_decisions import setup, freeze
from test_opponents import Stream


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    library = ctypes.CDLL("libcrypt.so.1")
    library.crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    library.crypt.restype = ctypes.c_char_p
    hashed = library.crypt(b"correct-password", b"$2b$04$abcdefghijklmnopqrstuu").decode()
    monkeypatch.setenv("APP_AUTH_HTPASSWD", "zeros:" + hashed)
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "auth.sqlite"))
    with TestClient(create_app(Settings(mode=Mode.TRAINING))) as client:
        yield client


def test_password_once_session_protects_api_and_websocket(auth_client, monkeypatch):
    client = auth_client
    assert client.get("/api/capture").status_code == 401
    assert client.get("/api/auth/check").status_code == 401
    result = client.post("/api/auth/login", data={"username": "zeros", "password": "correct-password"}, follow_redirects=False)
    assert result.status_code == 303
    assert "HttpOnly" in result.headers["set-cookie"] and "SameSite=lax" in result.headers["set-cookie"]
    monkeypatch.setattr(client.app.state.sessions, "verify", lambda *args: (_ for _ in ()).throw(AssertionError("Password verification repeated")))
    for _ in range(10):
        assert client.get("/api/auth/check").status_code == 204
        assert client.get("/api/capture").status_code == 200
    with client.websocket_connect("/ws/live", headers={"Origin": "http://testserver"}) as ws:
        assert ws.receive_json()["type"] == "system.ready"
    client.post("/api/auth/logout", follow_redirects=False)
    assert client.get("/api/capture").status_code == 401


def test_bad_password_tampered_cookie_and_rate_limit(auth_client):
    for _ in range(5):
        assert auth_client.post("/api/auth/login", data={"username": "zeros", "password": "bad"}).status_code == 401
    assert auth_client.post("/api/auth/login", data={"username": "zeros", "password": "bad"}).status_code == 429
    auth_client.cookies.set(COOKIE, "tampered.invalid")
    assert auth_client.get("/api/auth/check").status_code == 401


def test_origin_checks_prevent_foreign_browser_access(tmp_path, monkeypatch):
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "origins.sqlite"))
    with TestClient(create_app(Settings(mode=Mode.TRAINING))) as client:
        assert client.post("/api/capture/camera", json={}, headers={"Origin": "https://foreign.invalid"}).status_code == 403
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/live", headers={"Origin": "https://foreign.invalid"}):
                pass
        assert client.post("/api/capture/camera", json={}, headers={"Origin": "http://testserver"}).status_code == 201


def test_unknown_empty_seats_do_not_block_decisions_or_opportunities():
    stream, request = setup()
    players = tuple(replace(p, stack=None, current_bet=None) if p.seat > 2 else p for p in request.state.players)
    assert freeze(DecisionTracker(), stream, replace(request, state=replace(request.state, players=players))) is not None
    stream = Stream(configure=False)
    state = replace(stream.state, players=tuple(replace(p, stack=None, current_bet=None, bet_unit=None) if p.seat > 2 else p for p in stream.state.players))
    stream.state = state
    stream.model.configure(stream.config, state)
    stream.action(1, "RAISED", 300)
    stream.action(2, "CALLED", 300)
    assert stream.model.snapshot()["context_valid"]
    assert stream.stat(1, "vpip")["value"] == 1


def profile_zip(extra=False):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps({"name": "Real profile fixture", "platform": "Test room", "empty_bgr": [0, 80, 0]}))
        for rank in RANKS:
            for suit in SUITS:
                archive.writestr(rank + suit + ".png", cv2.imencode(".png", render_card(rank + suit))[1].tobytes())
        if extra:
            archive.writestr("../escape", "blocked")
    return output.getvalue()


def test_profile_import_immutable_selection_and_arbitrary_resolution(tmp_path, monkeypatch):
    profiles = CardProfiles(tmp_path / "profiles")
    raw = profile_zip()
    result = profiles.install(raw)
    assert profiles.install(raw)["id"] == result["id"]
    assert len(profiles.list()) == 1
    monkeypatch.setenv("CARD_PROFILE_ROOT", str(profiles.root))
    value = TableLayout.model_validate_json(DEFAULT_LAYOUT_PATH.read_bytes()).model_dump()
    for group in [value["regions"], *value["players"]]:
        for region in group.values():
            region.update(x=round(region["x"] * 2/3), y=round(region["y"] * 2/3), width=max(1,round(region["width"] * 2/3)), height=max(1,round(region["height"] * 2/3)))
    value.update(width=1280, height=720, platform=result["platform"], card_profile=result["id"], calibrated=True)
    path = tmp_path / "layout.json"
    path.write_text(json.dumps(value))
    observation = VisionEngine(LayoutStore(path)).observe(Frame(1, 0, np.zeros((720,1280,3), np.uint8), 10))
    assert observation.recognition_available
    assert observation.cards.status == "ready" and observation.ocr.status != "resolution_mismatch"


def test_profile_rejects_zip_traversal_and_incomplete_decks(tmp_path):
    profiles = CardProfiles(tmp_path / "profiles")
    with pytest.raises(ValueError):
        profiles.install(profile_zip(extra=True))
    with pytest.raises(ValueError):
        profiles.resolve("../outside")
    assert not (tmp_path / "escape").exists()


def test_session_export_and_confirmed_deletion_keep_other_sessions(tmp_path, monkeypatch):
    from test_feedback import seed, end_hand
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "maintenance.sqlite"))
    with TestClient(create_app(Settings(mode=Mode.TRAINING))) as client:
        data = seed(client, mode=Mode.TRAINING)
        end_hand(data)
        store = data[0]
        store.stop_review_capture("scope")
        store.finish_review_session("scope", Mode.TRAINING)
        store.start_review_session("other", "capture-other", Mode.TRAINING, "SESSION_FINISHED")
        response = client.get("/api/sessions/scope/export")
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert json.loads(archive.read("manifest.json"))["scope_id"] == "scope"
            assert len(archive.read("observed_hands.jsonl").splitlines()) == 1
            assert len(archive.read("decision_snapshots.jsonl").splitlines()) == 1
        from app.session_restore import restore_session
        from app.hand_reconstructor.store import HandStore
        exported = tmp_path / "export.zip"; exported.write_bytes(response.content)
        destination = tmp_path / "restored.sqlite"
        result = restore_session(exported, destination)
        assert result["scope_id"] == "scope" and result["records"] > 0
        restored = HandStore(path=destination)
        assert restored.get_decision(data[1].id)["id"] == data[1].id
        with pytest.raises(FileExistsError):
            restore_session(exported, destination)
        assert client.delete("/api/sessions/scope").status_code == 422
        assert client.request("DELETE", "/api/sessions/scope", json={"confirm_scope": "wrong"}).status_code == 422
        assert client.request("DELETE", "/api/sessions/scope", json={"confirm_scope": "scope"}).status_code == 200
        assert store.review_session("scope") is None
        assert store.review_session("other") is not None
        with store.connection() as db:
            for table in ("decision_evaluations", "decision_snapshots", "observed_hands", "observed_events"):
                assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_opponent_pagination_does_not_recompute_summary(tmp_path, monkeypatch):
    from test_feedback import seed, end_hand
    import app.session_dashboard as dashboard
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "pages.sqlite"))
    with TestClient(create_app(Settings(mode=Mode.TRAINING))) as client:
        data = seed(client, mode=Mode.TRAINING); end_hand(data); data[0].stop_review_capture("scope")
        monkeypatch.setattr(dashboard, "summarize", lambda *args: (_ for _ in ()).throw(AssertionError("Unexpected summary")))
        assert client.get("/api/sessions/scope/opponents?offset=20").status_code == 200


@pytest.mark.parametrize("postgres", [False, True])
def test_closed_session_maintenance_transaction_on_both_databases(tmp_path, monkeypatch, postgres):
    if postgres and not os.getenv("HAND_TEST_POSTGRES"):
        pytest.skip("Dedicated test database required")
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "transaction.sqlite"))
    settings = Settings(mode=Mode.TRAINING, database_url=os.getenv("HAND_TEST_POSTGRES") if postgres else None)
    with TestClient(create_app(settings)) as client:
        scope, hand = uuid4().hex, uuid4().hex
        store = client.app.state.hand_store
        store.start_review_session(scope, "capture", Mode.TRAINING, "SESSION_FINISHED")
        store.save([{"hand_id": hand, "scope_id": scope, "status": "finished", "started_timestamp": 0,
                     "state": {"hero_cards": ["As", "Kh"]}}], [], {"mode": Mode.TRAINING, "hero_seat": 1})
        store.stop_review_capture(scope); store.finish_review_session(scope, Mode.TRAINING)
        assert client.get(f"/api/sessions/{scope}/export").status_code == 200
        assert client.request("DELETE", f"/api/sessions/{scope}", json={"confirm_scope": scope}).status_code == 200
        with store.connection() as db:
            assert db.execute(f"SELECT COUNT(*) FROM observed_hands WHERE hand_id={store.marker}", (hand,)).fetchone()[0] == 0
            assert db.execute(f"SELECT COUNT(*) FROM hand_heroes WHERE hand_id={store.marker}", (hand,)).fetchone()[0] == 0


def test_expired_and_forged_sessions_are_not_accepted(auth_client, monkeypatch):
    auth = auth_client.app.state.sessions
    token = auth.issue()
    monkeypatch.setattr("app.auth.time.time", lambda: 10**12)
    assert not auth.valid(token)
    assert not auth.valid(token[:-1] + ("a" if token[-1] != "a" else "b"))


@pytest.mark.parametrize("origin", ["null", "https://foreign.invalid", "file:///tmp", "https://testserver@foreign.invalid", "https://testserver/path"])
def test_origin_policy_rejects_malformed_or_foreign_origins(origin):
    from app.web_security import trusted_origin
    assert not trusted_origin({"host": "testserver", "origin": origin})
