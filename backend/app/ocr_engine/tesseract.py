import csv
import io
import os
import shutil
import subprocess

import cv2

from .preprocessing import ROW_HEIGHT


class OcrFailure(Exception):
    def __init__(self, status):
        self.status = status


class TesseractReader:
    def __init__(self, executable="tesseract"):
        self.executable = shutil.which(executable)

    def read(self, image, count):
        if not self.executable:
            raise OcrFailure("engine_unavailable")
        ok, encoded = cv2.imencode(".png", image)
        if not ok:
            raise OcrFailure("engine_error")
        try:
            result = subprocess.run(
                [self.executable, "stdin", "stdout", "-l", "eng", "--psm", "6", "--dpi", "150", "tsv"],
                input=encoded.tobytes(), capture_output=True, timeout=2, check=True,
                env={**os.environ, "OMP_THREAD_LIMIT": "1"},
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            raise OcrFailure("engine_timeout") from exc
        except (OSError, subprocess.CalledProcessError) as exc:
            raise OcrFailure("engine_error") from exc
        return parse_tsv(result.stdout.decode("utf-8", errors="replace"), count)


def parse_tsv(text, count):
    rows = [[] for _ in range(count)]
    for item in csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE):
        if item.get("level") != "5" or not item.get("text", "").strip():
            continue
        try:
            top, height = int(item["top"]), int(item["height"])
            row = top // ROW_HEIGHT
            confidence = float(item["conf"]) / 100
            if 0 <= row < count and height > 0 and (top + height - 1) // ROW_HEIGHT == row and 0 <= confidence <= 1:
                rows[row].append((int(item["left"]), item["text"], confidence))
        except (ValueError, KeyError, TypeError):
            continue
    return [(" ".join(item[1] for item in sorted(row))[:80], min((item[2] for item in row), default=0)) for row in rows]
