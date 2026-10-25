from dataclasses import replace

import pytest

from app.config import FeedbackRelease, Mode
from app.hand_reconstructor.store import HandStore
from test_decisions import setup, freeze, event_for
from app.decision_engine.tracker import DecisionTracker
from test_feedback import client, seed, end_hand


def test_frame_is_atomic_immutable_and_survives_restart(tmp_path):
    s, request = setup()
    frozen = freeze(DecisionTracker(), s, request)
    event = event_for(s, frozen, request)
    store = HandStore(path=tmp_path / "frames.sqlite")
    store.initialize()
    jpeg = b"\xff\xd8original-frame\xff\xd9"
    store.save_decision(frozen.record(), event, jpeg)
    store.save_decision(frozen.record(), event, jpeg)
    assert store.get_decision_frame(frozen.id) == jpeg
    with pytest.raises(ValueError, match="reescribirse"):
        store.save_decision(frozen.record(), event, b"different")
    assert store.get_decision_frame(frozen.id) == jpeg
    reopened = HandStore(path=store.path)
    reopened.initialize()
    assert reopened.get_decision_frame(frozen.id) == jpeg
    item = reopened.list_decisions("hand", Mode.TRAINING)["items"][0]
    assert item["frame_available"] is True
    assert item["evaluation_status"] == "pending"
    assert reopened.list_decisions("hand", Mode.LIVE_REAL_MONEY)["items"] == []
    assert reopened.list_decisions("hand", Mode.TRAINING, after=item["event_sequence"])["items"] == []


def test_frame_endpoint_obeys_release_and_active_hand_revocation(client):
    data = seed(client, FeedbackRelease.HAND_FINISHED)
    store, frozen, *_ = data
    url = f"/api/decisions/{frozen.id}/frame"
    assert client.get(url).status_code == 403
    end_hand(data)
    response = client.get(url)
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store, private"
    store.save_decision(frozen.record(), store_event(store, frozen), b"jpeg")
    response = client.get(url)
    assert response.status_code == 200
    assert response.content == b"jpeg"
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "no-store, private"
    capture = client.app.state.capture
    capture.observation_state.current_state = replace(capture.observation_state.current_state,
        hand_id="next", hand_status="active")
    assert client.get(url).status_code == 403
    capture.observation_state.current_state = replace(capture.observation_state.current_state,
        hand_id=None, hand_status="unidentified")


def store_event(store, frozen):
    import json
    from app.event_engine.models import PokerEvent
    with store.connection() as db:
        row = db.execute(f"SELECT payload FROM observed_events WHERE scope_id={store.marker} AND sequence={store.marker}",
                         (frozen.record()["scope_id"], frozen.record()["event_sequence"])).fetchone()
    return PokerEvent(**json.loads(row[0]))
