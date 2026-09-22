from collections import deque
from dataclasses import asdict

from app.card_detector.models import CardObservation
from .card_tracker import CardTracker


class CardState:
    """Confirmed cards and a bounded observation log, not a full GameState/EventEngine."""
    def __init__(self):
        self.hero = CardTracker(unordered=True)
        self.board = CardTracker()
        self.observation = CardObservation()
        self.events = deque(maxlen=40)
        self.event_count = 0

    def accept(self, observation: CardObservation, frame_id: int, timestamp: float):
        self.observation = observation
        if observation.status != "ready":
            self.hero.interrupt()
            self.board.interrupt()
            return
        hero = self.hero.propose(observation.hero, timestamp)
        board = self.board.propose(observation.board, timestamp)
        next_hero = hero if hero is not None else self.hero.cards
        next_board = board if board is not None else self.board.cards
        if {card.code for card in next_hero} & {card.code for card in next_board}:
            self.hero.interrupt("conflict")
            self.board.interrupt("conflict")
            return
        for tracker, proposed, area in [(self.hero, hero, "hero"), (self.board, board, "board")]:
            if proposed is None:
                continue
            previous = tracker.cards
            if not tracker.commit(proposed):
                continue
            if not proposed:
                event_type = "HERO_CARDS_CLEARED" if area == "hero" else "BOARD_CARDS_CLEARED"
            elif area == "hero":
                event_type = "HOLE_CARDS_DETECTED"
            elif len(proposed) == 3 and not previous:
                event_type = "FLOP_DEALT"
            elif len(previous) == 3 and len(proposed) == 4 and tracker.identity(previous) == tracker.identity(proposed[:3]):
                event_type = "TURN_DEALT"
            elif len(previous) == 4 and len(proposed) == 5 and tracker.identity(previous) == tracker.identity(proposed[:4]):
                event_type = "RIVER_DEALT"
            else:
                event_type = "BOARD_CARDS_UPDATED"
            self.event_count += 1
            self.events.append({"id": self.event_count, "type": event_type, "frame_id": frame_id,
                                "timestamp": timestamp, "cards": [asdict(card) for card in proposed]})

    def snapshot(self):
        return {"detector_status": self.observation.status, "profile": self.observation.profile,
                "demo": self.observation.demo, "layout_revision": self.observation.layout_revision,
                "hero": self.hero.snapshot(), "board": self.board.snapshot(),
                "events": list(self.events), "event_count": self.event_count}
