import asyncio
from dataclasses import replace
from threading import Event
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from app.config import Mode, Settings
from app.game_state_engine.models import FieldEvidence
from app.main import create_app
from app.poker_engine.service import PokerService, confirmed_state
from test_poker import config, state


def evidence(current, timestamp=1):
    keys = ["hero_cards", "board", "pot"]
    keys += [f"players.{i}.{field}" for i in range(len(current.players)) for field in ("stack", "current_bet")]
    return {key: FieldEvidence("confirmed", .99, 10, timestamp, "layout") for key in keys}


def test_retained_stale_and_missing_values_never_enter_math():
    current = state()
    facts = evidence(current)
    facts["pot"] = replace(facts["pot"], status="unknown")
    facts["players.0.stack"] = replace(facts["players.0.stack"], status="pending")
    facts.pop("board")
    clean = confirmed_state(current, facts, 1)
    assert clean.pot is None and clean.players[0].stack is None
    assert clean.hero_cards == clean.board == () and clean.street == "unknown"
    assert current.pot == "300" and current.players[0].stack == "1000"
    assert confirmed_state(current, evidence(current), 4).pot is None


def test_latest_only_worker_discards_old_result_and_keeps_loop_responsive():
    async def scenario():
        entered, release = Event(), Event()
        calls, published = [], []

        class SlowEngine:
            def analyze(self, current, settings):
                calls.append(current.pot)
                if len(calls) == 1:
                    entered.set()
                    assert release.wait(3)
                return {"pot": current.pot}

        service = PokerService(Mode.TRAINING, lambda: published.append(service.snapshot()), SlowEngine())
        service.configure(config())
        original = state()
        service.submit(original, evidence(original), 10, 1)
        assert await asyncio.to_thread(entered.wait, 2)
        for i in range(1000):
            changed = replace(original, pot=str(i))
            service.submit(changed, evidence(changed), i, 1)
        assert service.snapshot()["analysis"] is None
        assert service.pending[1].pot == "999"
        # Event loop remains available while native/CPU work is in the worker.
        await asyncio.sleep(.001)
        release.set()
        await service.task
        assert calls == ["300", "999"]
        assert len(published) == 1 and published[0]["analysis"]["pot"] == "999"
        service.submit(changed, evidence(changed), 1001, 1)
        assert calls == ["300", "999"]  # identical input does not re-simulate
        await service.close()
    asyncio.run(scenario())


def test_new_capture_and_new_config_invalidate_inflight_analysis():
    async def scenario():
        entered, release = Event(), Event()
        notifications = []

        class SlowEngine:
            def analyze(self, current, settings):
                entered.set()
                assert release.wait(3)
                return {"hero_seat": settings.hero_seat}

        service = PokerService(Mode.TRAINING, lambda: notifications.append(True), SlowEngine())
        current = state()
        service.configure(config())
        service.submit(current, evidence(current))
        assert await asyncio.to_thread(entered.wait, 2)
        service.reset()
        release.set()
        await service.task
        assert notifications == [] and service.snapshot()["analysis"] is None
        assert service.config.hero_seat is None
        service.configure(config(hero_seat=2, opponents=[{"seat": 1}]))
        service.submit(current, evidence(current))
        await service.task
        assert service.result["hero_seat"] == 2
        await service.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", list(Mode))
def test_api_ws_policy_and_continuous_state_updates(mode):
    application = create_app(Settings(mode=mode))
    with TestClient(application) as client:
        capture = application.state.capture
        opened = client.post("/api/capture/screen", json={}).json()
        current = state()
        capture.observation_state.current_state = current
        capture.observation_state.evidence = evidence(current)
        body = config(postflop_context={"hand_id": "hand", "hero_range": "AA,KK", "button_seat": 1}).model_dump(mode="json") | {"capture_id": opened["capture_id"]}
        stale = body | {"postflop_context": {"hand_id": "old", "hero_range": "AA"}}
        assert client.put("/api/poker/config", json=stale).status_code == 409
        assert client.put("/api/poker/config", json=body).status_code == 200
        deadline = monotonic() + 3
        while client.get("/api/poker").json()["status"] != "ready" and monotonic() < deadline:
            sleep(.01)
        assert capture.poker.result["metrics"]["required_equity"] == .25
        assert capture.poker.result["postflop"]["hand_strength"]["detail"] == "overpair"
        assert capture.poker.result["postflop"]["range_comparison"] is not None
        visible = mode == Mode.TRAINING
        for payload in [client.get("/api/poker").json(), client.get("/api/capture").json()["poker"]]:
            assert (payload["analysis"] is not None) == visible
            if visible:
                assert payload["analysis"]["postflop"]["range_comparison"] is not None
        with client.websocket_connect("/ws/live") as ws:
            assert ws.receive_json()["payload"]["strategy_available"] == visible
            ws.send_json({"type": "capture.subscribe"})
            payload = ws.receive_json()["payload"]["capture"]["poker"]
            assert (payload["analysis"] is not None) == visible
        # New state invalidates the old result immediately, before completing the worker.
        async def update():
            capture.observation_state.current_state = replace(current, pot="500")
            capture._analyze()
            assert capture.poker.result is None
            await capture.poker.task
        client.portal.call(update)
        assert capture.poker.result["metrics"]["required_equity"] == pytest.approx(1 / 6)
        # Avoid synthetic lifecycle state interfering with the capture fixture cleanup.
        capture.observation_state.current_state = replace(current, hand_status="unidentified")
        client.post(f'/api/capture/{opened["capture_id"]}/stop')
        client.post("/api/capture/screen", json={})
        assert client.get("/api/poker").json()["config"]["hero_seat"] is None
        assert client.put("/api/poker/config", json=body).status_code == 409


@pytest.mark.parametrize("change", [
    {"opponents": [{"seat": 1}]}, {"opponents": [{"seat": 2}, {"seat": 2}]},
    {"opponents": [{"seat": 2, "range": "AA+"}]}, {"samples": 5001},
    {"hero_seat": 7}, {"mode": "TRAINING"}, {"opponents": [{"seat": 2, "range": "AA:nan"}]},
])
def test_configuration_rejects_invalid_work_and_mode_override(change):
    with TestClient(create_app(Settings(mode=Mode.LIVE_REAL_MONEY))) as client:
        capture_id = client.post("/api/capture/screen", json={}).json()["capture_id"]
        assert client.put("/api/poker/config", json=config().model_dump(mode="json") | {"capture_id": capture_id} | change).status_code == 422
        assert client.get("/api/poker").json()["config"]["hero_seat"] is None
