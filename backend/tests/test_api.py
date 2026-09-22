import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Mode, Settings
from app.main import create_app


@pytest.fixture
def client():
    with TestClient(create_app(Settings(mode=Mode.LIVE_REAL_MONEY))) as test_client:
        yield test_client


def test_health_and_empty_sessions(client):
    assert client.get("/health").json()["mode"] == "LIVE_REAL_MONEY"
    assert client.get("/api/sessions").json() == {
        "items": [], "total": 0, "persistence": "not_implemented",
    }
    assert client.get("/api/sessions/missing").status_code == 404


@pytest.mark.parametrize("mode", list(Mode))
def test_websocket_handshake_and_ping(mode):
    with TestClient(create_app(Settings(mode=mode))) as client:
        with client.websocket_connect("/ws/live") as ws:
            ready = ws.receive_json()
            assert ready["type"] == "system.ready"
            assert ready["payload"] == {
                "mode": mode, "phase": 22,
                "capture_available": True, "strategy_available": mode == Mode.TRAINING,
            }
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            assert pong["type"] == "system.pong"
            assert pong["connection_id"] == ready["connection_id"]
            assert pong["sequence"] == ready["sequence"] + 1


def test_invalid_messages_do_not_break_connection_or_change_mode(client):
    with client.websocket_connect("/ws/live") as ws:
        ws.receive_json()
        for message, code in [
            ("invalid", "INVALID_JSON"),
            ("[]", "UNSUPPORTED_MESSAGE"),
            ('{"type":"set_mode","mode":"TRAINING"}', "UNSUPPORTED_MESSAGE"),
        ]:
            ws.send_text(message)
            assert ws.receive_json()["payload"]["code"] == code
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "system.pong"
    assert client.get("/health").json()["mode"] == "LIVE_REAL_MONEY"


def test_oversized_message_closes_socket(client):
    with client.websocket_connect("/ws/live") as ws:
        ws.receive_json()
        ws.send_text("x" * 4097)
        with pytest.raises(WebSocketDisconnect) as error:
            ws.receive_json()
        assert error.value.code == 1009


def test_reconnection_has_its_own_sequence(client):
    with client.websocket_connect("/ws/live") as first:
        original = first.receive_json()
    with client.websocket_connect("/ws/live") as second:
        new = second.receive_json()
        assert new["connection_id"] != original["connection_id"]
        assert new["sequence"] == 1


def test_binary_messages_are_rejected_cleanly(client):
    with client.websocket_connect("/ws/live") as ws:
        ws.receive_json()
        ws.send_bytes(b"binary")
        with pytest.raises(WebSocketDisconnect) as error:
            ws.receive_json()
        assert error.value.code == 1003


def test_invalid_mode_fails_at_startup(monkeypatch):
    monkeypatch.setenv("APP_MODE", "invalid")
    with pytest.raises(ValueError):
        create_app()
