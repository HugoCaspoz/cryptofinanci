"""Load a complete reference deck once per capture. Never learn from future frames."""
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from .demo import CARD_SIZE, EMPTY_BGR, render_card
from .models import RANKS, SUITS


class TemplateManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    platform: str = Field(min_length=1, max_length=80)
    empty_bgr: tuple[int, int, int]
    empty_tolerance: int = Field(default=16, ge=1, le=40)


def features(image):
    normalized = cv2.resize(image, CARD_SIZE, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(normalized, cv2.COLOR_BGR2GRAY)
    return (255 - gray).astype(np.float32)


class TemplateDeck:
    def __init__(self, manifest: TemplateManifest, images: dict[str, np.ndarray], demo=False):
        if any(not 0 <= color <= 255 for color in manifest.empty_bgr):
            raise ValueError("empty_bgr debe contener tres colores entre 0 y 255")
        expected = {rank + suit for rank in RANKS for suit in SUITS}
        if set(images) != expected:
            raise ValueError("Se requieren las 52 referencias de cartas")
        self.manifest = manifest
        self.demo = demo
        self.templates = []
        for code in sorted(images):
            image = images[code]
            if image is None or image.ndim != 3 or min(image.shape[:2]) < 32 or max(image.shape[:2]) > 1024:
                raise ValueError(f"Referencia inválida: {code}")
            feature = features(image)
            if feature.std() < 10:
                raise ValueError(f"Referencia sin símbolos: {code}")
            self.templates.append((code, feature))

    @classmethod
    def load(cls, directory: Path | None = None):
        if directory is None:
            return cls(TemplateManifest(name="Zeros demo v1", platform="Zeros demo", empty_bgr=EMPTY_BGR),
                       {r + s: render_card(r + s) for r in RANKS for s in SUITS}, demo=True)
        manifest = TemplateManifest.model_validate_json((directory / "manifest.json").read_bytes())
        images = {}
        for rank in RANKS:
            for suit in SUITS:
                path = directory / f"{rank}{suit}.png"
                if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError(f"Falta una referencia válida: {path.name}")
                images[rank + suit] = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        return cls(manifest, images)
