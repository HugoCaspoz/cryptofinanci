"""Per-hand anchored history and private durable strategy results."""
import asyncio
from dataclasses import asdict, replace
from decimal import Decimal
from hashlib import sha256
import json

from app.config import Mode
from app.poker_engine.service import confirmed_state
from .models import PriorAction, StrategyResult
from .preflop import PreflopEngine

ACTION_TYPES = {"PLAYER_FOLDED": "FOLD", "PLAYER_CHECKED": "CHECK", "PLAYER_CALLED": "CALL",
                "PLAYER_RAISED": "RAISE", "PLAYER_BET": "RAISE", "PLAYER_ALL_IN": "ALL_IN"}


class PreflopService:
    def __init__(self, mode, store=None):
        self.mode, self.store = mode, store
        self.lock = asyncio.Lock()
        self.engine = PreflopEngine()
        self.pending_record = None
        self.reset()

    def reset(self):
        self.config = self.key = self.result = None
        self.actions = ()
        self.cursor = 0
        self.history_error = None
        self.status = "unconfigured"

    def configure(self, config, sequence):
        self.config, self.actions, self.cursor = config, config.prior_actions, sequence
        self.key = self.result = self.history_error = None

    def invalidate(self):
        self.result = self.key = None
        self.status = "storage_error" if self.pending_record is not None else "inactive"

    async def flush(self):
        if self.pending_record is not None:
            if self.store is not None:
                await asyncio.to_thread(self.store.save_preflop, self.pending_record)
            self.pending_record = None

    def advance(self, events, sequence, state, frame_id, timestamp):
        if sequence == self.cursor:
            return
        selected = [e for e in events if e.sequence > self.cursor]
        if (sequence < self.cursor or not selected or selected[0].sequence != self.cursor + 1
                or selected[-1].sequence != sequence
                or any(b.sequence != a.sequence + 1 for a, b in zip(selected, selected[1:]))):
            self.history_error = "Faltan eventos desde la confirmación del historial; vuelve a confirmar el contexto."
        for event in selected:
            if (event.scope_id != state.scope_id or timestamp is None or frame_id is None
                    or event.timestamp > timestamp or event.frame_id > frame_id):
                self.history_error = "Evento de otra captura o posterior al estado que se está evaluando."
                break
            if event.hand_id != self.config.hand_id or event.state_after.street != "preflop":
                continue
            if event.type not in ACTION_TYPES:
                continue
            if event.timestamp < 0 or len(self.actions) >= 32:
                self.history_error = "Historial preflop fuera de los límites de esta fase."
                break
            actor = next((p for p in event.state_after.players if p.player_id == event.player_id), None)
            try:
                if actor is None or actor.seat not in self.config.seats:
                    raise ValueError("Acción de un asiento no configurado.")
                total = None
                if event.amount is not None:
                    big = Decimal(event.state_after.big_blind or "0")
                    if big <= 0 or event.unit != event.state_after.blinds_unit:
                        raise ValueError("No se pudo convertir una acción observada a BB.")
                    total = Decimal(event.amount) / big
                self.actions += (PriorAction(seat=actor.seat, action=ACTION_TYPES[event.type], total_bb=total),)
            except ValueError as exc:
                self.history_error = str(exc)
        self.cursor = sequence

    @staticmethod
    def clean_state(state, evidence, timestamp):
        clean = confirmed_state(state, evidence, timestamp)
        for name in ("small_blind", "big_blind"):
            item = evidence.get(name)
            if (item is None or item.status != "confirmed" or item.confirmed_timestamp is None
                    or timestamp is None or not 0 <= timestamp - item.confirmed_timestamp <= 2.5):
                clean = replace(clean, **{name: None})
        return clean

    async def update(self, state, evidence, events, sequence, frame_id, timestamp):
        try:
            await self.flush()
        except Exception:
            self.result, self.status = None, "storage_error"
            raise
        if self.config is None:
            return
        if state.hand_id != self.config.hand_id:
            self.reset()  # Never carry button, antes or asserted history into a new hand.
            return
        self.advance(events, sequence, state, frame_id, timestamp)
        clean = self.clean_state(state, evidence, timestamp)
        key = (clean, self.config, self.actions, self.history_error)
        if key == self.key:
            return
        self.result = None
        result = (StrategyResult(status="unavailable", reason=self.history_error) if self.history_error
                  else self.engine.analyze(clean, self.config, self.actions))
        payload = {"state": asdict(clean), "config": self.config.model_dump(mode="json"),
                   "actions": [a.model_dump(mode="json") for a in self.actions], "mode": self.mode}
        identity = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        self.pending_record = ({"id": identity, "hand_id": state.hand_id, "scope_id": state.scope_id,
                                "frame_id": frame_id, "timestamp": timestamp, "event_sequence": sequence,
                                "input": payload, "result": result.model_dump(mode="json")}
                               if result.status == "ready" else None)
        try:
            await self.flush()
        except Exception:
            self.status = "storage_error"
            raise
        self.key, self.status = key, result.status
        self.result = {**result.model_dump(mode="json"), "id": identity, "hand_id": state.hand_id,
                       "frame_id": frame_id, "timestamp": timestamp}

    def fresh(self, state, evidence, timestamp, sequence):
        """Last result only while it still describes exactly this state and event cursor."""
        if (self.result is None or self.key is None or sequence != self.cursor
                or self.key[0] != self.clean_state(state, evidence, timestamp)):
            return None
        return self.result

    def snapshot(self, state=None, evidence=None, timestamp=None, sequence=None, running=True):
        result, status = self.result, self.status
        if not running:
            result = None
        elif state is not None and result is not None and self.fresh(state, evidence, timestamp, sequence) is None:
            result, status = None, "pending"
        return {"status": status,
                "visibility": "training" if self.mode == Mode.TRAINING else "internal_only",
                "config": self.config.model_dump(mode="json") if self.config else None,
                "result": result if self.mode == Mode.TRAINING else None}
