import asyncio
from dataclasses import replace
import json
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import Mode, Settings
from app.game_state_engine.models import FieldEvidence
from app.hand_reconstructor.store import HandStore
from app.main import create_app
from app.strategy_engine.models import StrategyConfig
from app.strategy_engine.strategy_service import StrategyService
from test_strategy import POKER, cbet_spot, stream


def decision_state(s, cards=("5h", "6h"), turn="p1"):
    state = replace(s.state, current_player=turn, hero_cards=cards,
                    pot=str(sum(int(p.current_bet or 0) for p in s.state.players) + s.pot))
    return state, s.model.strategy_input(state)


def submit(service, s, state, decision, frame=100, running=True):
    service.submit(state, POKER, decision, None, frame, float(frame), s.model.cursor, running)


def test_ready_result_is_archived_once_before_publication_and_hidden_in_real_money(tmp_path):
    async def scenario():
        store = HandStore(path=tmp_path / "private.sqlite")
        store.initialize()
        updates = []
        s = cbet_spot(stream())
        state, decision = decision_state(s)
        live = StrategyService(Mode.LIVE_REAL_MONEY, lambda: updates.append(1), store)
        submit(live, s, state, decision)
        await live.task
        assert live.result["status"] == "ready" and updates
        assert live.snapshot()["result"] is None and live.snapshot()["status"] == "ready"
        submit(live, s, state, decision, frame=101)  # Same inputs on a later frame: no new record.
        live.key = None
        submit(live, s, state, decision, frame=102)
        await live.task
        records = store.list_strategy("hand")
        assert len(records) == 1 and records[0]["frame_id"] == 100
        record = records[0]
        assert record["mode"] == "LIVE_REAL_MONEY" and record["result"]["id"] == record["id"]
        assert record["input"]["decision"]["event_sequence"] == decision.event_sequence
        assert len(record["input"]["decision"]["exploit_pools_sha256"]) == 64
        assert record["result"]["baseline_strategy"]["options"][0]["action"] == "CHECK"
        assert store.list_hands()["items"] == []  # Never exposed through the public hand archive.
        training = StrategyService(Mode.TRAINING, lambda: None, store)
        submit(training, s, state, decision)
        await training.task
        assert training.snapshot()["result"]["exploitative_strategy"] is not None
        assert len(store.list_strategy("hand")) == 2
        waiting_state, waiting_decision = decision_state(s, turn="p2")
        submit(training, s, waiting_state, waiting_decision)
        await training.task
        assert training.result["status"] == "waiting" and len(store.list_strategy("hand")) == 2
    asyncio.run(scenario())


def test_storage_failure_never_publishes_and_retries_the_pending_decision():
    async def scenario():
        class Store:
            failed, saved = True, []

            def save_strategy(self, record):
                if self.failed:
                    raise OSError("disk unavailable")
                self.saved.append(record)
        store = Store()
        s = cbet_spot(stream())
        state, decision = decision_state(s)
        service = StrategyService(Mode.TRAINING, lambda: None, store)
        submit(service, s, state, decision)
        await service.task
        assert service.result is None and service.status == "storage_error"
        assert service.pending_record is not None and service.snapshot()["storage_error"]
        store.failed = False
        await service.flush()
        assert len(store.saved) == 1 and service.pending_record is None and service.storage_error is None
    asyncio.run(scenario())


def test_new_state_stop_and_future_history_clear_or_block_results():
    async def scenario():
        s = cbet_spot(stream())
        state, decision = decision_state(s)
        service = StrategyService(Mode.TRAINING, lambda: None)
        submit(service, s, state, decision)
        await service.task
        assert service.result["status"] == "ready"
        submit(service, s, replace(state, pot="700"), decision)
        assert service.result is None and service.snapshot()["status"] == "pending"
        await service.task
        submit(service, s, state, decision, running=False)
        assert service.status == "inactive" and service.result is None
        submit(service, s, state, decision, frame=1)  # History newer than the evaluated frame is dropped.
        await service.task
        assert service.result["status"] == "unavailable" and "Modelo de rivales" in service.result["reason"]
        service.configure(StrategyConfig(bet_sizes=(0.5,)))
        submit(service, s, state, decision)
        await service.task
        assert [o["sizing_pot"] for o in service.result["baseline_strategy"]["options"]] == [None, 0.5]
        await service.close()
    asyncio.run(scenario())


def facts(current, timestamp):
    keys = ["hero_cards", "board", "pot", "small_blind", "big_blind"]
    keys += [f"players.{i}.{field}" for i in range(len(current.players)) for field in ("stack", "current_bet")]
    return {key: FieldEvidence("confirmed", .99, 100, timestamp, "layout") for key in keys}


def wait_for(client, predicate, timeout=10):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        payload = client.get("/api/strategy").json()
        if predicate(payload):
            return payload
        sleep(.05)
    raise AssertionError(payload)


@pytest.mark.parametrize("mode", list(Mode))
def test_api_and_websocket_publish_only_in_training_and_archive_is_reserved(mode):
    app = create_app(Settings(mode=mode))
    with TestClient(app) as client:
        started = client.post("/api/capture/screen", json={}).json()
        capture = app.state.capture
        s = cbet_spot(stream())
        state, _ = decision_state(s)
        capture.opponents.model = s.model
        capture.observation_state.current_state = state
        capture.observation_state.event_engine = s.bus
        capture.observation_state.evidence = facts(state, 100)
        capture.observation_state.last_observation = SimpleNamespace(frame_id=100, source_timestamp=100,
                                                                     recognition_available=True)
        body = StrategyConfig(bet_sizes=(0.5, 1)).model_dump(mode="json")
        assert client.put("/api/strategy/config", json=body | {"mode": "TRAINING"}).status_code == 422
        assert client.put("/api/strategy/config", json=body).json()["status"] in {"pending", "unavailable"}
        poker = POKER.model_dump(mode="json") | {"capture_id": started["capture_id"]}
        assert client.put("/api/poker/config", json=poker).status_code == 200
        ready = wait_for(client, lambda p: p["status"] == "ready")
        visible = mode == Mode.TRAINING
        assert ready["config"]["bet_sizes"] == [0.5, 1]
        assert (ready["result"] is not None) == visible
        assert (client.get("/api/capture").json()["strategy"]["result"] is not None) == visible
        with client.websocket_connect("/ws/live") as ws:
            assert ws.receive_json()["payload"]["strategy_available"] == visible
            ws.send_json({"type": "capture.subscribe"})
            strategy = ws.receive_json()["payload"]["capture"]["strategy"]
            assert (strategy["result"] is not None) == visible and strategy["visibility"] == (
                "training" if visible else "internal_only")
        archive = client.get("/api/strategy/archive", params={"hand_id": "hand"})
        if visible:
            assert ready["result"]["bluff"]["version"] == "bluff-analyzer-v1"
            assert archive.status_code == 200 and len(archive.json()["items"]) == 1
            assert archive.json()["items"][0]["result"]["bluff"]["exploit_strategy"]["applicable"] is True
            assert archive.json()["items"][0]["result"]["baseline_strategy"]["options"][1]["sizing_pot"] == .5
        else:
            assert archive.status_code == 403
            assert len(app.state.hand_store.list_strategy("hand")) == 1  # Stored for later review.
        assert client.get("/api/hands").json()["items"] == []
        capture.observation_state.current_state = replace(state, hand_status="unidentified")
        client.post(f'/api/capture/{started["capture_id"]}/stop')
        stopped = client.get("/api/strategy").json()
        assert stopped["result"] is None and stopped["status"] == "inactive"
        assert json.dumps(stopped)


def test_postgres_private_strategy_archive_if_configured():
    import os
    from uuid import uuid4
    url = os.getenv("HAND_TEST_POSTGRES")
    if not url:
        pytest.skip("Requiere PostgreSQL exclusivo de pruebas")
    store = HandStore(database_url=url)
    store.initialize()
    hand = f"strategy-{uuid4().hex}"
    record = {"id": uuid4().hex, "hand_id": hand, "scope_id": "test", "frame_id": 7, "mode": "TRAINING",
              "result": {"status": "ready"}}
    store.save_strategy(record)
    store.save_strategy(record | {"result": {"status": "changed"}})
    assert [r["result"]["status"] for r in store.list_strategy(hand)] == ["ready"]
