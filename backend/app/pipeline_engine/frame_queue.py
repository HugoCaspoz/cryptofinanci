import asyncio
from collections import deque

from app.capture_engine.source import Frame


class FrameQueue:
    """Single-event-loop queue: producers never await consumers.

    Overflow evicts the oldest frame. A consumer takes the newest available
    frame and skips stale pending frames. Close wakes an idle consumer.
    """

    def __init__(self, capacity: int = 2):
        if not 1 <= capacity <= 8:
            raise ValueError("La capacidad de la cola debe estar entre 1 y 8.")
        self.capacity = capacity
        self._frames: deque[Frame] = deque()
        self._ready = asyncio.Event()
        self.closed = False
        self.dropped = 0
        self.discarded = 0
        self.high_watermark = 0

    def __len__(self) -> int:
        return len(self._frames)

    def offer(self, frame: Frame) -> None:
        if self.closed:
            raise RuntimeError("Cannot add a frame to a closed queue")
        if len(self._frames) == self.capacity:
            self._frames.popleft()
            self.dropped += 1
        self._frames.append(frame)
        self.high_watermark = max(self.high_watermark, len(self._frames))
        self._ready.set()

    async def take_latest(self) -> Frame | None:
        await self._ready.wait()
        if self._frames:
            frame = self._frames.pop()
            self.dropped += len(self._frames)
            self._frames.clear()
            if not self.closed:
                self._ready.clear()
            return frame
        return None  # Only a closed queue can wake without a frame.

    def close(self, *, discard: bool = False) -> None:
        self.closed = True
        if discard:
            self.discarded += len(self._frames)
            self._frames.clear()
        self._ready.set()

