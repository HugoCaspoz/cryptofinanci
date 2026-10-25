from dataclasses import dataclass, field
from time import monotonic

import cv2

from app.capture_engine.source import Frame, SourceError
from app.vision_engine import VisionEngine, VisionObservation


@dataclass(frozen=True)
class ProcessedFrame:
    metadata: dict
    jpeg: bytes
    observation: VisionObservation
    timings: dict = field(default_factory=dict)


class FrameProcessor:
    def __init__(self, vision: VisionEngine | None = None):
        self.vision = vision or VisionEngine()

    def process(self, frame: Frame) -> ProcessedFrame:
        started = monotonic()
        observation = self.vision.observe(frame)
        observed_at = monotonic()
        image = frame.image
        height, width = image.shape[:2]
        if width > 1280 or height > 720:
            ratio = min(1280 / width, 720 / height)
            image = cv2.resize(image, (max(1, int(width * ratio)), max(1, int(height * ratio))))
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            raise SourceError("No se pudo preparar la previsualización.")
        return ProcessedFrame({
            "frame_id": frame.frame_id,
            "timestamp": frame.timestamp,
            "fps": frame.fps,
            "width": int(width),
            "height": int(height),
        }, encoded.tobytes(), observation, {"vision": (observed_at - started) * 1000,
            "preview": (monotonic() - observed_at) * 1000})

