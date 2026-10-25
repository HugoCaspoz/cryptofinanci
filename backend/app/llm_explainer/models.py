from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class ExplanationStyle(StrEnum):
    SIMPLE = "simple"
    ADVANCED = "advanced"


class ExplanationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    style: ExplanationStyle = ExplanationStyle.SIMPLE


class ExplanationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_ids: list[str] = Field(min_length=1, max_length=32)
