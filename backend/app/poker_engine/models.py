from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ranges import expand_range


class OpponentRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    seat: int = Field(ge=1, le=6)
    range: str = Field(default="random", min_length=1, max_length=4096)

    @field_validator("range")
    @classmethod
    def valid_range(cls, value):
        expand_range(value)
        return value


class PostflopContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    hand_id: str = Field(min_length=1, max_length=128)
    hero_range: str | None = Field(default=None, min_length=1, max_length=4096)
    button_seat: int | None = Field(default=None, ge=1, le=6)

    @field_validator("hero_range")
    @classmethod
    def valid_range(cls, value):
        if value is not None:
            expand_range(value)
        return value


class PokerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    hero_seat: int | None = Field(default=None, ge=1, le=6)
    range_source: Literal["manual", "adaptive"] = "manual"
    opponents: tuple[OpponentRange, ...] = Field(default=(), max_length=5)
    # None means the displayed pot convention has not been calibrated.
    pot_includes_bets: bool | None = None
    samples: int = Field(default=1000, ge=100, le=5000)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    postflop_context: PostflopContext | None = None

    @model_validator(mode="after")
    def distinct_seats(self):
        seats = [p.seat for p in self.opponents]
        if len(set(seats)) != len(seats) or self.hero_seat in seats:
            raise ValueError("Hero y rivales deben ocupar asientos distintos.")
        if self.opponents and self.hero_seat is None:
            raise ValueError("Asigna el asiento de Hero.")
        return self
