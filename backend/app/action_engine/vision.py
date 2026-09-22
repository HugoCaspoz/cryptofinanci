"""Pixel templates for the synthetic profile; no action text is supplied by OCR."""
from dataclasses import dataclass

import cv2
import numpy as np

LABELS = ("ACTIVE", "FOLD", "CHECK", "CALL", "BET", "RAISE", "ALL-IN")


@dataclass(frozen=True)
class ActionReading:
    label: str | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class ActionObservation:
    status: str = "unavailable"
    readings: tuple[ActionReading, ...] = ()
    layout_revision: str | None = None


def render_badge(width, height, label):
    image = np.full((height, width, 3), (26, 35, 27), np.uint8)
    if label:
        scale = min(.65, (width - 12) / 130, (height - 8) / 28)
        cv2.putText(image, label, (6, round(height * .73)), cv2.FONT_HERSHEY_SIMPLEX,
                    scale, (238, 241, 235), 1, cv2.LINE_AA)
    return image


def mask(image):
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) > 170


class ActionVision:
    def __init__(self, layout, revision):
        self.layout, self.revision = layout, revision
        self.templates = []
        if layout:
            for player in layout.players:
                r = player.action
                self.templates.append([mask(render_badge(r.width, r.height, label)) for label in LABELS])

    def observe(self, frame):
        if not self.layout or self.layout.platform != "Zeros demo":
            return ActionObservation("unsupported_profile", layout_revision=self.revision)
        if frame.image.shape[:2] != (self.layout.height, self.layout.width):
            return ActionObservation("resolution_mismatch", layout_revision=self.revision)
        readings = []
        for player, templates in zip(self.layout.players, self.templates):
            r = player.action
            pixels = frame.image[r.y:r.y+r.height, r.x:r.x+r.width]
            observed = mask(pixels)
            scores = [2 * np.count_nonzero(observed & reference) /
                      max(1, np.count_nonzero(observed) + np.count_nonzero(reference)) for reference in templates]
            order = np.argsort(scores)
            best, second = int(order[-1]), int(order[-2])
            if scores[best] >= .90 and scores[best] - scores[second] >= .08:
                readings.append(ActionReading(LABELS[best], round(scores[best], 4)))
            else:
                readings.append(ActionReading())
        return ActionObservation("ready", tuple(readings), self.revision)
