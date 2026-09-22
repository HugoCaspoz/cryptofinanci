from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.poker_engine.ranges import expand_range

Position = Literal["UTG", "HJ", "CO", "BTN", "SB", "BB", "BTN/SB"]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PriorAction(FrozenModel):
    seat: int = Field(ge=1, le=6)
    action: Literal["FOLD", "CHECK", "CALL", "RAISE", "ALL_IN"]
    # Total wager on this street, in BB, not the amount added.
    total_bb: Decimal | None = Field(default=None, ge=0, le=100000, allow_inf_nan=False)

    @model_validator(mode="after")
    def amount_required(self):
        if (self.action in {"CALL", "RAISE", "ALL_IN"}) != (self.total_bb is not None):
            raise ValueError("CALL/RAISE/ALL_IN requieren total_bb; FOLD/CHECK no llevan importe.")
        return self


class PreflopRule(FrozenModel):
    id: str = Field(min_length=1, max_length=60)
    scenario: Literal["unopened", "limped", "single_raise"]
    positions: tuple[Position, ...] = Field(min_length=1, max_length=7)
    opener_positions: tuple[Position, ...] = ()
    min_players: int = Field(default=2, ge=2, le=6)
    max_players: int = Field(default=6, ge=2, le=6)
    min_stack_bb: float = Field(default=20, ge=0, le=100000, allow_inf_nan=False)
    max_stack_bb: float = Field(default=200, gt=0, le=100000, allow_inf_nan=False)
    min_raise_bb: float = Field(default=1, ge=0, le=100000, allow_inf_nan=False)
    max_raise_bb: float = Field(default=4, gt=0, le=100000, allow_inf_nan=False)
    min_ante_bb: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    max_ante_bb: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    raise_range: str = Field(default="", max_length=4096)
    call_range: str = Field(default="", max_length=4096)
    open_to_bb: float = Field(default=2.5, ge=2, le=20, allow_inf_nan=False)
    raise_multiplier: float = Field(default=3, ge=2, le=10, allow_inf_nan=False)
    extra_per_caller_bb: float = Field(default=1, ge=0, le=10, allow_inf_nan=False)

    @field_validator("raise_range", "call_range")
    @classmethod
    def deterministic_range(cls, value):
        if value:
            entries = expand_range(value)
            if any(weight != 1 for _, weight in entries):
                raise ValueError("Las tablas preflop son deterministas: no admiten pesos ni frecuencias mixtas.")
        return value

    @model_validator(mode="after")
    def consistent_rule(self):
        for low, high in [(self.min_players, self.max_players), (self.min_stack_bb, self.max_stack_bb),
                          (self.min_raise_bb, self.max_raise_bb), (self.min_ante_bb, self.max_ante_bb)]:
            if low > high:
                raise ValueError("Los límites mínimos no pueden superar los máximos.")
        raising = {cards for cards, _ in expand_range(self.raise_range)} if self.raise_range else set()
        calling = {cards for cards, _ in expand_range(self.call_range)} if self.call_range else set()
        if raising & calling:
            raise ValueError("Los rangos de raise y call no pueden solaparse.")
        return self


class PreflopConfig(FrozenModel):
    hand_id: str = Field(min_length=1, max_length=64)
    hero_seat: int = Field(ge=1, le=6)
    button_seat: int = Field(ge=1, le=6)
    # Seats are numbered clockwise, as explicitly confirmed by the operator.
    seats: tuple[int, ...] = Field(min_length=2, max_length=6)
    ante_total_bb: Decimal = Field(ge=0, le=100, allow_inf_nan=False)
    pot_includes_bets: bool
    history_confirmed: Literal[True]
    prior_actions: tuple[PriorAction, ...] = Field(default=(), max_length=32)
    rules: tuple[PreflopRule, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def valid_context(self):
        if (len(set(self.seats)) != len(self.seats) or any(s not in range(1, 7) for s in self.seats)
                or self.hero_seat not in self.seats or self.button_seat not in self.seats):
            raise ValueError("Confirma asientos únicos entre 1 y 6, incluyendo Hero y botón.")
        if any(a.seat not in self.seats for a in self.prior_actions):
            raise ValueError("El historial incluye un asiento que no participó en la mano.")
        if len({r.id for r in self.rules}) != len(self.rules):
            raise ValueError("Cada regla debe tener un identificador único.")
        return self


class StrategyResult(FrozenModel):
    status: Literal["ready", "unavailable"]
    reason: str
    action: Literal["FOLD", "CHECK", "CALL", "RAISE", "ALL_IN"] | None = None
    sizing_bb: float | None = None
    additional_bb: float | None = None
    sizing_kind: str = "total_street"
    confidence: None = None  # Strategy strength is not calibrated against a solver.
    basis: str = "configured_baseline_not_gto"
    rule_id: str | None = None
    context: dict = Field(default_factory=dict)


class StrategyConfig(FrozenModel):
    # Bet sizes as fractions of the current total pot; raises target a multiple of the bet faced.
    bet_sizes: tuple[float, ...] = Field(default=(0.33, 0.75), min_length=1, max_length=4)
    raise_multiplier: float = Field(default=3, ge=2, le=6, allow_inf_nan=False)
    # Logit spread: EV differences are divided by this fraction of the pot.
    temperature: float = Field(default=0.05, ge=0.01, le=0.5, allow_inf_nan=False)
    tournament_adjustment: bool = True

    @field_validator("bet_sizes")
    @classmethod
    def valid_sizes(cls, value):
        if any(not 0.1 <= size <= 3 for size in value) or len(set(value)) != len(value):
            raise ValueError("Tamaños de apuesta distintos, entre 0.1 y 3 veces el bote.")
        return tuple(sorted(value))
