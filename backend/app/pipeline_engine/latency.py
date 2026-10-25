"""Bounded durations, never source timestamps or cross-machine clock subtraction."""
from collections import deque
from math import ceil, isfinite


class LatencyWindow:
    CAPACITY = 128

    def __init__(self, target_ms=None):
        self.values = deque(maxlen=self.CAPACITY)
        self.count = 0
        self.frame_id = None
        self.target_ms = target_ms

    def add(self, milliseconds, frame_id=None):
        if not isinstance(milliseconds, (int, float)) or not isfinite(milliseconds) or milliseconds < 0:
            return
        self.values.append(milliseconds)
        self.count += 1
        self.frame_id = frame_id

    def snapshot(self):
        values = sorted(self.values)
        p95 = values[ceil(.95 * len(values)) - 1] if values else None
        return {"last_ms": round(self.values[-1], 2) if values else None,
            "mean_ms": round(sum(values) / len(values), 2) if values else None,
            "p95_ms": round(p95, 2) if values else None,
            "max_ms": round(values[-1], 2) if values else None,
            "samples": len(values), "total_samples": self.count, "frame_id": self.frame_id,
            "target_ms": self.target_ms,
            "within_target": p95 < self.target_ms if p95 is not None and self.target_ms is not None else None}
