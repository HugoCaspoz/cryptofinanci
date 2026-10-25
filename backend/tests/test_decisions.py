import asyncio
from dataclasses import FrozenInstanceError, replace
import json
from types import SimpleNamespace

import pytest

from app.capture_engine.engine import CaptureEngine
from app.config import Mode, Settings
from app.decision_engine.models import DecisionSnapshot
from app.decision_engine.service import DecisionService
from app.decision_engine.tracker import DecisionTracker
from app.hand_reconstructor.store import HandStore
from app.strategy_engine.engine import StrategyEngine, StrategyRequest
from app.strategy_engine.models import StrategyConfig
from test_strategy import POKER, cbet_spot, stream
from test_strategy_service import decision_state, facts


def setup(builder=cbet_spot):
    s = stream({"fold_to_cbet": [7, 10]})
    def emit(kind, **kwargs):
        event = s.bus.emit(kind, s.state, s.bus.replay.frame_id + 1, s.bus.replay.timestamp + 1, **kwargs)
        s.events.append(event)
        s.model.consume(event)
        return event
    s.emit = emit
    s.emit("HAND_STARTED")
    builder(s)
    state, decision = decision_state(s)
    return s, StrategyRequest(state, POKER, StrategyConfig(), decision, None, 100, 100., s.model.cursor)


def freeze(tracker, s, request, **changes):
    args = dict(mode=Mode.TRAINING, events=tuple(s.bus.events), evidence=facts(request.state, 100),
                opponents=s.model.snapshot(), preflop_config=None, running=True)
    return tracker.detect(request, **(args | changes))


def event_for(s, snapshot, request):
    return s.bus.emit("HERO_DECISION_REQUIRED", request.state, request.frame_id, request.timestamp,
                      player_id=request.state.current_player, decision_id=snapshot.id)


def test_snapshot_preserves_full_inputs_and_reproduces_analysis_after_later_actions():
    s, request = setup()
    snapshot = freeze(DecisionTracker(), s, request)
    assert snapshot is not None
    original = snapshot.payload_json
    payload = snapshot.payload()
    assert payload["history_complete"] is True
    assert len(payload["request"]["decision"]["exploit_pools"][0][1]) == 1176
    assert len(payload["actions"]) == 3
    assert all(e["sequence"] <= payload["source_event_sequence"] for e in payload["actions"])
    before = StrategyEngine().analyze(snapshot.request())
    assert before["status"] == "ready"
    s.action(1, "BET", 300)
    s.action(2, "CALLED", 300)
    s.street("turn")
    s.model.profiles[s.model.active[2]]["counts"]["fold_to_cbet"] = [90, 100]
    payload["request"]["state"]["board"].append("As")
    restored = DecisionSnapshot(snapshot.id, original).request()
    assert restored.state.board == request.state.board
    assert restored.decision == request.decision
    assert StrategyEngine().analyze(restored) == before
    assert snapshot.payload_json == original
    with pytest.raises(FrozenInstanceError):
        snapshot.payload_json = "{}"


def test_turn_dedup_ignores_flicker_money_refresh_and_config_changes_but_new_action_reopens():
    s, request = setup()
    tracker = DecisionTracker()
    first = freeze(tracker, s, request)
    event_for(s, first, request)
    same = replace(request, sequence=s.bus.replay.sequence, frame_id=101, timestamp=101.)
    assert freeze(tracker, s, replace(same, state=replace(same.state, current_player=None))) is None
    assert freeze(tracker, s, replace(same, state=replace(same.state, pot="999"), config=StrategyConfig(temperature=.2))) is None
    assert tracker.active == first.payload()["decision_key"]
    # Let the opponent projection consume the descriptive event, then another round.
    s.model.consume(s.bus.events[-1])
    s.action(1, "BET", 300)
    s.action(2, "RAISED", 900)
    state, decision = decision_state(s)
    second = freeze(tracker, s, replace(request, state=state, decision=decision, sequence=s.model.cursor,
                                      frame_id=110, timestamp=110.))
    assert second and second.id != first.id
    assert len(second.payload()["actions"]) == 5


@pytest.mark.parametrize("change", [
    {"hero_cards": ()}, {"current_player": "p2"}, {"pot": None}, {"big_blind": None},
    {"hand_status": "finished"}, {"hero_cards": ("Js", "Ah")},
])
def test_incomplete_or_nonhero_state_does_not_create_decision(change):
    s, request = setup()
    assert freeze(DecisionTracker(), s, replace(request, state=replace(request.state, **change))) is None


def test_future_evidence_wrong_pending_order_and_stale_history_are_rejected():
    s, request = setup()
    evidence = facts(request.state, 100)
    evidence["pot"] = replace(evidence["pot"], confirmed_timestamp=101)
    assert freeze(DecisionTracker(), s, request, evidence=evidence) is None
    for decision in (replace(request.decision, timestamp=101), replace(request.decision, pending=(2, 1)),
                     replace(request.decision, scope_id="other")):
        assert freeze(DecisionTracker(), s, replace(request, decision=decision)) is None
    assert freeze(DecisionTracker(), s, request, events=(s.bus.events[-1].model_copy(update={"timestamp": 101}),)) is None


def test_history_gap_is_explicit_and_optional_inputs_remain_unknown():
    s, request = setup()
    snapshot = freeze(DecisionTracker(), s, replace(request, decision=None), events=(s.bus.events[-1],), opponents=None)
    assert snapshot.payload()["history_complete"] is False
    assert snapshot.payload()["strategy_input_available"] is False
    assert snapshot.payload()["opponents"] is None
    assert len(snapshot.payload()["configured_opponent_ranges"][0]["combos"]) == 1326
    assert snapshot.request().decision is None


def test_atomic_store_is_idempotent_immutable_and_survives_restart(tmp_path):
    s, request = setup()
    snapshot = freeze(DecisionTracker(), s, request)
    event = event_for(s, snapshot, request)
    store = HandStore(path=tmp_path / "decisions.sqlite")
    store.initialize()
    store.save_decision(snapshot.record(), event)
    store.save_decision(snapshot.record(), event)
    original = store.get_decision(snapshot.id)
    with pytest.raises(ValueError, match="reescribirse"):
        store.save_decision(original | {"hero_seat": 2}, event)
    reopened = HandStore(path=store.path)
    reopened.initialize()
    assert reopened.get_decision(snapshot.id) == original
    assert len(store.list_decisions("hand", Mode.TRAINING)["items"]) == 1
    assert store.list_decisions("hand", Mode.LIVE_REAL_MONEY)["items"] == []
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM observed_events").fetchone()[0] == 1


def test_failed_storage_retains_snapshot_without_publication_and_retries():
    class Store:
        fail = True
        saved = []
        def save_decision(self, record, event):
            if self.fail:
                raise OSError("disk unavailable")
            self.saved.append(record)

    async def run():
        s, request = setup()
        tracker = DecisionTracker()
        snapshot = freeze(tracker, s, request)
        store = Store()
        service = DecisionService(Mode.TRAINING, store, lambda: None)
        service.enqueue(snapshot, event_for(s, snapshot, request))
        await service.task
        assert service.pending and service.snapshot(tracker)["recent"] == []
        with pytest.raises(ValueError):
            service.reset()
        store.fail = False
        await service.flush()
        await service.flush()
        assert service.count == 1 and len(store.saved) == 1
        assert service.snapshot(tracker)["active_id"] == snapshot.id
    asyncio.run(run())


def test_capture_links_frozen_strategy_and_keeps_event_stream_contiguous(tmp_path):
    async def run():
        s, request = setup()
        store = HandStore(path=tmp_path / "capture.sqlite")
        store.initialize()
        capture = CaptureEngine(mode=Mode.TRAINING, hand_store=store)
        capture.state = "running"
        game = capture.observation_state
        game.current_state, game.event_engine = request.state, s.bus
        game.evidence = facts(request.state, 100)
        game.last_observation = SimpleNamespace(frame_id=100, source_timestamp=100, recognition_available=True)
        capture.opponents.model = s.model
        capture.poker.configure(POKER)
        capture.preview = ({"frame_id": 100, "timestamp": 100.}, b"exact-frame")
        capture._analyze()
        await capture.decisions.task
        await capture.strategy.task
        snapshot = capture.decisions.current
        assert snapshot and capture.decisions.count == 1
        assert capture.strategy.result["decision_snapshot_id"] == snapshot.id
        original = store.get_decision(snapshot.id)
        assert store.get_decision_frame(snapshot.id) == b"exact-frame"
        assert s.model.cursor == game.event_engine.replay.sequence
        assert game.event_engine.events[-1].type == "HERO_DECISION_REQUIRED"
        capture.strategy.configure(StrategyConfig(temperature=.2))
        capture._analyze()
        await capture.strategy.task
        assert capture.decisions.count == 1
        assert store.get_decision(snapshot.id) == original
        assert capture.strategy.result["timestamp"] == 100
        assert store.list_strategy("hand")[0]["input"]["decision_snapshot_id"] == snapshot.id
        game.current_state = replace(game.current_state, current_player=None)
        capture._analyze()
        await capture.strategy.task
        assert capture.strategy.result["status"] == "waiting"
        await capture.close()
    asyncio.run(run())


def test_inflight_snapshot_result_is_archived_after_hero_acts_but_not_published(tmp_path):
    from threading import Event
    from app.strategy_engine.strategy_service import StrategyService

    async def run():
        s, request = setup()
        frozen = freeze(DecisionTracker(), s, request)
        entered, release = Event(), Event()
        class SlowEngine:
            def analyze(self, req):
                if req.snapshot_id:
                    entered.set()
                    assert release.wait(3)
                return StrategyEngine().analyze(req)
        store = HandStore(path=tmp_path / "slow.sqlite")
        store.initialize()
        service = StrategyService(Mode.TRAINING, lambda: None, store, SlowEngine())
        args = (request.state, request.poker, request.decision, None, 100, 100., request.sequence)
        service.submit(*args, decision_snapshot=frozen)
        assert await asyncio.to_thread(entered.wait, 2)
        service.submit(replace(request.state, current_player=None), *args[1:])
        release.set()
        await service.task
        assert service.result["status"] == "waiting"
        records = store.list_strategy("hand")
        assert len(records) == 1 and records[0]["input"]["decision_snapshot_id"] == frozen.id
        assert records[0]["input"]["state"]["current_player"] == "p1"
        await service.close()
    asyncio.run(run())


def test_snapshot_history_survives_event_ring_rotation():
    s, request = setup()
    tracker = DecisionTracker()
    freeze(tracker, s, replace(request, state=replace(request.state, current_player=None)))
    count = len(tracker.actions)
    for _ in range(50):
        s.emit("GAME_STATE_UPDATED")
        updated = replace(request, sequence=s.bus.replay.sequence, state=replace(request.state, current_player=None))
        freeze(tracker, s, updated)
    assert s.bus.checkpoint.sequence > 0
    frozen = freeze(tracker, s, replace(request, sequence=s.bus.replay.sequence))
    assert frozen.payload()["history_complete"] and len(frozen.payload()["actions"]) == count


def test_postgres_decision_snapshot_if_configured():
    import os
    from uuid import uuid4
    from app.event_engine.engine import EventEngine
    url = os.getenv("HAND_TEST_POSTGRES")
    if not url:
        pytest.skip("Requiere PostgreSQL exclusivo de pruebas")
    _, request = setup()
    identity = uuid4().hex
    request = replace(request, state=replace(request.state, scope_id=identity, hand_id=identity), decision=None, sequence=0)
    source = SimpleNamespace(bus=EventEngine(request.state), model=SimpleNamespace(snapshot=lambda: {}))
    frozen = freeze(DecisionTracker(), source, request)
    store = HandStore(database_url=url)
    store.initialize()
    event = event_for(source, frozen, request)
    store.save_decision(frozen.record(), event)
    store.save_decision(frozen.record(), event)
    assert store.get_decision(frozen.id) == frozen.record()
    assert store.list_decisions(identity, Mode.TRAINING)["items"][0]["id"] == frozen.id


@pytest.mark.parametrize("mode", list(Mode))
def test_private_decision_api_and_cross_mode_archive(mode, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "api.sqlite"))
    with TestClient(create_app(Settings(mode=mode))) as client:
        s, request = setup()
        snapshot = freeze(DecisionTracker(), s, request, mode=mode)
        client.app.state.hand_store.save_decision(snapshot.record(), event_for(s, snapshot, request))
        visible = mode == Mode.TRAINING
        assert client.get("/api/decisions", params={"hand_id": "hand"}).status_code == (200 if visible else 403)
        detail = client.get(f"/api/decisions/{snapshot.id}")
        assert detail.status_code == (200 if visible else 403)
        if visible:
            assert detail.json()["request"]["decision"]["counts"]
            s2, req2 = setup()
            # Another scope is not needed here; a second sequence suffices for the real-money record.
            req2 = replace(req2, sequence=s.bus.replay.sequence, frame_id=101, timestamp=101.)
            private = freeze(DecisionTracker(), s2, req2, mode=Mode.LIVE_REAL_MONEY, events=())
            event = event_for(s, private, replace(req2, sequence=s.bus.replay.sequence))
            record = private.record()
            client.app.state.hand_store.save_decision(record, event)
            assert client.get(f"/api/decisions/{private.id}").status_code == 403
            assert len(client.get("/api/decisions", params={"hand_id": "hand"}).json()["items"]) == 1
        with client.websocket_connect("/ws/live") as ws:
            ws.receive_json()
            ws.send_json({"type": "capture.subscribe"})
            payload = ws.receive_json()["payload"]["capture"]["decisions"]
            assert payload["visibility"] == ("training" if visible else "internal_only")
            if not visible:
                assert payload["recent"] == [] and payload["active_id"] is None
