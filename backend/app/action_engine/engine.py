from dataclasses import replace
from decimal import Decimal

from .vision import LABELS

EVENTS = {"FOLD": "PLAYER_FOLDED", "CHECK": "PLAYER_CHECKED", "CALL": "PLAYER_CALLED",
          "BET": "PLAYER_BET", "RAISE": "PLAYER_RAISED", "ALL-IN": "PLAYER_ALL_IN"}


class ActionEngine:
    """One observed turn at a time. Ambiguous or missing evidence never becomes an action."""
    def __init__(self):
        self.hand = self.street = None
        self.samples = [(None, 0, 0.0, 0.0)] * 6
        self.last_labels = [None] * 6
        self.last_time = None
        self.pending = None
        self.folded, self.all_in = set(), set()
        self.event_count = 0
        self.status = "waiting"
        self.reason = None

    @staticmethod
    def keys():
        return ["pot", *[f"players.{i}.{field}" for i in range(6) for field in ("stack", "current_bet")]]

    def fresh(self, state, evidence, timestamp, since=None):
        values = [state.pot, *[v for p in state.players for v in (p.stack, p.current_bet)]]
        units = [state.pot_unit, *[v for p in state.players for v in (p.stack_unit, p.bet_unit)]]
        if any(v is None for v in values) or len(set(units)) != 1:
            return False
        for key in self.keys():
            field = evidence.get(key)
            if (field is None or field.status != "confirmed" or field.confirmed_timestamp is None
                    or not 0 <= timestamp - field.confirmed_timestamp <= 2.5
                    or since is not None and field.confirmed_timestamp < since):
                return False
        return True

    def decorate(self, state, active=None):
        return replace(state, current_player=state.players[active].player_id if active is not None else None,
                       players=tuple(replace(p, folded=True if i in self.folded else None,
                                             all_in=True if i in self.all_in else None)
                                     for i, p in enumerate(state.players)))

    def update(self, state, observation, evidence, timestamp):
        events = []
        identity = (state.hand_id, state.street)
        if identity != (self.hand, self.street):
            if state.hand_id != self.hand:
                self.folded.clear()
                self.all_in.clear()
            self.hand, self.street = identity
            self.pending = None
            self.samples = [(None, 0, 0.0, 0.0)] * 6
            self.last_labels = [None] * 6
        self.status, self.reason = observation.status, None
        if state.hand_status != "active" or state.street == "unknown":
            self.pending = None
            self.status = "no_active_hand"
            return self.decorate(state), events
        if self.last_time is not None and timestamp - self.last_time > 2.5:
            self.pending = None
            self.samples = [(None, 0, 0.0, 0.0)] * 6
        self.last_time = timestamp
        visible = [None] * 6
        edges = []
        for i in range(6):
            reading = observation.readings[i] if observation.status == "ready" and len(observation.readings) == 6 else None
            label = reading.label if reading and reading.confidence >= .90 and reading.label in LABELS else None
            old, count, first, confidence = self.samples[i]
            if label is None:
                self.samples[i] = (None, 0, timestamp, 0.0)
                continue
            self.samples[i] = (label, min(count + 1, 3), first, min(confidence, reading.confidence)) if label == old else (label, 1, timestamp, reading.confidence)
            if self.samples[i][1] >= 3:
                visible[i] = label
                if self.last_labels[i] != label:
                    edges.append((i, label))
                    self.last_labels[i] = label
        active = [i for i, label in enumerate(visible) if label == "ACTIVE"]
        if len(active) > 1:
            self.pending = None
            self.reason = "multiple_active_players"
            return self.decorate(state), events
        if self.pending and timestamp > self.pending["expires"]:
            self.pending = None
            self.reason = "evidence_timeout"
        for i, label in edges:
            if label == "ACTIVE":
                self.pending = {"actor": i, "before": None, "expires": timestamp + 12,
                                "label": None, "confidence": self.samples[i][3]}
        pending = self.pending
        if pending:
            i = pending["actor"]
            if i in self.folded or i in self.all_in:
                self.pending = None
            else:
                if pending["before"] is None and visible[i] == "ACTIVE" and self.fresh(state, evidence, timestamp):
                    pending["before"] = state
                label = visible[i]
                if label in EVENTS and pending["label"] is None:
                    pending.update(label=label, since=self.samples[i][2], expires=timestamp + 6)
                if pending["label"]:
                    self.reason = "awaiting_consistent_evidence"
                    if label == pending["label"] and pending["before"] is not None and self.fresh(state, evidence, timestamp, pending["since"]):
                        accepted = self.classify(pending["before"], state, i, label)
                        if accepted:
                            if label == "FOLD":
                                self.folded.add(i)
                            if label == "ALL-IN":
                                self.all_in.add(i)
                            state = self.decorate(state)
                            confidence = min(pending["confidence"], self.samples[i][3],
                                             *[evidence[k].confidence for k in self.keys()])
                            details = {"player_id": state.players[i].player_id, "confidence": confidence,
                                       "action_evidence": ("visual_turn", "visual_label", "stack", "wager", "pot")}
                            if label not in {"FOLD", "CHECK"}:
                                details.update(amount=state.players[i].current_bet, unit=state.players[i].bet_unit)
                            events.append((EVENTS[label], details))
                            self.event_count += 1
                            self.pending = None
                            self.reason = None
        return self.decorate(state, active[0] if active else None), events

    @staticmethod
    def classify(before, after, actor, label):
        a, b = before.players[actor], after.players[actor]
        if before.pot_unit != after.pot_unit:
            return False
        # Coalesced updates cannot be safely ordered or assigned to this player.
        if any((p.stack, p.current_bet) != (q.stack, q.current_bet)
               for i, (p, q) in enumerate(zip(before.players, after.players)) if i != actor):
            return False
        paid = Decimal(a.stack) - Decimal(b.stack)
        wager = Decimal(b.current_bet) - Decimal(a.current_bet)
        pot = Decimal(after.pot) - Decimal(before.pot)
        highest = max(Decimal(p.current_bet) for p in before.players)
        target = Decimal(b.current_bet)
        if label in {"FOLD", "CHECK"}:
            return paid == wager == pot == 0 and (label == "FOLD" or target == highest)
        if not paid == wager == pot or paid <= 0:
            return False
        return {"BET": highest == 0, "CALL": target == highest,
                "RAISE": highest > 0 and target > highest,
                "ALL-IN": Decimal(b.stack) == 0}.get(label, False)

    def snapshot(self):
        return {"status": self.status, "event_count": self.event_count, "reason": self.reason,
                "pending_seat": self.pending["actor"] + 1 if self.pending else None,
                "profile": "Zeros demo", "capacity": 1}
