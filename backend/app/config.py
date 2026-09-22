"""Configuration is fixed at startup, never controlled by a browser message."""

import os
from dataclasses import dataclass
from enum import StrEnum


class Mode(StrEnum):
    LIVE_REAL_MONEY = "LIVE_REAL_MONEY"
    TRAINING = "TRAINING"


class FeedbackRelease(StrEnum):
    HAND_FINISHED = "HAND_FINISHED"
    SESSION_FINISHED = "SESSION_FINISHED"


@dataclass(frozen=True)
class Settings:
    mode: Mode
    frame_queue_size: int = 2
    card_template_dir: str | None = None
    tesseract_cmd: str = "tesseract"
    ocr_decimal_separator: str = "."
    database_url: str | None = None
    hand_db_path: str = "data/hands.sqlite3"
    feedback_release: FeedbackRelease = FeedbackRelease.SESSION_FINISHED

    def __post_init__(self):
        FeedbackRelease(self.feedback_release)
        if not 1 <= self.frame_queue_size <= 8:
            raise ValueError("FRAME_QUEUE_SIZE debe estar entre 1 y 8.")
        if self.ocr_decimal_separator not in {".", ","}:
            raise ValueError("OCR_DECIMAL_SEPARATOR debe ser punto o coma.")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            mode=Mode(os.getenv("APP_MODE", Mode.LIVE_REAL_MONEY)),
            frame_queue_size=int(os.getenv("FRAME_QUEUE_SIZE", "2")),
            card_template_dir=os.getenv("CARD_TEMPLATE_DIR") or None,
            tesseract_cmd=os.getenv("TESSERACT_CMD") or "tesseract",
            ocr_decimal_separator=os.getenv("OCR_DECIMAL_SEPARATOR", "."),
            database_url=os.getenv("DATABASE_URL") or None,
            hand_db_path=os.getenv("HAND_DB_PATH", "data/hands.sqlite3"),
            feedback_release=FeedbackRelease(os.getenv("FEEDBACK_RELEASE", FeedbackRelease.SESSION_FINISHED)),
        )
