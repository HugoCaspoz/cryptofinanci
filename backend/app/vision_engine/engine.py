from dataclasses import dataclass
from pathlib import Path
import logging
import cv2

from pydantic import ValidationError

from app.capture_engine.source import Frame
from app.card_detector.models import CardObservation
from app.card_detector.detector import CardDetector
from app.card_detector.templates import TemplateDeck
from app.card_detector.profiles import CardProfiles
import os
from app.table_detector.store import LayoutStore
from app.ocr_engine.engine import OcrEngine
from app.ocr_engine.models import OcrObservation
from app.action_engine.vision import ActionObservation, ActionVision


@dataclass(frozen=True)
class VisionObservation:
    frame_id: int
    source_timestamp: float
    width: int
    height: int
    recognition_available: bool = False
    cards: CardObservation = CardObservation()
    ocr: OcrObservation = OcrObservation()
    actions: ActionObservation = ActionObservation()


class VisionEngine:
    """Frozen layout and references per capture; observations have no strategic meaning."""

    def __init__(self, layouts: LayoutStore | None = None, template_dir: str | None = None,
                 tesseract_cmd="tesseract", decimal_separator="."):
        self.layout = None
        self.detector = None
        self.profile = None
        self.demo = False
        self.revision = None
        self.status = "not_configured"
        self.ocr = OcrEngine(None, None, tesseract_cmd, decimal_separator)
        self.actions = ActionVision(None, None)
        if layouts is None:
            return
        try:
            self.layout, self.revision = layouts.read()
        except (OSError, ValidationError):
            self.status = "layout_unavailable"
            return
        self.ocr = OcrEngine(self.layout, self.revision, tesseract_cmd, decimal_separator)
        self.actions = ActionVision(self.layout, self.revision)
        try:
            directory = Path(template_dir) if template_dir else None
            if self.layout.card_profile:
                root = os.getenv("CARD_PROFILE_ROOT", str(layouts.path.parent / "card_profiles"))
                directory = CardProfiles(root).resolve(self.layout.card_profile)
            deck = TemplateDeck.load(directory)
        except (OSError, ValueError, cv2.error) as exc:
            logging.getLogger(__name__).warning("Card references unavailable: %s", exc)
            self.status = "templates_unavailable"
            return
        self.profile, self.demo = deck.manifest.name, deck.demo
        if self.layout.platform != deck.manifest.platform:
            self.status = "platform_mismatch"
        elif not self.layout.calibrated and not self.demo:
            self.status = "uncalibrated_layout"
        else:
            self.detector = CardDetector(deck)
            self.status = "ready"

    def observe(self, frame: Frame) -> VisionObservation:
        height, width = frame.image.shape[:2]
        status = self.status
        if self.layout and (width != self.layout.width or height != self.layout.height):
            status = "resolution_mismatch"
        reading = CardObservation(status, self.profile, self.demo, self.revision)
        if status == "ready":
            def crop(region):
                return frame.image[region.y:region.y + region.height, region.x:region.x + region.width]
            hero = self.detector.read(crop(self.layout.regions.hero_cards), {2})
            board = self.detector.read(crop(self.layout.regions.board), {3, 4, 5})
            if {card.code for card in hero.cards} & {card.code for card in board.cards}:
                reading = CardObservation("duplicate_cards", self.profile, self.demo, self.revision)
            else:
                reading = CardObservation(status, self.profile, self.demo, self.revision, hero, board)
        return VisionObservation(frame.frame_id, frame.timestamp, int(width), int(height), status == "ready", reading, self.ocr.observe(frame), self.actions.observe(frame))
