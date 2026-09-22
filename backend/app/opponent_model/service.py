import asyncio

from app.config import Mode
from .engine import OpponentModel


class OpponentService:
    def __init__(self, scope_id, mode, store=None):
        self.mode, self.store = mode, store
        self.lock = asyncio.Lock()
        self.pending = None
        self.reset(scope_id)

    def reset(self, scope_id):
        if self.pending is not None:
            raise ValueError("Guarda las estadísticas pendientes antes de iniciar otra captura.")
        self.model = OpponentModel(scope_id)
        self.saved_revision = -1
        self.storage_error = None

    async def flush(self):
        if self.pending is None:
            return
        try:
            if self.store:
                await asyncio.to_thread(self.store.save_opponents, self.pending)
        except Exception:
            self.storage_error = "No se pudieron guardar las estadísticas de rivales."
            raise
        self.saved_revision = self.pending["revision"]
        self.pending = None
        self.storage_error = None

    async def save(self):
        await self.flush()
        if self.model.revision != self.saved_revision:
            self.pending = self.model.snapshot() | {"mode": self.mode}
            await self.flush()

    async def update(self, events, sequence, state, frame_id, timestamp):
        await self.flush()
        model = self.model
        if sequence == model.cursor:
            return
        selected = [e for e in events if e.sequence > model.cursor]
        if (state.scope_id != model.scope_id or sequence < model.cursor or not selected or selected[-1].sequence != sequence
                or any(e.scope_id != model.scope_id or frame_id is None or timestamp is None
                       or e.frame_id > frame_id or e.timestamp > timestamp for e in selected)):
            model.invalidate("Historial ajeno, incompleto o posterior al estado actual; estadísticas contextuales suspendidas.")
            await self.save()
            return
        for event in selected:
            model.consume(event)
        await self.save()

    def snapshot(self):
        data = self.model.snapshot() if not self.storage_error and self.pending is None else None
        return {"visibility": "training" if self.mode == Mode.TRAINING else "internal_only",
                "storage_error": self.storage_error,
                "observations": {k: data[k] for k in ("coverage", "event_sequence", "timestamp", "profiles")} if data else None,
                "analysis": data if self.mode == Mode.TRAINING else None}
