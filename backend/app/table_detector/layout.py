from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Region(StrictModel):
    x: int = Field(ge=0, strict=True)
    y: int = Field(ge=0, strict=True)
    width: int = Field(gt=0, strict=True)
    height: int = Field(gt=0, strict=True)


class TableRegions(StrictModel):
    hero_cards: Region
    board: Region
    pot: Region
    dealer_button: Region
    blinds: Region


class PlayerRegions(StrictModel):
    nickname: Region
    stack: Region
    bet: Region
    action: Region


class TableLayout(StrictModel):
    version: Literal[1] = 1
    platform: str = Field(min_length=1, max_length=80, pattern=r"\S")
    width: int = Field(ge=320, le=3840, strict=True)
    height: int = Field(ge=240, le=2160, strict=True)
    calibrated: bool = Field(strict=True)
    card_profile: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    regions: TableRegions
    players: list[PlayerRegions] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def check_bounds(self):
        if self.width * self.height > 3840 * 2160:
            raise ValueError("La resolución supera el límite de la captura.")
        groups = [self.regions, *self.players]
        for group in groups:
            for name in type(group).model_fields:
                region = getattr(group, name)
                if region.x + region.width > self.width or region.y + region.height > self.height:
                    raise ValueError(f"La región {name} sale del frame de {self.width} × {self.height}.")
        return self
