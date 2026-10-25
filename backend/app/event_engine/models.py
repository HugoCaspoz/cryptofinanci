from enum import StrEnum
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.game_state_engine.models import GameState
from .state_validation import validate_state


class EventType(StrEnum):
    MANUAL_CORRECTION = "MANUAL_CORRECTION"
    ANALYSIS_RESUMED = "ANALYSIS_RESUMED"
    GAME_STATE_UPDATED = "GAME_STATE_UPDATED"
    HOLE_CARDS_DETECTED = "HOLE_CARDS_DETECTED"
    HERO_CARDS_CLEARED = "HERO_CARDS_CLEARED"
    BOARD_CARDS_CLEARED = "BOARD_CARDS_CLEARED"
    BOARD_CARDS_UPDATED = "BOARD_CARDS_UPDATED"
    FLOP_DEALT = "FLOP_DEALT"
    TURN_DEALT = "TURN_DEALT"
    RIVER_DEALT = "RIVER_DEALT"
    HAND_STARTED = "HAND_STARTED"
    HAND_FINISHED = "HAND_FINISHED"
    CAPTURE_ENDED = "CAPTURE_ENDED"
    PLAYER_FOLDED = "PLAYER_FOLDED"
    PLAYER_CHECKED = "PLAYER_CHECKED"
    PLAYER_CALLED = "PLAYER_CALLED"
    PLAYER_BET = "PLAYER_BET"
    PLAYER_RAISED = "PLAYER_RAISED"
    PLAYER_ALL_IN = "PLAYER_ALL_IN"
    HERO_DECISION_REQUIRED = "HERO_DECISION_REQUIRED"


AMOUNT_TYPES = {EventType.PLAYER_CALLED, EventType.PLAYER_BET,
                EventType.PLAYER_RAISED, EventType.PLAYER_ALL_IN}


class PokerEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: int = Field(default=1, ge=1, le=1)
    sequence: int = Field(ge=1)
    scope_id: str = Field(min_length=1)
    type: EventType
    frame_id: int = Field(ge=1)
    timestamp: float = Field(ge=0, allow_inf_nan=False)
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    hand_id: str | None = None
    player_id: str | None = None
    # Total visible wager on this street, never the increment paid by an action.
    amount: str | None = None
    unit: str | None = None
    action_evidence: tuple[str, ...] = ()
    correction_id: str | None = Field(default=None, min_length=36, max_length=36)
    decision_id: str | None = Field(default=None, min_length=64, max_length=64)
    state_after: GameState

    @model_validator(mode="after")
    def consistent(self):
        if (self.type == EventType.MANUAL_CORRECTION) != (self.correction_id is not None):
            raise ValueError("Solo las correcciones manuales llevan correction_id.")
        state = self.state_after
        validate_state(state)
        if state.scope_id != self.scope_id or state.hand_id != self.hand_id:
            raise ValueError("El evento y su estado deben pertenecer a la misma captura y mano.")
        players = {p.player_id: p for p in state.players}
        if self.player_id is not None and self.player_id not in players:
            raise ValueError("Jugador ajeno al estado.")
        if self.type.value.startswith("PLAYER_"):
            if self.player_id is None or self.hand_id is None or self.confidence is None:
                raise ValueError("Una acción necesita jugador, mano y confianza.")
        if self.type == EventType.HERO_DECISION_REQUIRED:
            if (self.decision_id is None or self.hand_id is None or self.player_id is None
                    or state.current_player != self.player_id or state.hand_status != "active"
                    or players[self.player_id].folded or players[self.player_id].all_in):
                raise ValueError("Una decisión necesita snapshot, mano activa y turno de Hero.")
        elif self.decision_id is not None:
            raise ValueError("Solo un punto de decisión lleva decision_id.")
        if self.type in {EventType.HAND_STARTED, EventType.HAND_FINISHED} and self.hand_id is None:
            raise ValueError("Un límite de mano necesita hand_id.")
        if self.type in AMOUNT_TYPES:
            if self.amount is None or not re.fullmatch(r"(?:0|[1-9]\d*)(?:\.\d{1,2})?", self.amount):
                raise ValueError("La apuesta total debe ser un decimal no negativo exacto.")
            player = players[self.player_id]
            if (player.current_bet, player.bet_unit) != (self.amount, self.unit):
                raise ValueError("El importe y la unidad deben coincidir con la apuesta resultante.")
        elif self.amount is not None or self.unit is not None:
            raise ValueError("Este evento no lleva importe.")
        if self.type == EventType.PLAYER_FOLDED and players[self.player_id].folded is not True:
            raise ValueError("El estado debe confirmar folded.")
        if self.type == EventType.PLAYER_ALL_IN and players[self.player_id].all_in is not True:
            raise ValueError("El estado debe confirmar all_in.")
        expected = {EventType.FLOP_DEALT: 3, EventType.TURN_DEALT: 4, EventType.RIVER_DEALT: 5}
        if self.type in expected and len(state.board) != expected[self.type]:
            raise ValueError("La calle no coincide con el board.")
        if self.type == EventType.HOLE_CARDS_DETECTED and len(state.hero_cards) != 2:
            raise ValueError("Se requieren dos cartas de Hero.")
        if self.type == EventType.HERO_CARDS_CLEARED and state.hero_cards:
            raise ValueError("Las cartas de Hero deben estar vacías.")
        if self.type == EventType.BOARD_CARDS_CLEARED and state.board:
            raise ValueError("El board debe estar vacío.")
        return self


class Checkpoint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    sequence: int = Field(ge=0)
    frame_id: int = Field(ge=0)
    timestamp: float = Field(ge=0, allow_inf_nan=False)
    state: GameState

    @model_validator(mode="after")
    def consistent(self):
        validate_state(self.state)
        return self


class EventBatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: int = Field(default=1, ge=1, le=1)
    scope_id: str
    requested_after: int = Field(ge=0)
    gap: bool
    last_sequence: int = Field(ge=0)
    checkpoint: Checkpoint
    events: tuple[PokerEvent, ...]

    @model_validator(mode="after")
    def consistent(self):
        if self.scope_id != self.checkpoint.state.scope_id:
            raise ValueError("El checkpoint pertenece a otra captura.")
        if not self.requested_after <= self.checkpoint.sequence <= self.last_sequence:
            raise ValueError("Cursor y checkpoint incompatibles.")
        if self.gap != (self.requested_after < self.checkpoint.sequence):
            raise ValueError("El indicador de hueco no coincide con el checkpoint.")
        return self
