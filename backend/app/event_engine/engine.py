from collections import deque

from .models import Checkpoint, PokerEvent
from .replay import EventReplay


class EventEngine:
    CAPACITY = 40

    def __init__(self, initial_state):
        self.checkpoint = Checkpoint(sequence=0, frame_id=0, timestamp=0, state=initial_state)
        self.replay = EventReplay(self.checkpoint)
        self.events = deque()
        self._frame_keys = {}

    def emit(self, event_type, state, frame_id, timestamp, **details):
        event = PokerEvent(sequence=self.replay.sequence + 1, scope_id=state.scope_id,
                           hand_id=state.hand_id, type=event_type, state_after=state,
                           frame_id=frame_id, timestamp=timestamp, **details)
        key = (event.type, event.player_id)
        if frame_id == self.replay.frame_id and key in self._frame_keys:
            old = self._frame_keys[key]
            if event.model_copy(update={"sequence": old.sequence}) == old:
                return old
            raise ValueError("Dos versiones del mismo evento en el mismo frame.")
        self.replay.apply(event)
        if not self.events or frame_id != self.events[-1].frame_id:
            self._frame_keys.clear()
        self._frame_keys[key] = event
        if len(self.events) == self.CAPACITY:
            removed = self.events.popleft()
            self.checkpoint = Checkpoint(sequence=removed.sequence, frame_id=removed.frame_id,
                                         timestamp=removed.timestamp, state=removed.state_after)
        self.events.append(event)
        return event

    def summary(self):
        return {"scope_id": self.checkpoint.state.scope_id, "event_count": self.replay.sequence,
                "first_sequence": self.events[0].sequence if self.events else None,
                "dropped_events": self.checkpoint.sequence, "capacity": self.CAPACITY,
                "events": [event.model_dump(mode="json", exclude={"state_after"}) for event in self.events]}

    def export(self, after=0):
        if after < 0 or after > self.replay.sequence:
            raise ValueError("Cursor fuera del historial disponible.")
        checkpoint = self.checkpoint
        gap = after < checkpoint.sequence
        if after > checkpoint.sequence:
            event = next(event for event in self.events if event.sequence == after)
            checkpoint = Checkpoint(sequence=event.sequence, frame_id=event.frame_id,
                                    timestamp=event.timestamp, state=event.state_after)
        return {"schema_version": 1, "scope_id": checkpoint.state.scope_id,
                "requested_after": after, "gap": gap, "last_sequence": self.replay.sequence,
                "checkpoint": checkpoint.model_dump(mode="json"),
                "events": [event.model_dump(mode="json") for event in self.events
                           if event.sequence > checkpoint.sequence]}
