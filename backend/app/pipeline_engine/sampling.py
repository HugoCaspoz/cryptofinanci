"""Cheap visual gate; no OCR, poker inference or retained full frames."""
import cv2
import numpy as np


class SmartSampler:
    def __init__(self, layout=None):
        self.layout = layout
        self.previous = None
        self.last_selected = None
        self.next_due = None
        self.burst_until = float("-inf")
        self.observed = 0
        self.skipped = 0
        self.target_fps = 2

    def select(self, frame):
        image = frame.image
        height, width = image.shape[:2]
        regions = []
        if self.layout and (width, height) == (self.layout.width, self.layout.height):
            regions = [self.layout.regions.hero_cards, self.layout.regions.board,
                       self.layout.regions.pot, self.layout.regions.dealer_button]
            for player in self.layout.players:
                regions.extend([player.stack, player.bet, player.action])
        crops = [image[r.y:r.y+r.height, r.x:r.x+r.width] for r in regions] or [image]
        signatures = [cv2.cvtColor(cv2.resize(crop, (64, 32), interpolation=cv2.INTER_AREA),
                                   cv2.COLOR_BGR2GRAY) for crop in crops]
        changed = self.previous is not None and (
            len(signatures) != len(self.previous) or any(
                np.count_nonzero(cv2.absdiff(a, b) > 20) / a.size >= 0.025
                for a, b in zip(signatures, self.previous)))
        self.previous = signatures
        self.observed += 1
        now = frame.timestamp
        if changed:
            self.burst_until = now + 2
        previous_fps = self.target_fps
        self.target_fps = 10 if now < self.burst_until else 2
        interval = 1 / self.target_fps
        if previous_fps != self.target_fps and not changed and self.last_selected is not None:
            self.next_due = self.last_selected + interval
        selected = self.next_due is None or changed or now >= self.next_due - 1e-6
        if selected:
            self.last_selected = now
            # Keep cadence on sources whose native FPS cannot land on every deadline.
            self.next_due = now + interval if changed or self.next_due is None else self.next_due + interval
            if self.next_due <= now:
                self.next_due = now + interval
        else:
            self.skipped += 1
        return selected

    def snapshot(self):
        return {"mode": "adaptive", "target_fps": self.target_fps,
                "observed_frames": self.observed, "skipped_frames": self.skipped,
                "burst_seconds": 2}
