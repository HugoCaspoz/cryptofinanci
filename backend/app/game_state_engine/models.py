"""Immutable, descriptive state. Unknown facts stay None, never guessed actions."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PlayerState:
    player_id: str
    seat: int
    nickname: str | None = None
    position: str | None = None
    observed_action: str | None = None
    stack: str | None = None
    stack_unit: str | None = None
    current_bet: str | None = None
    bet_unit: str | None = None
    folded: bool | None = None
    all_in: bool | None = None


@dataclass(frozen=True)
class GameState:
    # scope_id identifies this observation run, NOT a hand or durable player.
    scope_id: str
    players: tuple[PlayerState, ...]
    hand_id: str | None = None
    hand_status: str = "unidentified"
    street: str = "unknown"
    pot: str | None = None
    pot_unit: str | None = None
    board: tuple[str, ...] = ()
    hero_cards: tuple[str, ...] = ()
    current_player: str | None = None
    button_position: int | None = None
    small_blind: str | None = None
    big_blind: str | None = None
    blinds_unit: str | None = None


@dataclass(frozen=True)
class FieldEvidence:
    status: str
    confidence: float
    confirmed_frame_id: int | None
    confirmed_timestamp: float | None
    layout_revision: str | None
    source: str = "vision"
