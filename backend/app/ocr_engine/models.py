from dataclasses import dataclass


@dataclass(frozen=True)
class TextReading:
    key: str
    kind: str
    text: str = ""
    confidence: float = 0.0
    value: str | None = None
    unit: str | None = None


@dataclass(frozen=True)
class OcrObservation:
    status: str = "not_configured"
    sampled: bool = False
    readings: tuple[TextReading, ...] = ()
    layout_revision: str | None = None
    decimal_separator: str = "."
