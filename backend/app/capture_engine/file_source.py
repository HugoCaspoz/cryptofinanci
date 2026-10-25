import math
import time
from pathlib import Path
from typing import Callable

import cv2

from .source import MAX_PIXELS, EndOfSource, Frame, SourceError, VideoSource


class FileVideoSource(VideoSource):
    kind = "file"

    def __init__(self, path: Path, name: str, capture_fps: float = 5,
                 clock: Callable[[], float] = time.monotonic):
        self.path = path
        self.name = name
        self.capture_fps = capture_fps
        self.clock = clock
        self._capture = None
        self._read_index = -1
        self._frame_id = 0

    def start(self) -> None:
        self._capture = cv2.VideoCapture(str(self.path), cv2.CAP_FFMPEG)
        if not self._capture.isOpened():
            raise SourceError("No se puede abrir el vídeo. Comprueba el archivo y su códec.")
        self.source_fps = self._capture.get(cv2.CAP_PROP_FPS)
        count = self._capture.get(cv2.CAP_PROP_FRAME_COUNT)
        width = self._capture.get(cv2.CAP_PROP_FRAME_WIDTH)
        height = self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
        if not all(math.isfinite(value) and value > 0 for value in (self.source_fps, count, width, height)):
            raise SourceError("El vídeo no tiene metadatos válidos de duración o resolución.")
        if width * height > MAX_PIXELS:
            raise SourceError("La resolución máxima de entrada es 3840 × 2160 píxeles.")
        self._total = int(count)
        self.duration = self._total / self.source_fps
        self._read_index = -1
        self._frame_id = 0
        self._started = self.clock()
        self._paused_at = None

    def pause(self):
        if self._paused_at is None:
            self._paused_at = self.clock()

    def resume(self):
        if self._paused_at is not None:
            self._started += self.clock() - self._paused_at
            self._paused_at = None

    def get_frame(self) -> Frame | None:
        if self._capture is None:
            raise SourceError("La fuente de vídeo no está abierta.")
        target = int(((self._paused_at if self._paused_at is not None else self.clock()) - self._started) * self.source_fps)
        if target >= self._total:
            raise EndOfSource
        if target <= self._read_index:
            return None
        # Advance with the source clock. Skipped frames are not turned into
        # observations, and the entire video is never loaded into memory.
        decode_started = time.monotonic()
        while self._read_index < target:
            if not self._capture.grab():
                raise SourceError("El vídeo terminó antes de lo indicado o no se pudo decodificar.")
            self._read_index += 1
        ok, image = self._capture.retrieve()
        if not ok or image is None:
            raise SourceError("No se pudo decodificar un frame del vídeo.")
        self._frame_id += 1
        return Frame(self._frame_id, self._read_index / self.source_fps, image, self.capture_fps,
                     capture_latency_ms=(time.monotonic() - decode_started) * 1000)

    def stop(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None

