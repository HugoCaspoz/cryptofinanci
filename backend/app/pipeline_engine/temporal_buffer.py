"""Bounded, capture-local image history. Source timestamps never mean wall time."""
from collections import deque
from dataclasses import dataclass
from math import isfinite
from threading import Lock

import cv2


@dataclass(frozen=True)
class BufferedFrame:
    frame_id: int
    timestamp: float
    width: int
    height: int
    jpeg: bytes

    def metadata(self):
        return {"frame_id": self.frame_id, "timestamp": self.timestamp,
                "width": self.width, "height": self.height}


class TemporalBuffer:
    def __init__(self, seconds=10, max_bytes=64 * 1024 * 1024, max_frames=450):
        if not 10 <= seconds <= 30 or max_bytes < 1 or max_frames < 1:
            raise ValueError("Invalid temporal buffer limits")
        self.seconds, self.max_bytes, self.max_frames = seconds, max_bytes, max_frames
        self._frames = deque()
        self._bytes = 0
        self._lock = Lock()
        self.evicted = 0
        self.encoding_failures = 0

    def append(self, frame):
        if not isfinite(frame.timestamp):
            return
        # No ndarray or view survives this call. Encode outside the short lock.
        try:
            ok, encoded = cv2.imencode(".jpg", frame.image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        except cv2.error:
            ok, encoded = False, None
        if not ok:
            with self._lock:
                self.encoding_failures += 1
            return
        height, width = frame.image.shape[:2]
        item = BufferedFrame(frame.frame_id, frame.timestamp, width, height, encoded.tobytes())
        with self._lock:
            if self._frames and (item.frame_id <= self._frames[-1].frame_id or
                                 item.timestamp < self._frames[-1].timestamp):
                return
            self._frames.append(item)
            self._bytes += len(item.jpeg)
            while self._frames and (self._frames[0].timestamp < item.timestamp - self.seconds or
                                    len(self._frames) > self.max_frames or self._bytes > self.max_bytes):
                removed = self._frames.popleft()
                self._bytes -= len(removed.jpeg)
                self.evicted += 1

    def get(self, frame_id=None, timestamp=None):
        with self._lock:
            if timestamp is not None and (not isfinite(timestamp) or not self._frames or
                                          timestamp > self._frames[-1].timestamp):
                return None
            for frame in reversed(self._frames):
                if frame_id is not None and frame.frame_id == frame_id:
                    return frame
                if frame_id is None and timestamp is not None and frame.timestamp <= timestamp:
                    return frame
            return None

    def index(self):
        with self._lock:
            return [frame.metadata() for frame in self._frames]

    def clear(self):
        with self._lock:
            self._frames.clear()
            self._bytes = 0

    def snapshot(self):
        with self._lock:
            return {"seconds": self.seconds, "max_frames": self.max_frames, "max_bytes": self.max_bytes,
                    "frames": len(self._frames), "bytes": self._bytes, "evicted_frames": self.evicted,
                    "encoding_failures": self.encoding_failures,
                    "oldest_timestamp": self._frames[0].timestamp if self._frames else None,
                    "latest_timestamp": self._frames[-1].timestamp if self._frames else None}
