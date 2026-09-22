from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.poker_engine.models import OpponentRange
from app.tournament_context.models import TournamentContext


class HandContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    hand_id: str = Field(min_length=1, max_length=128)
    button_seat: int = Field(ge=1, le=6)
    seats: tuple[int, ...] = Field(min_length=2, max_length=6)
    start_confirmed: Literal[True]
    range_priors: tuple[OpponentRange, ...] = Field(default=(), max_length=6)
    prior_strength: int = Field(default=30, ge=1, le=1000)
    tournament: TournamentContext | None = None

    @model_validator(mode="after")
    def valid_seats(self):
        if len(set(self.seats)) != len(self.seats) or any(s not in range(1, 7) for s in self.seats):
            raise ValueError("Asientos únicos entre 1 y 6.")
        if self.button_seat not in self.seats:
            raise ValueError("El botón debe participar en la mano.")
        prior_seats = [p.seat for p in self.range_priors]
        if len(set(prior_seats)) != len(prior_seats) or not set(prior_seats) <= set(self.seats):
            raise ValueError("Los rangos iniciales deben pertenecer a participantes distintos.")
        if self.tournament and len(self.seats) > (self.tournament.remaining_players or self.tournament.players):
            raise ValueError("Los asientos participantes superan los jugadores disponibles en el torneo.")
        return self
