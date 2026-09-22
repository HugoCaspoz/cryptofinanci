from dataclasses import dataclass
from typing import Literal

RANKS = "23456789TJQKA"
SUITS = {"s": "spades", "h": "hearts", "d": "diamonds", "c": "clubs"}


@dataclass(frozen=True)
class Card:
    rank: str
    suit: str
    confidence: float

    @property
    def code(self) -> str:
        return self.rank + next(key for key, value in SUITS.items() if value == self.suit)


@dataclass(frozen=True)
class RegionReading:
    status: Literal["known", "empty", "unknown"] = "unknown"
    cards: tuple[Card, ...] = ()


@dataclass(frozen=True)
class CardObservation:
    status: str = "not_configured"
    profile: str | None = None
    demo: bool = False
    layout_revision: str | None = None
    hero: RegionReading = RegionReading()
    board: RegionReading = RegionReading()
