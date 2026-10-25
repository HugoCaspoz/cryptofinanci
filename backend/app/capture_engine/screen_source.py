import threading
import time
from typing import Callable

import cv2
import numpy as np

from .source import MAX_PIXELS, Frame, SourceError, VideoSource


class ScreenCaptureSource(VideoSource):
    """Browser-selected desktop/window frames, also usable by a Docker backend.

    One latest frame only. This is the capture adapter, not the phase-3
    processing queue. getDisplayMedia owns the OS permission and selection.
    """

    kind = "screen"
    label = "pantalla"
    timeout = 15.0

    def __init__(self, name: str = "Pantalla o ventana", capture_fps: float = 5,
                 clock: Callable[[], float] = time.monotonic):
        self.name = name
        self.capture_fps = capture_fps
        self.clock = clock
        self._lock = threading.Lock()
        self._running = False
        self._pending: Frame | None = None
        self._frame_id = 0

    def start(self) -> None:
        with self._lock:
            self._running = True
            self._started = self._last_received = self.clock()
            self._frame_id = 0
            self._pending = None

    def push(self, encoded: bytes) -> None:
        decode_started = time.monotonic()
        image = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise SourceError("El frame recibido no es una imagen válida.")
        if image.shape[0] * image.shape[1] > MAX_PIXELS:
            raise SourceError("El frame supera la resolución máxima permitida.")
        with self._lock:
            if not self._running:
                raise SourceError(f"La captura de {self.label} ya está detenida.")
            self._last_received = self.clock()
            self._frame_id += 1
            self._pending = Frame(self._frame_id, self._last_received - self._started,
                                  image, self.capture_fps, capture_latency_ms=(time.monotonic() - decode_started) * 1000)

    def get_frame(self) -> Frame | None:
        with self._lock:
            if self.clock() - self._last_received > self.timeout:
                raise SourceError(f"La {self.label} dejó de enviar imágenes. Vuelve a conectarla.")
            frame, self._pending = self._pending, None
            return frame

    def stop(self) -> None:
        with self._lock:
            self._running = False
            self._pending = None


class CameraCaptureSource(ScreenCaptureSource):
    """Browser-permitted camera; shares the bounded latest-frame ingress."""

    kind = "camera"
    label = "cámara"

