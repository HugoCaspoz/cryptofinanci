from dataclasses import asdict, replace
from math import isfinite
from uuid import uuid4

from app.vision_engine import VisionObservation
from .card_state import CardState
from .ocr_state import OcrState
from .models import GameState, PlayerState
from .projection import collect_evidence, project
from .changes import StateChanges
from app.event_engine.engine import EventEngine
from app.event_engine.bridge import publish_observed
from app.hand_reconstructor.lifecycle import HandLifecycle
from app.action_engine.engine import ActionEngine
from app.decision_engine.tracker import DecisionTracker


class GameStateEngine:
    """Ordered projection of known facts, called on the pipeline's event loop."""

    def __init__(self):
        self.last_observation: VisionObservation | None = None
        self.observations_seen = 0
        self.cards = CardState()
        self.ocr = OcrState()
        scope_id = uuid4().hex
        self.current_state = GameState(scope_id, tuple(
            PlayerState(f"{scope_id}:seat:{i + 1}", i + 1) for i in range(6)))
        self.previous_state = self.current_state
        self.evidence = {}
        self.changes = StateChanges()
        self.event_engine = EventEngine(self.current_state)
        self.hands = HandLifecycle()
        self.actions = ActionEngine()
        self.decisions = DecisionTracker()

    def accept(self, observation: VisionObservation) -> None:
        if self.last_observation and observation.frame_id <= self.last_observation.frame_id:
            raise ValueError("Las observaciones deben llegar en orden, sin duplicados.")
        if (not isfinite(observation.source_timestamp) or observation.source_timestamp < 0
                or self.last_observation and observation.source_timestamp <= self.last_observation.source_timestamp):
            raise ValueError("El tiempo de fuente debe ser finito y avanzar.")
        self.last_observation = observation
        # Outbox for this observation; CaptureEngine persists before accepting another.
        self.hands.pending_records.clear()
        self.observations_seen += 1
        last_card_event = self.cards.event_count
        self.cards.accept(observation.cards, observation.frame_id, observation.source_timestamp)
        self.ocr.accept(observation.ocr, observation.frame_id, observation.source_timestamp)
        self.previous_state = self.current_state
        self.current_state = project(self.previous_state, self.cards, self.ocr)
        self.evidence = collect_evidence(self.cards, self.ocr, self.evidence,
                                        observation.frame_id, observation.source_timestamp)
        self.current_state, boundaries = self.hands.update(self.previous_state, self.current_state,
            self.evidence, observation.frame_id, observation.source_timestamp)
        if any(kind == "HAND_STARTED" for kind, _ in boundaries) and self.hands.started_count > 1:
            self.ocr.reset_hand_values()
            refreshed = project(self.current_state, self.cards, self.ocr)
            self.current_state = replace(refreshed, hand_id=self.current_state.hand_id, hand_status="active")
            self.hands.last_state = self.current_state
            boundaries = [(kind, self.current_state if kind == "HAND_STARTED" else state) for kind, state in boundaries]
            self.evidence = collect_evidence(self.cards, self.ocr, self.evidence,
                observation.frame_id, observation.source_timestamp)
            self.hands.pending_records[-1]["state"] = asdict(self.current_state)
        for kind, state in boundaries:
            self.event_engine.emit(kind, state, observation.frame_id, observation.source_timestamp)
        action_input = self.current_state
        self.current_state, actions = self.actions.update(action_input, observation.actions,
            self.evidence, observation.source_timestamp)
        if self.hands.active and self.hands.last_state is action_input:
            self.hands.last_state = self.current_state
        for kind, details in actions:
            self.event_engine.emit(kind, self.current_state, observation.frame_id, observation.source_timestamp, **details)
        self.changes.compare(self.previous_state, self.current_state,
                             observation.frame_id, observation.source_timestamp)
        publish_observed(self.event_engine, self.previous_state, self.current_state,
                         [event for event in self.cards.events if event["id"] > last_card_event],
                         self.evidence, observation.frame_id, observation.source_timestamp)

    def snapshot(self) -> dict:
        return {
            "recognition_available": self.last_observation.recognition_available if self.last_observation else False,
            "observations_seen": self.observations_seen,
            "last_frame_id": self.last_observation.frame_id if self.last_observation else None,
            "cards": self.cards.snapshot(),
            "ocr": self.ocr.snapshot(),
            "event_stream": self.event_engine.summary(),
            "hands": self.hands.snapshot(),
            "actions": self.actions.snapshot(),
            "game_state": {
                **asdict(self.current_state), "revision": self.changes.revision,
                "frame_id": self.last_observation.frame_id if self.last_observation else None,
                "timestamp": self.last_observation.source_timestamp if self.last_observation else None,
                "evidence": {key: asdict(value) for key, value in self.evidence.items()},
                "events": self.changes.snapshot(),
            },
        }
