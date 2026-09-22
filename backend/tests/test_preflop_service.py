import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import Mode, Settings
from app.event_engine.engine import EventEngine
from app.hand_reconstructor.store import HandStore
from app.main import create_app
from app.strategy_engine.service import PreflopService
from test_poker_service import evidence
from test_preflop import settings, state, action


def facts(current, timestamp=1):
    result = evidence(current, timestamp)
    result["board"] = replace(result["board"], status="empty")
    result["small_blind"] = result["big_blind"] = result["pot"]
    return result


def test_private_archive_is_durable_deduplicated_and_preserves_inputs(tmp_path):
    async def scenario():
        store = HandStore(path=tmp_path / "private.sqlite")
        store.initialize()
        current = state()
        service = PreflopService(Mode.LIVE_REAL_MONEY, store)
        service.configure(settings(), 0)
        await service.update(current, facts(current), (), 0, 10, 1)
        assert service.result["action"] == "RAISE" and service.snapshot()["result"] is None
        await service.update(current, facts(current, 2), (), 0, 11, 2)
        reopened = HandStore(path=tmp_path / "private.sqlite")
        with reopened.connection() as db:
            records = db.execute("SELECT payload FROM preflop_results").fetchall()
        assert len(records) == 1
        record = json.loads(records[0][0])
        assert record["timestamp"] == 1 and record["input"]["state"]["hero_cards"] == ["As", "Kh"]
        assert record["input"]["config"]["button_seat"] == 6 and record["result"]["sizing_bb"] == 2.5
        assert record["input"]["mode"] == "LIVE_REAL_MONEY"
        assert reopened.get("hand") is None  # Strategy records cannot appear through the hand API.
        assert reopened.list_hands()["items"] == []
    asyncio.run(scenario())


def test_append_observed_actions_not_future_or_missing_events():
    async def scenario():
        config = settings(hero_seat=4)
        before = state(config)
        after = state(config, history=[action(3, "RAISE", 3)])
        event = SimpleNamespace(sequence=1, hand_id="hand", scope_id="scope", timestamp=2, frame_id=20,
                                type="PLAYER_RAISED", amount="300", unit=None, player_id="p3", state_after=after)
        service = PreflopService(Mode.TRAINING)
        service.configure(config, 0)
        await service.update(before, facts(before), (), 0, 10, 1)
        assert service.result["action"] is None  # Not Hero's turn yet.
        await service.update(after, facts(after, 2), (event,), 1, 20, 2)
        assert service.result["action"] == "RAISE" and service.result["sizing_bb"] == 9
        assert len(service.actions) == 1
        await service.update(after, facts(after, 2), (event,), 1, 20, 2)
        assert len(service.actions) == 1
        for bad_sequence, timestamp in [(2, 2), (1, 3)]:
            service.configure(config, 0)
            bad = SimpleNamespace(**(vars(event) | {"sequence": bad_sequence, "timestamp": timestamp}))
            await service.update(after, facts(after, 2), (bad,), bad_sequence, 20, 2)
            assert service.result["action"] is None and service.history_error
        service.configure(config, 1)
        await service.update(replace(after, hand_id="next"), facts(after, 2), (), 1, 20, 2)
        assert service.config is None and service.result is None
    asyncio.run(scenario())


def test_new_state_or_missing_blinds_hides_result_even_during_commit():
    async def scenario():
        current = state()
        service = PreflopService(Mode.TRAINING)
        service.configure(settings(), 0)
        await service.update(current, facts(current), (), 0, 10, 1)
        assert service.snapshot(current, facts(current), 1, 0)["result"]["action"] == "RAISE"
        stale = facts(current)
        stale["big_blind"] = replace(stale["big_blind"], status="unknown")
        assert service.snapshot(current, stale, 1, 0)["result"] is None
        assert service.snapshot(replace(current, current_player="p4"), facts(current), 1, 0)["result"] is None
        assert service.snapshot(current, facts(current), 1, 1)["result"] is None
        assert service.snapshot(current, facts(current), 1, 0, running=False)["result"] is None
        await service.update(current, stale, (), 0, 10, 1)
        assert service.result["action"] is None
    asyncio.run(scenario())


def test_failed_archive_retains_one_pending_record_and_never_publishes():
    async def scenario():
        class Store:
            failed = True
            saved = []
            def save_preflop(self, record):
                if self.failed:
                    raise OSError("disk unavailable")
                self.saved.append(record)
        store = Store()
        service = PreflopService(Mode.TRAINING, store)
        service.configure(settings(), 0)
        current = state()
        with pytest.raises(OSError):
            await service.update(current, facts(current), (), 0, 10, 1)
        assert service.pending_record and service.result is None
        assert service.status == "storage_error"
        service.invalidate()
        assert service.status == "storage_error" and service.pending_record is not None
        store.failed = False
        await service.flush()
        assert len(store.saved) == 1 and service.pending_record is None
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", list(Mode))
def test_api_ws_filter_config_binding_and_no_archive_leak(mode):
    app = create_app(Settings(mode=mode))
    with TestClient(app) as client:
        started = client.post("/api/capture/screen", json={}).json()
        capture = app.state.capture
        current = state()
        capture.observation_state.current_state = current
        capture.observation_state.event_engine = EventEngine(current)
        capture.observation_state.evidence = facts(current)
        capture.observation_state.last_observation = SimpleNamespace(frame_id=10, source_timestamp=1, recognition_available=True)
        body = settings().model_dump(mode="json") | {"capture_id": started["capture_id"], "state_revision": 0}
        response = client.put("/api/preflop/config", json=body)
        assert response.status_code == 200
        visible = mode == Mode.TRAINING
        for payload in [response.json(), client.get("/api/preflop").json(), client.get("/api/capture").json()["preflop"]]:
            assert (payload["result"] is not None) == visible
        with client.websocket_connect("/ws/live") as ws:
            assert ws.receive_json()["payload"]["strategy_available"] == visible
            ws.send_json({"type": "capture.subscribe"})
            payload = ws.receive_json()["payload"]["capture"]["preflop"]
            assert (payload["result"] is not None) == visible
        assert client.get("/api/hands").json()["items"] == []
        for change in [{"hand_id": "wrong"}, {"state_revision": 1}, {"capture_id": "wrong"}]:
            assert client.put("/api/preflop/config", json=body | change).status_code == 409
        assert client.put("/api/preflop/config", json=body | {"mode": "TRAINING"}).status_code == 422
        assert client.put("/api/preflop/config", json=body | {"history_confirmed": False}).status_code == 422
        assert capture.preflop.result["action"] == "RAISE"
        capture.observation_state.current_state = replace(current, hand_status="unidentified")
        client.post(f'/api/capture/{started["capture_id"]}/stop')
        assert client.get("/api/preflop").json()["result"] is None
        assert client.put("/api/preflop/config", json=body).status_code == 409
        assert client.post("/api/capture/file", files={"file": ("invalid.avi", b"not a video", "video/avi")}).status_code == 422
        assert capture.preflop.config.hand_id == "hand"


def test_postgres_private_preflop_archive_if_configured():
    import os
    from uuid import uuid4
    url = os.getenv("HAND_TEST_POSTGRES")
    if not url:
        pytest.skip("Requiere PostgreSQL exclusivo de pruebas")
    store = HandStore(database_url=url)
    store.initialize()
    record = {"id": uuid4().hex, "hand_id": "private-test", "scope_id": "test", "result": {"action": "RAISE"}}
    store.save_preflop(record)
    store.save_preflop(record | {"result": {"action": "FOLD"}})
    with store.connection() as db:
        rows = db.execute("SELECT payload FROM preflop_results WHERE id=%s", (record["id"],)).fetchall()
    assert len(rows) == 1 and json.loads(rows[0][0])["result"]["action"] == "RAISE"
