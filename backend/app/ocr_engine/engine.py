from .models import OcrObservation, TextReading
from .parsing import parse
from .preprocessing import atlas, region_fields
from .tesseract import OcrFailure, TesseractReader


class OcrEngine:
    INTERVAL_SECONDS = .5

    def __init__(self, layout, revision, executable="tesseract", decimal_separator=".", reader=None):
        self.layout, self.revision = layout, revision
        self.decimal_separator = decimal_separator
        self.reader = reader if reader is not None else TesseractReader(executable)
        self.last_sample = float("-inf")
        self.fields = region_fields(layout) if layout else []

    def observe(self, frame):
        def result(status, sampled=False, readings=()):
            return OcrObservation(status, sampled, readings, self.revision, self.decimal_separator)
        if not self.layout:
            return result("layout_unavailable")
        if frame.image.shape[:2] != (self.layout.height, self.layout.width):
            return result("resolution_mismatch")
        if not self.layout.calibrated and self.layout.platform != "Zeros demo":
            return result("uncalibrated_layout")
        if frame.timestamp - self.last_sample < self.INTERVAL_SECONDS:
            return result("not_sampled")
        self.last_sample = frame.timestamp
        image, active = atlas(frame.image, self.fields)
        try:
            recognized = self.reader.read(image, len(self.fields))
        except OcrFailure as exc:
            return result(exc.status, True)
        readings = []
        for (key, kind, _), (text, confidence), has_text in zip(self.fields, recognized, active):
            if not has_text:
                text, confidence = "", 0
            parsed = parse(text, kind, self.decimal_separator)
            value, unit = parsed if parsed else (None, None)
            readings.append(TextReading(key, kind, text, round(confidence, 4), value, unit))
        return result("ready", True, tuple(readings))
