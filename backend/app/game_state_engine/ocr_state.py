from collections import deque

from app.ocr_engine.models import TextReading


class StableText:
    MIN_CONFIDENCE = .80

    def __init__(self, key, kind):
        self.key, self.kind = key, kind
        self.value = self.unit = None
        self.confidence = 0.0
        self.raw_text = ""
        self.latest_confidence = 0.0
        self.status = "waiting"
        self.confirmed_frame_id = self.confirmed_timestamp = None
        self.history = deque(maxlen=5)

    def interrupt(self):
        self.history.clear()
        self.status = "unknown"

    def accept(self, reading, frame_id, timestamp):
        if self.history and timestamp - self.history[-1][0] > 2.5:
            self.history.clear()
        self.raw_text, self.latest_confidence = reading.text, reading.confidence
        valid = reading.value is not None and reading.confidence >= self.MIN_CONFIDENCE
        identity = (reading.value, reading.unit) if valid else None
        self.history.append((timestamp, identity, reading.confidence))
        votes = [sample for sample in self.history if identity is not None and sample[1] == identity and 0 <= timestamp - sample[0] <= 6]
        if len(votes) >= 3:
            self.value, self.unit = identity
            self.confidence = min(sample[2] for sample in votes)
            self.confirmed_frame_id, self.confirmed_timestamp = frame_id, timestamp
            self.status = "confirmed"
        else:
            self.status = "pending" if valid else "unknown"

    def snapshot(self):
        return {"key": self.key, "kind": self.kind, "value": self.value, "unit": self.unit,
                "confidence": self.confidence, "raw_text": self.raw_text, "latest_confidence": self.latest_confidence,
                "status": self.status, "confirmed_frame_id": self.confirmed_frame_id,
                "confirmed_timestamp": self.confirmed_timestamp}


class OcrState:
    def reset_hand_values(self):
        for key, field in list(self.fields.items()):
            if key == "pot" or key.endswith((".stack", ".bet")):
                self.fields[key] = StableText(key, field.kind)

    def __init__(self):
        fields = [("pot", "amount"), ("blinds", "blinds")]
        fields += [(f"players.{index}.{name}", "nickname" if name == "nickname" else "amount")
                   for index in range(6) for name in ("nickname", "stack", "bet")]
        self.fields = {key: StableText(key, kind) for key, kind in fields}
        self.status = "waiting"
        self.revision = None
        self.decimal_separator = "."
        self.last_frame_id = self.last_timestamp = None

    def accept(self, observation, frame_id, timestamp):
        if observation.status == "not_sampled":
            return  # Cached/unsampled frames must not count as additional OCR evidence.
        self.status, self.revision = observation.status, observation.layout_revision
        self.decimal_separator = observation.decimal_separator
        if observation.sampled:
            self.last_frame_id, self.last_timestamp = frame_id, timestamp
        if observation.status != "ready":
            for field in self.fields.values():
                field.interrupt()
            return
        readings = {reading.key: reading for reading in observation.readings}
        for key, field in self.fields.items():
            field.accept(readings.get(key, TextReading(key, field.kind)), frame_id, timestamp)

    def snapshot(self):
        return {"status": self.status, "layout_revision": self.revision, "decimal_separator": self.decimal_separator,
                "last_sample_frame_id": self.last_frame_id, "last_sample_timestamp": self.last_timestamp,
                "fields": {key: field.snapshot() for key, field in self.fields.items()}}
