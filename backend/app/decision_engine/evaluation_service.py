"""Durable evaluation queue, independent of the latest-only live strategy worker."""
import asyncio
import json
import logging

from app.config import Mode
from .models import DecisionSnapshot
from .evaluation import DecisionEvaluator

logger = logging.getLogger(__name__)


class EvaluationService:
    def __init__(self, mode, store, on_update, evaluator=None):
        self.mode, self.store, self.on_update = mode, store, on_update
        self.evaluator = evaluator or DecisionEvaluator()
        self.task = None
        self.revision = 0
        self.storage_error = None
        self.requested = False

    def kick(self):
        self.requested = True
        if self.store and (self.task is None or self.task.done()):
            self.task = asyncio.create_task(self._work())

    async def _work(self):
        try:
            while True:
                self.requested = False
                job = await asyncio.to_thread(self.store.next_evaluation, self.mode)
                if job is None:
                    if self.requested:
                        continue
                    break
                record, link = job
                identity = record.pop("id")
                frozen = DecisionSnapshot(identity, json.dumps(record, sort_keys=True, separators=(",", ":")))
                result = await asyncio.to_thread(self.evaluator.evaluate, frozen, link)
                await asyncio.to_thread(self.store.save_evaluation, identity, result)
                self.storage_error = None
                self.revision += 1
                self.on_update()
        except Exception:
            logger.exception("Decision evaluation failed; durable job retained")
            self.storage_error = "No se pudo completar la evaluación; queda pendiente para reintentar."
            self.on_update()

    def snapshot(self):
        return {"revision": self.revision if self.mode == Mode.TRAINING else 0,
                "storage_error": self.storage_error}

    async def close(self):
        self.kick()
        if self.task:
            await self.task
