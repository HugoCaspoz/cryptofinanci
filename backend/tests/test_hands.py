import asyncio
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient

from app.hand_reconstructor.store import HandStore
from app.main import create_app
from test_game_state import Stream


def boundaries(stream):
    return [e for e in stream.engine.event_engine.events if e.type in {"HAND_STARTED", "HAND_FINISHED"}]


def test_confirmed_board_clear_and_empty_hero_finish_once_and_archive_last_board():
    stream = Stream()
    first = stream.send(board=("Js", "7c", "4d"))
    stream.send(hero=(), board=(), count=7)
    assert [e.type for e in boundaries(stream)] == ["HAND_STARTED", "HAND_FINISHED"]
    finish = boundaries(stream)[-1]
    assert finish.hand_id == first["hand_id"] and finish.state_after.board == ("Js", "7c", "4d")
    assert finish.state_after.hand_status == "finished"
    stream.send(hero=(), board=(), count=30)
    assert stream.engine.hands.finished_count == 1
    assert stream.engine.current_state.hand_id is None
    assert stream.engine.event_engine.events[-1].hand_id is None
    next_state = stream.send(hero=("Qh", "Qs"))
    assert next_state["hand_id"] != first["hand_id"]
    assert [e.type for e in boundaries(stream)] == ["HAND_STARTED", "HAND_FINISHED", "HAND_STARTED"]
    assert not stream.engine.hands.active["partial_start"]
    assert next_state["pot"] is None and next_state["players"][0]["current_bet"] is None
    assert stream.send(hero=("Qh", "Qs"))["pot"] == "750"


def test_fold_occlusion_and_board_correction_do_not_split_hands():
    stream = Stream()
    first = stream.send(board=("Js", "7c", "4d"))
    stream.send(hero=(), board=("Js", "7c", "4d"), count=10)
    stream.send(hero=None, board=None, count=10)
    stream.send(hero=("As", "Jh"), board=("Js", "7c", "5d"), count=5)
    assert stream.engine.current_state.hand_id == first["hand_id"]
    assert stream.engine.hands.finished_count == 0


def test_preflop_hero_disappearing_is_not_sufficient_to_finish():
    stream = Stream()
    first = stream.send()
    stream.send(hero=(), board=(), count=10)
    assert stream.engine.hands.finished_count == 0
    stream.send(hero=("Qh", "Qs"), board=())
    assert stream.engine.hands.finished_count == 1
    assert stream.engine.current_state.hand_id != first["hand_id"]


def test_redeal_after_board_reset_orders_finish_before_start():
    stream = Stream()
    first = stream.send(board=("Js", "7c", "4d"))
    state = stream.send(hero=("Qh", "Qs"), board=())
    assert state["hand_id"] != first["hand_id"]
    assert [e.type for e in boundaries(stream)] == ["HAND_STARTED", "HAND_FINISHED", "HAND_STARTED"]
    assert boundaries(stream)[1].state_after.board == ("Js", "7c", "4d")


def test_preflop_new_cards_require_independent_reset_evidence():
    stream = Stream()
    first = stream.send()
    assert stream.send(hero=("Qh", "Qs"))["hand_id"] == first["hand_id"]
    state = stream.send(hero=("Qh", "Qs"), pot="0", stack="13000")
    assert state["hand_id"] != first["hand_id"]


def test_fresh_capture_at_river_is_partial_and_stop_is_incomplete():
    stream = Stream()
    stream.send(hero=None, board=("Js", "7c", "4d", "2h", "Tc"))
    assert stream.engine.hands.active["partial_start"]
    stream.engine.hands.interrupt("capture_ended")
    record = stream.engine.hands.pending_records[-1]
    assert record["status"] == "incomplete" and record["finished_timestamp"] is None
    assert not any(e.type == "HAND_FINISHED" for e in boundaries(stream))


def test_many_hands_keep_memory_bounded():
    stream = Stream()
    for _ in range(150):
        stream.send(board=("Js", "7c", "4d"))
        stream.send(hero=(), board=(), count=8)
    assert stream.engine.hands.finished_count == 150
    assert len(stream.engine.hands.recent) == 20
    assert len(stream.engine.event_engine.events) == 40
    assert len(stream.engine.hands.pending_records) <= 2


def test_transactional_archive_persists_events_beyond_memory_and_recovers_open_hand(tmp_path):
    store = HandStore(path=tmp_path / "archive.sqlite3")
    store.initialize()
    stream = Stream()
    for i in range(55):
        before = stream.engine.event_engine.replay.sequence
        stream.send(pot=str(i), count=3)
        state = stream.engine.current_state
        record = {**stream.engine.hands.active, "state": asdict(state)}
        events = [e for e in stream.engine.event_engine.events if e.sequence > before]
        store.save([record], events, {"mode": "TRAINING"})
        store.save([record], events, {"mode": "TRAINING"})  # Idempotent retry.
    result = store.get(state.hand_id)
    assert len(result["events"]) > 40
    assert len(store.get(state.hand_id, limit=10)["events"]) == 10
    assert store.get(state.hand_id, limit=10)["has_more"]
    recovered = HandStore(path=tmp_path / "archive.sqlite3")
    recovered.initialize()
    assert recovered.get(state.hand_id)["hand"]["status"] == "incomplete"
    assert recovered.list_hands()["total"] == 1


def test_archive_transaction_rolls_back_on_event_failure(tmp_path):
    store = HandStore(path=tmp_path / "archive.sqlite3")
    store.initialize()
    stream = Stream()
    stream.send()
    record = {**stream.engine.hands.active, "state": asdict(stream.engine.current_state)}
    with pytest.raises(AttributeError):
        store.save([record], [object()], {})
    assert store.list_hands()["total"] == 0


def test_hand_api_handles_pagination_and_failures():
    with TestClient(create_app()) as client:
        assert client.get("/api/hands").json()["total"] == 0
        assert client.get("/api/hands/missing").status_code == 404
        assert client.get("/api/hands", params={"limit": 101}).status_code == 422
        assert client.get("/api/hands/missing", params={"after": -1}).status_code == 422
        client.app.state.hand_store.list_hands = lambda *args: 1 / 0
        assert client.get("/api/hands").status_code == 503


def test_storage_failure_stops_capture_and_retry_preserves_pending_hand():
    from app.capture_engine.engine import CaptureEngine
    from app.card_detector.models import CardObservation
    from app.pipeline_engine.processor import FrameProcessor
    from app.vision_engine import VisionObservation
    from test_card_state import reading
    from test_pipeline import SyntheticSource, wait_until

    class Vision:
        def observe(self, frame):
            return VisionObservation(frame.frame_id, frame.timestamp, 8, 8, True,
                CardObservation("ready", hero=reading(("As", "Jh")), board=reading(())))

    class Store:
        kind = "test"
        fail = True
        records = []

        def save_opponents(self, record):
            if self.fail:
                raise OSError("simulated storage failure")

        def save(self, records, events, context):
            if self.fail:
                raise OSError("simulated storage failure")
            self.records.extend(records)

    async def scenario():
        store = Store()
        engine = CaptureEngine(processor_factory=lambda: FrameProcessor(Vision()), hand_store=store)
        try:
            await engine.start(SyntheticSource(total=30))
            await wait_until(lambda: engine.state == "error")
            assert engine.storage_error
            assert len(engine.pending_events) <= 5
            assert engine.observation_state.hands.pending_records[-1]["status"] == "incomplete"
            store.fail = False
            await engine.start(SyntheticSource(total=1))
            await wait_until(lambda: engine.state == "ended")
            assert engine.storage_error is None
            assert store.records[-1]["status"] == "incomplete"
        finally:
            await engine.close()
    asyncio.run(scenario())
