"""Optional check against a dedicated database, never the application's database."""
import os
from dataclasses import asdict
import pytest
from app.hand_reconstructor.store import HandStore
from test_game_state import Stream


@pytest.mark.skipif(not os.getenv("HAND_TEST_POSTGRES"), reason="Requiere base PostgreSQL exclusiva de pruebas")
def test_postgres_archive_commit_pagination_and_rollback():
    store = HandStore(database_url=os.environ["HAND_TEST_POSTGRES"])
    store.initialize()
    stream = Stream()
    stream.send()
    record = {**stream.engine.hands.active, "state": asdict(stream.engine.current_state)}
    events = list(stream.engine.event_engine.events)
    store.save([record], events, {"mode": "TRAINING"})
    store.save([record], events, {"mode": "TRAINING"})
    assert len(store.get(record["hand_id"])["events"]) == len(events)
    assert store.list_hands(scope_id=record["scope_id"])["total"] == 1
    broken = {**record, "hand_id": "rollback-" + record["hand_id"]}
    with pytest.raises(AttributeError):
        store.save([broken], [object()], {})
    assert store.get(broken["hand_id"]) is None
