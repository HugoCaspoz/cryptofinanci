import asyncio
from collections import deque
import logging

from app.config import Mode

logger = logging.getLogger(__name__)


class DecisionService:
    def __init__(self, mode, store, on_update):
        self.mode, self.store, self.on_update = mode, store, on_update
        self.lock = asyncio.Lock()
        self.pending = deque()
        self.task = None
        self.reset()

    def reset(self):
        if self.pending:
            raise ValueError("Guarda las decisiones pendientes antes de cambiar de captura.")
        self.recent = deque(maxlen=20)
        self.current = None
        self.current_key = None
        self.storage_error = None
        self.count = 0

    def enqueue(self, snapshot, event, jpeg=None):
        if self.pending:
            if self.pending[0][0].id == snapshot.id:
                return
            raise ValueError("Guarda la decisión pendiente antes de encolar otra.")
        self.current = snapshot
        self.current_key = snapshot.payload()["decision_key"]
        self.pending.append((snapshot, event, jpeg))
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._work())

    async def _work(self):
        try:
            await self.flush()
        except Exception:
            logger.exception("Decision snapshot archive failed")
        self.on_update()

    async def flush(self):
        async with self.lock:
            while self.pending:
                snapshot, event, jpeg = self.pending[0]
                try:
                    if self.store:
                        args = (snapshot.record(), event) if jpeg is None else (snapshot.record(), event, jpeg)
                        await asyncio.to_thread(self.store.save_decision, *args)
                except Exception:
                    self.storage_error = "No se pudo guardar la decisión; se conserva para reintentar."
                    raise
                self.pending.popleft()
                self.recent.append(snapshot.summary())
                self.count += 1
                self.storage_error = None

    def active(self, key):
        return self.current if self.current and self.current_key == key else None

    def snapshot(self, tracker):
        visible = self.mode == Mode.TRAINING
        return {"visibility": "training" if visible else "internal_only", "count": self.count,
                "storage_error": self.storage_error, "pending": len(self.pending), "reason": tracker.reason,
                "recent": list(self.recent) if visible and not self.storage_error else [],
                "active_id": self.current.id if visible and tracker.active and self.active(tracker.active)
                             and not self.pending and not self.storage_error else None}
