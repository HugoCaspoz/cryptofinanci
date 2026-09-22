from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Money = Annotated[Decimal, Field(ge=0, le=1_000_000_000, max_digits=12, decimal_places=2)]
Rate = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class PrizeTier(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    first_place: int = Field(ge=1, le=1_000_000)
    last_place: int = Field(ge=1, le=1_000_000)
    amount: Money  # Per paid position, in the tournament currency; excludes bounties.

    @model_validator(mode="after")
    def valid_tier(self):
        if self.last_place < self.first_place or self.amount <= 0:
            raise ValueError("Cada tramo necesita puestos ordenados y un premio positivo por puesto.")
        return self


class TournamentPrior(BaseModel):
    """Explicit study hypothesis for this buy-in/currency/format, not measured population data."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    label: str = Field(min_length=1, max_length=80)
    strength: int = Field(default=10, ge=1, le=30)
    vpip: Rate = .28
    pfr: Rate = .18
    three_bet: Rate = .07

    @field_validator("label")
    @classmethod
    def clean_label(cls, value):
        if not value.strip():
            raise ValueError("Identifica el supuesto de población utilizado.")
        return value.strip()

    @model_validator(mode="after")
    def consistent_rates(self):
        if self.pfr > self.vpip:
            raise ValueError("El prior PFR no puede superar al VPIP.")
        # 3Bet has a different denominator; do not require 3Bet <= PFR.
        return self


class TournamentContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    buy_in: Money
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    tournament_type: Literal["mtt", "sit_and_go", "satellite", "bounty", "other"]
    starting_stack: int = Field(ge=1, le=1_000_000_000)
    players: int = Field(ge=2, le=1_000_000)
    remaining_players: int | None = Field(default=None, ge=2, le=1_000_000)
    prize_structure: tuple[PrizeTier, ...] | None = Field(default=None, min_length=1, max_length=1000)
    population_prior: TournamentPrior | None = None

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value):
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def valid_structure(self):
        if self.remaining_players is not None and self.remaining_players > self.players:
            raise ValueError("Los jugadores restantes no pueden superar los participantes totales.")
        previous_place, previous_amount = 0, None
        for tier in self.prize_structure or ():
            if tier.first_place != previous_place + 1 or tier.last_place > self.players:
                raise ValueError("Los premios deben empezar en el puesto 1, sin huecos ni solapamientos, dentro del total de participantes.")
            if previous_amount is not None and tier.amount > previous_amount:
                raise ValueError("Un puesto posterior no puede cobrar más que uno anterior.")
            previous_place, previous_amount = tier.last_place, tier.amount
        return self

    def summary(self):
        prizes = self.prize_structure
        return self.model_dump(mode="json") | {
            "paid_places": prizes[-1].last_place if prizes else None,
            "prize_pool": str(sum((p.amount * (p.last_place - p.first_place + 1) for p in prizes), Decimal(0))) if prizes else None,
            "prior_policy": "explicit-population-v1" if self.population_prior else "generic",
        }
