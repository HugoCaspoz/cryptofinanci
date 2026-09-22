import asyncio
from dataclasses import replace
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import Mode, Settings
from app.event_engine.engine import EventEngine
from app.hand_reconstructor.store import HandStore
from app.main import create_app
from app.opponent_model.service import OpponentService
from test_opponents import Stream, initial
from test_preflop_service import facts
from test_tournament_context import tournament
from app.opponent_model.models import HandContext


def test_archive_survives_reopen_and_old_revision_cannot_overwrite_new(tmp_path):
    async def scenario():
        store = HandStore(path=tmp_path / "opponents.sqlite")
        store.initialize()
        stream = Stream()
        service = OpponentService("scope", Mode.TRAINING, store)
        context = HandContext(**(stream.config.model_dump() | {"tournament": tournament(population_prior={"label": "Example", "three_bet": .01})}))
        service.model.configure(context, stream.state)
        await service.save()
        old = store.get_opponents("scope")
        stream.action(1, "RAISED", 300)
        stream.action(2, "RAISED", 900)
        await service.update(stream.events, 2, stream.state, 2, 2)
        record = store.get_opponents("scope")
        await service.update(stream.events, 2, stream.state, 2, 2)
        assert store.get_opponents("scope") == record
        store.save_opponents(old)
        assert HandStore(path=store.path).get_opponents("scope") == record
        assert record["profiles"][1]["stats"]["three_bet"]["hits"] == 1
        assert record["adaptive"]["version"] == "action-likelihood-v1"
        assert record["adaptive"]["history"][-1]["evidence"]["opportunities"] == 0
        assert record["adaptive"]["ranges"][1]["effective_combos"] < 1326
        assert record["context"]["tournament"]["buy_in"] == "5.00"
        assert record["adaptive"]["tournament"]["prize_pool"] == "20.00"
        assert record["adaptive"]["history"][-1]["evidence"]["prior_source"]["kind"] == "tournament"
        service.reset("another_scope")
        assert service.model.snapshot()["profiles"] == []
        assert store.get_opponents("scope") == record
    asyncio.run(scenario())


def test_failed_save_keeps_single_pending_snapshot_hides_results_and_retries_without_double_count():
    class Store:
        fail = True
        records = []
        def save_opponents(self, record):
            if self.fail:
                raise OSError("storage unavailable")
            self.records.append(record)

    async def scenario():
        stream = Stream()
        event = stream.action(1, "RAISED", 300)
        store = Store()
        service = OpponentService("scope", Mode.TRAINING, store)
        with pytest.raises(OSError):
            await service.update([event], 1, stream.state, 1, 1)
        assert service.pending is not None and service.snapshot()["analysis"] is None
        with pytest.raises(ValueError):
            service.reset("new")
        store.fail = False
        await service.update([event], 1, stream.state, 1, 1)
        assert len(store.records) == 1
        assert service.snapshot()["analysis"]["profiles"][0]["actions"] == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("change", [{"timestamp": 20}, {"frame_id": 20}, {"scope_id": "foreign"}])
def test_future_or_foreign_actions_never_enter_counters(change):
    async def scenario():
        stream = Stream()
        event = stream.action(1, "RAISED", 300).model_copy(update=change)
        service = OpponentService("scope", Mode.TRAINING)
        await service.update([event], 1, stream.state, 1, 1)
        assert service.snapshot()["analysis"]["profiles"] == []
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", list(Mode))
def test_api_context_binding_websocket_and_private_archive_policy(mode, tmp_path, monkeypatch):
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "api.sqlite"))
    with TestClient(create_app(Settings(mode=mode))) as client:
        capture = client.app.state.capture
        capture_id = client.post("/api/capture/screen", json={}).json()["capture_id"]
        current = initial(scope=capture.observation_state.current_state.scope_id)
        game = capture.observation_state
        game.current_state = current
        game.event_engine = EventEngine(current)
        game.last_observation = SimpleNamespace(frame_id=10, source_timestamp=1, recognition_available=True)
        game.evidence = facts(current)
        config = Stream().config.model_dump(mode="json") | {"capture_id": capture_id, "state_revision": game.changes.revision}
        config["tournament"] = tournament(population_prior={"label": "Study", "three_bet": .01}).model_dump(mode="json")
        assert client.put("/api/opponents/context", json=config | {"tournament": config["tournament"] | {"buy_in": "-1"}}).status_code == 422
        assert client.put("/api/opponents/context", json=config | {"state_revision": 999}).status_code == 409
        assert client.put("/api/opponents/context", json=config | {"mode": "TRAINING"}).status_code == 422
        original_update = capture._opponents_locked
        async def advance_during_save():
            game.changes.revision += 1
        capture._opponents_locked = advance_during_save
        assert client.put("/api/opponents/context", json=config).status_code == 409
        assert capture.opponents.model.hand is None
        capture._opponents_locked = original_update
        config["state_revision"] = game.changes.revision
        assert client.put("/api/opponents/context", json=config).status_code == 200
        assert client.put("/api/opponents/context", json=config).status_code == 422
        assert client.put("/api/opponents/context", json=config | {"tournament": config["tournament"] | {"buy_in": "500"}}).status_code == 422
        assert capture.opponents.model.hand["context"].tournament.buy_in == 5
        visible = mode == Mode.TRAINING
        for payload in [client.get("/api/opponents").json(), client.get("/api/capture").json()["opponents"]]:
            assert (payload["analysis"] is not None) == visible
            if visible:
                assert len(payload["analysis"]["adaptive"]["ranges"]) == 2
                assert payload["analysis"]["adaptive"]["tournament"]["prize_pool"] == "20.00"
        with client.websocket_connect("/ws/live") as ws:
            ws.receive_json()
            ws.send_json({"type": "capture.subscribe"})
            payload = ws.receive_json()["payload"]["capture"]["opponents"]
            assert (payload["analysis"] is not None) == visible
            if visible:
                assert payload["analysis"]["adaptive"]["version"] == "action-likelihood-v1"
                assert payload["analysis"]["context"]["tournament"]["buy_in"] == "5.00"
        archived = client.get(f"/api/opponents/archive/{current.scope_id}")
        assert archived.status_code == (200 if visible else 403)
        if visible:
            assert archived.json()["context"]["tournament"]["population_prior"]["label"] == "Study"
        assert client.put("/api/opponents/showdown", json={"capture_id": capture_id, "hand_id": "hand", "showdown_observed": True}).status_code == 409
        game.current_state = replace(current, hand_status="unidentified")
        client.post(f"/api/capture/{capture_id}/stop")
        client.post("/api/capture/screen", json={})
        assert capture.opponents.model.snapshot()["profiles"] == []
        assert client.put("/api/opponents/context", json=config).status_code == 409


def test_training_cannot_unlock_live_money_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "archive.sqlite"))
    with TestClient(create_app(Settings(mode=Mode.TRAINING))) as client:
        client.app.state.hand_store.save_opponents({"scope_id": "real", "revision": 1, "mode": "LIVE_REAL_MONEY", "profiles": []})
        assert client.get("/api/opponents/archive/real").status_code == 403


@pytest.mark.skipif(not os.getenv("HAND_TEST_POSTGRES"), reason="Dedicated PostgreSQL test database required")
def test_postgres_opponent_archive():
    from uuid import uuid4
    scope = uuid4().hex
    store = HandStore(database_url=os.environ["HAND_TEST_POSTGRES"])
    store.initialize()
    record = {"scope_id": scope, "revision": 1, "mode": "TRAINING", "profiles": [],
              "context": {"tournament": tournament().model_dump(mode="json")},
              "adaptive": {"tournament": tournament().summary()}}
    store.save_opponents(record)
    store.save_opponents(record)
    assert store.get_opponents(scope) == record
