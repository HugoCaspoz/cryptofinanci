"""Replay consumes only a checkpoint and ordered events, never observations."""
from .models import Checkpoint, EventBatch, PokerEvent


class EventReplay:
    def __init__(self, checkpoint: Checkpoint):
        self.state = checkpoint.state
        self.sequence = checkpoint.sequence
        self.frame_id, self.timestamp = checkpoint.frame_id, checkpoint.timestamp
        self.last_event = None

    def apply(self, event: PokerEvent):
        if event == self.last_event:
            return  # Exact retransmission of the last event is idempotent.
        if event.scope_id != self.state.scope_id:
            raise ValueError("No se pueden mezclar capturas.")
        if event.sequence != self.sequence + 1:
            raise ValueError("El historial contiene un hueco o un evento fuera de orden.")
        if event.frame_id < self.frame_id or event.timestamp < self.timestamp:
            raise ValueError("El tiempo y el frame no pueden retroceder.")
        self.state = event.state_after
        self.sequence, self.frame_id, self.timestamp = event.sequence, event.frame_id, event.timestamp
        self.last_event = event
        return self.state


def replay_batch(batch: EventBatch):
    replay = EventReplay(batch.checkpoint)
    for event in batch.events:
        replay.apply(event)
    if replay.sequence != batch.last_sequence:
        raise ValueError("La exportación está incompleta: faltan eventos al final.")
    return replay
