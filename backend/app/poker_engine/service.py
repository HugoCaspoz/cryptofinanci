"""Latest-only background analysis, with server-side publication policy."""
import asyncio
from dataclasses import replace
import logging
from time import perf_counter

from app.config import Mode
from .engine import PokerEngine
from .models import PokerConfig

logger = logging.getLogger(__name__)


def confirmed_state(state, evidence, timestamp=None):
    """Discard retained/unconfirmed readings before arithmetic (not from the UI)."""
    def known(key, empty=False):
        item = evidence.get(key)
        return (item is not None and item.status in ({"confirmed", "empty"} if empty else {"confirmed"})
                and (timestamp is None or item.confirmed_timestamp is not None
                     and 0 <= timestamp - item.confirmed_timestamp <= 2.5))
    players = tuple(replace(p,
        stack=p.stack if known(f"players.{i}.stack") else None,
        current_bet=p.current_bet if known(f"players.{i}.current_bet") else None)
        for i, p in enumerate(state.players))
    cards_known = known("hero_cards") and known("board", empty=True)
    return replace(state, players=players, pot=state.pot if known("pot") else None,
                   hero_cards=state.hero_cards if cards_known else (),
                   board=state.board if cards_known else (), street=state.street if cards_known else "unknown")


class PokerService:
    def __init__(self, mode, on_update, engine=None):
        self.mode, self.on_update = mode, on_update
        self.engine = engine or PokerEngine()
        self.task = None
        self.generation = 0
        self.reset()

    def reset(self):
        self.generation += 1
        self.config = PokerConfig()
        self.key = self.pending = self.result = None
        self.status = "unconfigured"

    def configure(self, config):
        self.config = config
        self.key = None

    def submit(self, state, evidence, frame_id=None, timestamp=None, adaptive=None):
        state = confirmed_state(state, evidence, timestamp)
        if self.config.range_source != "adaptive":
            adaptive = None
        elif adaptive is not None and (frame_id is None or timestamp is None
                or adaptive.frame_id > frame_id or adaptive.timestamp > timestamp):
            adaptive = None
        key = (state, self.config, adaptive)
        if key == self.key:
            return
        self.key = key
        self.generation += 1
        self.result = None
        self.pending = None
        if self.config.hero_seat is None or not self.config.opponents:
            self.status = "unconfigured"
            return
        self.status = "pending"
        self.pending = (self.generation, state, self.config, frame_id, timestamp, adaptive)
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._work())

    async def _work(self):
        while self.pending is not None:
            generation, state, config, frame_id, timestamp, adaptive = self.pending
            self.pending = None
            started = perf_counter()
            try:
                args = (state, config, adaptive) if config.range_source == "adaptive" else (state, config)
                result = await asyncio.to_thread(self.engine.analyze, *args)
                result.update(frame_id=frame_id, timestamp=timestamp,
                              analysis_latency_ms=round((perf_counter() - started) * 1000, 2))
                status = "ready"
            except Exception:
                logger.exception("Poker analysis failed")
                result, status = None, "error"
            if generation == self.generation:
                self.result, self.status = result, status
                self.on_update()

    def snapshot(self):
        visible = self.mode == Mode.TRAINING
        return {"config": self.config.model_dump(mode="json"),
                "visibility": "training" if visible else "internal_only",
                "status": self.status, "analysis": self.result if visible else None}

    async def close(self):
        self.generation += 1
        self.pending = None
        if self.task:
            await self.task
