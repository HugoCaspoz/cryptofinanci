import asyncio
from types import SimpleNamespace

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.main import create_app
from app.websocket_engine.capture_hub import CaptureHub


def snapshot(ws, predicate=lambda capture: True):
    for _ in range(50):
        event = ws.receive_json()
        if event["type"] == "capture.snapshot" and predicate(event["payload"]["capture"]):
            return event
    raise AssertionError("No llegó el snapshot esperado")


def test_latest_snapshot_queue_is_bounded_for_slow_subscribers():
    async def scenario():
        hub = CaptureHub()
        slow, fast = hub.subscribe(), hub.subscribe()
        for revision in range(1000):
            hub.publish({"revision": revision})
            assert (await fast.get())["revision"] == revision
        assert slow.qsize() == 1
        assert (await slow.get())["revision"] == 999
        late = hub.subscribe()
        assert (await late.get())["revision"] == 999
        for queue in [slow, fast, late]:
            hub.unsubscribe(queue)
        assert not hub.subscribers
    asyncio.run(scenario())


def test_subscription_broadcasts_start_frame_stop_and_is_idempotent():
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/live") as first, client.websocket_connect("/ws/live") as second:
            ready = first.receive_json()
            second.receive_json()
            for ws in [first, second]:
                ws.send_json({"type": "capture.subscribe"})
                assert snapshot(ws)["payload"]["capture"]["state"] == "idle"
            first.send_json({"type": "capture.subscribe"})
            first.send_json({"type": "ping"})
            assert first.receive_json()["type"] == "system.pong"
            assert len(app.state.capture_hub.subscribers) == 2
            opened = client.post("/api/capture/screen", json={}).json()
            starts = [snapshot(ws, lambda c: c["state"] == "running") for ws in [first, second]]
            assert all(e["payload"]["capture"]["capture_id"] == opened["capture_id"] for e in starts)
            assert starts[0]["connection_id"] == ready["connection_id"]
            image = cv2.imencode(".jpg", np.zeros((16, 16, 3), np.uint8))[1].tobytes()
            assert client.post(f'/api/capture/{opened["capture_id"]}/screen-frame', content=image).status_code == 204
            frames = [snapshot(ws, lambda c: c["frame"] is not None) for ws in [first, second]]
            assert frames[0]["payload"] == frames[1]["payload"]
            assert frames[0]["payload"]["capture"]["revision"] > opened["revision"]
            client.post(f'/api/capture/{opened["capture_id"]}/stop')
            stopped = [snapshot(ws, lambda c: c["state"] == "stopped") for ws in [first, second]]
            assert all(e["payload"]["capture"]["frame"] is None for e in stopped)
        assert not app.state.capture_hub.subscribers


def test_reconnection_bootstraps_latest_capture_with_new_connection_sequence():
    app = create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/live") as ws:
            original = ws.receive_json()
            ws.send_json({"type": "capture.subscribe"})
            baseline = snapshot(ws)["payload"]["capture"]
        opened = client.post("/api/capture/screen", json={}).json()
        client.post(f'/api/capture/{opened["capture_id"]}/stop')
        with client.websocket_connect("/ws/live") as ws:
            ready = ws.receive_json()
            ws.send_json({"type": "capture.subscribe"})
            restored = snapshot(ws)
            assert ready["connection_id"] != original["connection_id"]
            assert restored["sequence"] == 2
            capture = restored["payload"]["capture"]
            assert capture["state"] == "stopped" and capture["capture_id"] == opened["capture_id"]
            assert capture["server_id"] == baseline["server_id"] and capture["revision"] > baseline["revision"]


def test_backend_restart_has_a_distinct_server_identity():
    identities = []
    for _ in range(2):
        with TestClient(create_app()) as client:
            with client.websocket_connect("/ws/live") as ws:
                ws.receive_json()
                ws.send_json({"type": "capture.subscribe"})
                identities.append(snapshot(ws)["payload"]["capture"]["server_id"])
    assert identities[0] != identities[1]


def test_blocked_socket_times_out_without_retaining_subscriber(monkeypatch):
    from app.websocket_engine import routes
    monkeypatch.setattr(routes, "SEND_TIMEOUT", .02)
    hub = CaptureHub()
    hub.publish({"revision": 1})

    class SlowSocket:
        app = SimpleNamespace(state=SimpleNamespace(capture_hub=hub, settings=SimpleNamespace(mode="TRAINING")))
        received = False
        code = None

        async def accept(self):
            pass

        async def send_json(self, message):
            if message["type"] == "capture.snapshot":
                await asyncio.Event().wait()

        async def receive(self):
            if not self.received:
                self.received = True
                return {"type": "websocket.receive", "text": '{"type":"capture.subscribe"}'}
            await asyncio.Event().wait()

        async def close(self, code, reason=None):
            self.code = code

    socket = SlowSocket()
    asyncio.run(routes.live(socket))
    assert socket.code == 1013 and not hub.subscribers
