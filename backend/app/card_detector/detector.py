import cv2
import numpy as np

from .models import Card, RegionReading, SUITS
from .templates import TemplateDeck, features


class CardDetector:
    MIN_SCORE = .86
    MIN_MARGIN = .035

    def __init__(self, deck: TemplateDeck):
        self.deck = deck

    def classify(self, crop: np.ndarray) -> Card | None:
        sample = features(crop)
        if sample.std() < 10:
            return None
        scores = []
        for code, reference in self.deck.templates:
            # Both index and suit must agree; a large matching suit cannot hide a bad rank.
            rank = float(cv2.matchTemplate(sample[4:50], reference[4:50], cv2.TM_CCOEFF_NORMED)[0, 0])
            suit = float(cv2.matchTemplate(sample[50:124], reference[50:124], cv2.TM_CCOEFF_NORMED)[0, 0])
            scores.append((min(rank, suit), code))
        scores.sort(reverse=True)
        score, code = scores[0]
        if not np.isfinite(score) or score < self.MIN_SCORE or score - scores[1][0] < self.MIN_MARGIN:
            return None
        return Card(code[0], SUITS[code[1]], round(max(0, min(1, score)), 4))

    def read(self, roi: np.ndarray, counts: set[int]) -> RegionReading:
        if roi.size == 0:
            return RegionReading()
        background = np.array(self.deck.manifest.empty_bgr, dtype=np.int16)
        distance = np.abs(roi.astype(np.int16) - background).max(axis=2)
        if float((distance <= self.deck.manifest.empty_tolerance).mean()) >= .985:
            return RegionReading("empty")
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (0, 0, 185), (179, 65, 255))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w < 20 or h < 32:
                continue
            if not .5 <= w / h <= .9 or cv2.contourArea(contour) < .80 * w * h:
                return RegionReading()
            if x == 0 or y == 0 or x + w >= roi.shape[1] or y + h >= roi.shape[0]:
                return RegionReading()  # Clipped cards are not complete observations.
            boxes.append((x, y, w, h))
        if len(boxes) not in counts:
            return RegionReading()
        cards = []
        for x, y, w, h in sorted(boxes):
            card = self.classify(roi[y:y + h, x:x + w])
            if card is None:
                return RegionReading()
            cards.append(card)
        if len({card.code for card in cards}) != len(cards):
            return RegionReading()
        return RegionReading("known", tuple(cards))
