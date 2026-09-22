"""Frozen view of one hand for the strategy engine: known history only, never later events."""
from dataclasses import dataclass
from decimal import Decimal

from app.tournament_context.models import TournamentContext
from .adaptive import VERSION


@dataclass(frozen=True)
class StrategyInput:
    scope_id: str
    hand_id: str
    street: str
    board: tuple[str, ...]
    event_sequence: int
    frame_id: int
    timestamp: float
    button_seat: int
    seats: tuple[int, ...]
    live: tuple[int, ...]
    pending: tuple[int, ...]
    high_bb: Decimal
    increment_bb: Decimal
    bets_bb: tuple  # (seat, total street wager in BB)
    preflop_aggressor: int | None
    flop_bet_seen: bool
    exploit_pools: tuple  # (seat, pool) with observed statistics and optional tournament prior
    neutral_pools: tuple  # (seat, pool) with the same actions under generic priors only
    counts: tuple  # (seat, ((statistic, hits, opportunities), ...)) frozen when the hand started
    prior_strength: int
    tournament: TournamentContext | None
    version: str = VERSION


def strategy_input(model, state):
    h = model.hand
    if model.adaptive_input(state) is None:
        return None
    ranges, betting = h["ranges"], h["betting"]
    live = tuple(s for s in h["context"].seats if s not in betting.folded)
    return StrategyInput(model.scope_id, h["id"], h["street"], ranges.board, model.cursor, model.frame_id,
        model.timestamp, h["context"].button_seat, tuple(h["context"].seats), live, tuple(betting.pending),
        Decimal(betting.high), Decimal(betting.increment),
        tuple((s, Decimal(betting.bets.get(s, 0))) for s in h["context"].seats),
        h["aggressor"], h["flop_bet_seen"],
        tuple((s, ranges.pools[s]) for s in live), tuple((s, ranges.neutral[s]) for s in live),
        tuple((s, tuple((k, v[0], v[1]) for k, v in sorted(ranges.stats[s].items()))) for s in live),
        h["context"].prior_strength, h["context"].tournament)
