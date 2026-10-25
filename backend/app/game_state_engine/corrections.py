"""Human labels for the frozen current observation; never a historical rewrite."""
from copy import deepcopy
from dataclasses import asdict, replace
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.card_detector.models import Card, SUITS
from app.action_engine.engine import ActionEngine
from app.event_engine.state_validation import validate_state
from .models import FieldEvidence


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManualAmount(StrictModel):
    value: str = Field(pattern=r"^(?:0|[1-9]\d{0,11})(?:\.\d{1,2})?$", max_length=15)
    unit: Literal["$", "€", "£", "BB"] | None = None


class PlayerCorrection(StrictModel):
    seat: int = Field(ge=1, le=6, strict=True)
    nickname: str | None = Field(default=None, min_length=1, max_length=32, pattern=r"^[\w.-]+$")
    stack: ManualAmount | None = None
    bet: ManualAmount | None = None
    action: Literal["NONE", "ACTIVE", "FOLD", "CHECK", "CALL", "BET", "RAISE", "ALL-IN"] | None = None

    @model_validator(mode="after")
    def has_change(self):
        if self.model_fields_set == {"seat"}:
            raise ValueError("Indica un dato que corregir del jugador.")
        return self


class CorrectionRequest(StrictModel):
    id: UUID
    expected_frame_id: int = Field(ge=1, strict=True)
    expected_revision: int = Field(ge=0, strict=True)
    reason: str = Field(min_length=1, max_length=240)
    hero_cards: tuple[str, ...] | None = Field(default=None, max_length=2)
    board: tuple[str, ...] | None = Field(default=None, max_length=5)
    players: tuple[PlayerCorrection, ...] = Field(default=(), max_length=6)

    @model_validator(mode="after")
    def valid_patch(self):
        if not self.reason.strip():
            raise ValueError("Indica el motivo de la corrección.")
        for name, sizes in [("hero_cards", {0, 2}), ("board", {0, 3, 4, 5})]:
            if name in self.model_fields_set:
                value = getattr(self, name)
                if value is None or len(value) not in sizes:
                    raise ValueError("Número de cartas inválido.")
        if not self.players and not self.model_fields_set & {"hero_cards", "board"}:
            raise ValueError("La corrección está vacía.")
        if len({p.seat for p in self.players}) != len(self.players):
            raise ValueError("No repitas asientos.")
        if sum(p.action == "ACTIVE" for p in self.players) > 1:
            raise ValueError("Solo puede haber un jugador activo.")
        return self


def corrected_game(game, body):
    trial = deepcopy(game)
    old = game.current_state
    values = {key: tuple(getattr(body, key)) for key in ("hero_cards", "board") if key in body.model_fields_set}
    players = list(old.players)
    current = old.current_player
    for patch in body.players:
        p = players[patch.seat - 1]
        changes = {}
        if "nickname" in patch.model_fields_set:
            changes["nickname"] = patch.nickname
        for name, target, unit in [("stack", "stack", "stack_unit"), ("bet", "current_bet", "bet_unit")]:
            if name in patch.model_fields_set:
                amount = getattr(patch, name)
                changes.update({target: amount.value if amount else None, unit: amount.unit if amount else None})
        if "action" in patch.model_fields_set:
            action = patch.action or "NONE"
            changes.update(observed_action=None if action == "NONE" else action,
                           folded=True if action == "FOLD" else None,
                           all_in=True if action == "ALL-IN" else None)
            if current == p.player_id:
                current = None
            if action == "ACTIVE":
                current = p.player_id
                players = [replace(other, observed_action=None) if other.observed_action == "ACTIVE" else other for other in players]
        players[patch.seat - 1] = replace(p, **changes)
    hero, board = values.get("hero_cards", old.hero_cards), values.get("board", old.board)
    street = {3: "flop", 4: "turn", 5: "river"}.get(len(board), "preflop" if hero else "unknown")
    new = validate_state(replace(old, **values, players=tuple(players), current_player=current, street=street))
    observation = trial.last_observation
    frame, timestamp = observation.frame_id, observation.source_timestamp
    trial.previous_state, trial.current_state = old, new
    for name in values:
        tracker = trial.cards.hero if name == "hero_cards" else trial.cards.board
        tracker.interrupt()
        tracker.commit(tuple(Card(code[0], SUITS[code[1]], 1.0) for code in getattr(new, name)))
        trial.evidence[name] = FieldEvidence("confirmed" if getattr(new, name) else "empty", 1, frame, timestamp,
                                            observation.cards.layout_revision, "manual")
    for patch in body.players:
        for key in patch.model_fields_set - {"seat", "action"}:
            ocr_key = f"players.{patch.seat - 1}.{key}"
            field = trial.ocr.fields[ocr_key]
            field.history.clear()
            amount = getattr(patch, key)
            field.value = amount.value if isinstance(amount, ManualAmount) else amount
            field.unit = amount.unit if isinstance(amount, ManualAmount) else None
            field.confidence, field.status = 1.0, "confirmed" if field.value is not None else "unknown"
            field.confirmed_frame_id, field.confirmed_timestamp = frame, timestamp
            target = ocr_key.replace(".bet", ".current_bet")
            trial.evidence[target] = FieldEvidence(field.status, 1, frame, timestamp, trial.ocr.revision, "manual")
    count = trial.actions.event_count
    trial.actions = ActionEngine()
    trial.actions.event_count = count
    trial.actions.hand, trial.actions.street = new.hand_id, new.street
    trial.actions.folded = {i for i, p in enumerate(new.players) if p.folded}
    trial.actions.all_in = {i for i, p in enumerate(new.players) if p.all_in}
    trial.actions.last_labels = [p.observed_action for p in new.players]
    if trial.hands.active:
        trial.hands.last_state = new
        trial.hands.last_hero = new.hero_cards
        trial.hands.blank_since, trial.hands.blank_samples = None, 0
        trial.hands.saw_board = bool(new.board)
        trial.hands.reset_until = trial.hands.zero_until = trial.hands.stack_until = -1
    trial.changes.compare(old, new, frame, timestamp)
    event = trial.event_engine.emit("MANUAL_CORRECTION", new, frame, timestamp,
                                    correction_id=str(body.id), action_evidence=("manual_label",))
    return trial, event
