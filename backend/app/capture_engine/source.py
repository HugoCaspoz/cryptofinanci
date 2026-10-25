from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import time

import numpy as np

MAX_PIXELS = 3840 * 2160


class SourceError(ValueError):
    """A source cannot be opened or no longer produces valid frames."""


class EndOfSource(Exception):
    pass


@dataclass(frozen=True)
class Frame:
    frame_id: int
    timestamp: float  # Source-relative seconds, never wall-clock time.
    image: np.ndarray  # BGR image at capture resolution.
    fps: float  # Configured sampling rate, not measured throughput.
    captured_at: float = field(default_factory=time.monotonic)  # Backend availability clock.
    capture_latency_ms: float | None = None  # Decode/adapter work, excluding browser/network.


class VideoSource(ABC):
    sampling_mode: str = "fixed"
    kind: str
    name: str
    capture_fps: float
    duration: float | None = None

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def get_frame(self) -> Frame | None: ...
