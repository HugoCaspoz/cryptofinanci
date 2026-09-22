"""Small temporal filter for one card region, independent of hand reconstruction."""
from dataclasses import asdict, replace

from app.card_detector.models import Card, RegionReading


class CardTracker:
    REQUIRED_READINGS = 3
    MAX_GAP_SECONDS = 2.5

    def __init__(self, unordered=False):
        self.unordered = unordered
        self.cards: tuple[Card, ...] = ()
        self.candidate: tuple[Card, ...] | None = None
        self.count = 0
        self.status = "waiting"
        self.last_timestamp: float | None = None

    @staticmethod
    def identity(cards):
        return tuple(card.code for card in cards)

    def interrupt(self, status="unknown"):
        self.candidate, self.count, self.status = None, 0, status

    def propose(self, reading: RegionReading, timestamp: float):
        if self.last_timestamp is not None and not 0 < timestamp - self.last_timestamp <= self.MAX_GAP_SECONDS:
            self.interrupt()
        self.last_timestamp = timestamp
        if reading.status == "unknown":
            self.interrupt()
            return None
        cards = tuple(sorted(reading.cards, key=lambda card: card.code)) if self.unordered else reading.cards
        if self.candidate is not None and self.identity(cards) == self.identity(self.candidate):
            self.count = min(self.REQUIRED_READINGS, self.count + 1)
            self.candidate = tuple(replace(card, confidence=min(card.confidence, old.confidence))
                                   for card, old in zip(cards, self.candidate))
        else:
            self.candidate, self.count = cards, 1
        already_confirmed = self.identity(cards) == self.identity(self.cards) and self.status in {"confirmed", "empty"}
        self.status = "confirmed" if already_confirmed and cards else "empty" if already_confirmed else "pending"
        if self.count == self.REQUIRED_READINGS:
            return self.candidate
        return None

    def commit(self, cards):
        changed = self.identity(cards) != self.identity(self.cards)
        self.cards = cards
        self.status = "confirmed" if cards else "empty"
        return changed

    def snapshot(self):
        return {"cards": [asdict(card) for card in self.cards], "status": self.status,
                "confirmations": self.count, "required_confirmations": self.REQUIRED_READINGS}
