"""Latest-only combined strategy. Ready results are archived privately before publication."""
import asyncio
from dataclasses import asdict
from hashlib import sha256
import json
import logging
from time import perf_counter

from app.config import Mode
from .engine import StrategyEngine, StrategyRequest
from .models import StrategyConfig

logger = logging.getLogger(__name__)


def digest(pools):
    return sha256(json.dumps([[seat, [[list(c), w] for c, w in pool]] for seat, pool in pools]).encode()).hexdigest()


def archived_input(request):
    """Compact analysis input; decision_snapshot_id links the complete immutable ranges."""
    decision = request.decision
    return {"state": asdict(request.state), "poker_config": request.poker.model_dump(mode="json"),
            "decision_snapshot_id": request.snapshot_id,
            "config": request.config.model_dump(mode="json"), "event_sequence": request.sequence,
            "preflop_result_id": request.preflop["result"]["id"] if request.preflop else None,
            "decision": None if decision is None else {
                "event_sequence": decision.event_sequence, "frame_id": decision.frame_id,
                "timestamp": decision.timestamp, "street": decision.street, "board": list(decision.board),
                "button_seat": decision.button_seat, "live": list(decision.live), "pending": list(decision.pending),
                "high_bb": str(decision.high_bb), "increment_bb": str(decision.increment_bb),
                "bets_bb": [[s, str(b)] for s, b in decision.bets_bb], "counts": decision.counts,
                "preflop_aggressor": decision.preflop_aggressor, "flop_bet_seen": decision.flop_bet_seen,
                "prior_strength": decision.prior_strength, "range_version": decision.version,
                "tournament": decision.tournament.model_dump(mode="json") if decision.tournament else None,
                "neutral_pools_sha256": digest(decision.neutral_pools),
                "exploit_pools_sha256": digest(decision.exploit_pools)}}


class StrategyService:
    def __init__(self, mode, on_update, store=None, engine=None):
        self.mode, self.on_update, self.store = mode, on_update, store
        self.engine = engine or StrategyEngine()
        self.config = StrategyConfig()  # Sizing preferences survive captures; hand facts never do.
        self.task = None
        self.generation = 0
        self.pending_record = None
        self.storage_error = None
        self.archive_lock = asyncio.Lock()
        self.reset()

    def reset(self):
        self.generation += 1
        self.key = self.pending = self.result = None
        self.status = "inactive"

    def configure(self, config):
        self.config = config
        self.key = None

    async def flush(self):
        async with self.archive_lock:
            await self._flush_locked()

    async def _flush_locked(self):
        if self.pending_record is None:
            return
        try:
            if self.store is not None:
                await asyncio.to_thread(self.store.save_strategy, self.pending_record)
        except Exception:
            self.storage_error = "No se pudo guardar el resultado de estrategia; no se publica."
            raise
        self.pending_record = None
        self.storage_error = None

    def submit(self, state, poker, decision, preflop, frame_id, timestamp, sequence, running=True, decision_snapshot=None):
        if not running:
            if self.status != "inactive" or self.result is not None:
                self.reset()
            return
        if decision is not None and (frame_id is None or timestamp is None
                                     or decision.frame_id > frame_id or decision.timestamp > timestamp):
            decision = None  # Never evaluate with history newer than the frame.
        request = StrategyRequest(state, poker, self.config, decision, preflop, frame_id, timestamp, sequence)
        if decision_snapshot is not None:
            request = decision_snapshot.request()
        key = (request.state, request.poker, request.config, request.decision, request.preflop, request.snapshot_id)
        if key == self.key:
            return
        self.key = key
        self.generation += 1
        self.result = None
        self.status = "pending"
        self.pending = (self.generation, request)
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._work())

    def record(self, request, result):
        payload = archived_input(request) | {"mode": self.mode}
        identity = sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        return identity, {"id": identity, "hand_id": result["hand_id"], "scope_id": request.state.scope_id,
                          "frame_id": request.frame_id, "timestamp": request.timestamp,
                          "event_sequence": request.sequence, "mode": self.mode, "input": payload, "result": result}

    async def _work(self):
        while self.pending is not None:
            generation, request = self.pending
            self.pending = None
            started = perf_counter()
            try:
                result = await asyncio.to_thread(self.engine.analyze, request)
                result["analysis_latency_ms"] = round((perf_counter() - started) * 1000, 2)
            except Exception:
                logger.exception("Strategy analysis failed")
                result = None
            if generation != self.generation and request.snapshot_id is None:
                continue
            if result is not None and result["status"] == "ready":
                try:
                    await self.flush()  # An older unsaved decision goes first.
                    result["decision_snapshot_id"] = request.snapshot_id
                    result["id"], self.pending_record = self.record(request, result)
                    await self.flush()
                except Exception:
                    logger.exception("Strategy archive failed")
                    if generation == self.generation:
                        self.result, self.status = None, "storage_error"
                        self.on_update()
                    continue
            if generation == self.generation:
                self.result = result
                self.status = result["status"] if result else "error"
                self.on_update()

    def snapshot(self, running=True):
        visible = self.mode == Mode.TRAINING
        return {"status": self.status if running else "inactive",
                "visibility": "training" if visible else "internal_only",
                "config": self.config.model_dump(mode="json"), "storage_error": self.storage_error,
                "result": self.result if visible and running else None}

    async def close(self):
        self.generation += 1
        self.pending = None
        if self.task:
            await self.task
