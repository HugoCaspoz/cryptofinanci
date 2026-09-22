"""Bounded value deltas, not yet a stream that reconstructs poker actions."""
from collections import deque
from copy import deepcopy
from dataclasses import asdict


def flatten(state):
    result = asdict(state)
    players = result.pop("players")
    for index, player in enumerate(players):
        result.update({f"players.{index}.{key}": value for key, value in player.items()})
    return result


class StateChanges:
    def __init__(self):
        self.revision = 0
        self.events = deque(maxlen=40)

    def compare(self, previous, current, frame_id, timestamp):
        before, after = flatten(previous), flatten(current)
        changes = [{"field": key, "previous": before[key], "current": value}
                   for key, value in after.items() if before[key] != value]
        if not changes:
            return
        self.revision += 1
        self.events.append({"id": self.revision, "type": "GAME_STATE_UPDATED",
                            "revision": self.revision, "frame_id": frame_id,
                            "timestamp": timestamp, "changes": changes})

    def snapshot(self):
        return deepcopy(list(self.events))
