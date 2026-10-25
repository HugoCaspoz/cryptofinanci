import time
from collections import deque, OrderedDict
from typing import Callable

from .frame_queue import FrameQueue
from .latency import LatencyWindow


class PipelineMetrics:
    WINDOW_SECONDS = 5.0
    MAX_RATE_SAMPLES = 512
    MAX_LATENCY_SAMPLES = 128

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.started = clock()
        self.captured_frames = 0
        self.processed_frames = 0
        self.failed_frames = 0
        self.discarded_in_flight = 0
        self.in_flight = 0
        self.active = False
        self._captures: deque[float] = deque(maxlen=self.MAX_RATE_SAMPLES)
        self._processed: deque[float] = deque(maxlen=self.MAX_RATE_SAMPLES)
        self._latencies: deque[float] = deque(maxlen=self.MAX_LATENCY_SAMPLES)
        self.queue_wait_ms: float | None = None
        self.frame_latency_ms: float | None = None
        self.latencies = {name: LatencyWindow(target) for name, target in {
            "capture": None, "vision": 200, "preview": None, "state": 50, "publish": None,
            "equity": None, "strategy": None, "total_backend": None,
            "equity_total": None, "strategy_total": None}.items()}
        self.origins = OrderedDict()

    def record_origin(self, frame_id, captured_at, capture_ms):
        self.latencies["capture"].add(capture_ms, frame_id)
        self.origins[frame_id] = captured_at - capture_ms / 1000
        if len(self.origins) > self.MAX_LATENCY_SAMPLES:
            self.origins.popitem(last=False)

    def record_analysis(self, kind, frame_id, milliseconds, finished_at):
        self.latencies[kind].add(milliseconds, frame_id)
        origin = self.origins.get(frame_id)
        if origin is not None:
            self.latencies[kind + "_total"].add((finished_at - origin) * 1000, frame_id)

    def record_capture(self) -> None:
        self.captured_frames += 1
        self._captures.append(self.clock())

    def record_processed(self, captured_at: float, started_at: float, finished_at: float) -> None:
        self.processed_frames += 1
        self._processed.append(finished_at)
        self._latencies.append(max(0, (finished_at - started_at) * 1000))
        self.queue_wait_ms = max(0, (started_at - captured_at) * 1000)
        self.frame_latency_ms = max(0, (finished_at - captured_at) * 1000)

    def _fps(self, samples: deque[float], now: float) -> float:
        while samples and samples[0] <= now - self.WINDOW_SECONDS:
            samples.popleft()
        elapsed = now - self.started
        if not self.active or elapsed < 1:
            return 0.0
        return round(len(samples) / min(elapsed, self.WINDOW_SECONDS), 2)

    def snapshot(self, queue: FrameQueue) -> dict:
        now = self.clock()
        return {
            "active": self.active,
            "latencies": {name: window.snapshot() for name, window in self.latencies.items()},
            "window_seconds": self.WINDOW_SECONDS,
            "capture_fps": self._fps(self._captures, now),
            "processing_fps": self._fps(self._processed, now),
            "queue_size": len(queue),
            "queue_capacity": queue.capacity,
            "queue_high_watermark": queue.high_watermark,
            "captured_frames": self.captured_frames,
            "processed_frames": self.processed_frames,
            "dropped_frames": queue.dropped,
            "discarded_frames": queue.discarded + self.discarded_in_flight,
            "failed_frames": self.failed_frames,
            "in_flight": self.in_flight,
            "processing_latency_ms": round(self._latencies[-1], 2) if self._latencies else None,
            "mean_processing_latency_ms": round(sum(self._latencies) / len(self._latencies), 2) if self._latencies else None,
            "queue_wait_ms": round(self.queue_wait_ms, 2) if self.queue_wait_ms is not None else None,
            "frame_latency_ms": round(self.frame_latency_ms, 2) if self.frame_latency_ms is not None else None,
        }

