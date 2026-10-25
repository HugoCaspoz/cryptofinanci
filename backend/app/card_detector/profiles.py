"""Immutable, validated deck imports. ZIP members are never extracted by path."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import tempfile
import zipfile

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from .templates import TemplateDeck, TemplateManifest
from .models import RANKS, SUITS

router = APIRouter(prefix="/api/card-profiles", tags=["card profiles"])
MAX_UPLOAD = 16 * 1024 * 1024


class CardProfiles:
    def __init__(self, root):
        self.root = Path(root)

    def resolve(self, identity):
        if not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise ValueError("Identidad de perfil no válida.")
        return self.root / identity

    def list(self):
        items = []
        if self.root.exists():
            for path in sorted(self.root.iterdir()):
                if re.fullmatch(r"[0-9a-f]{64}", path.name) and (path / "manifest.json").is_file():
                    manifest = TemplateManifest.model_validate_json((path / "manifest.json").read_bytes())
                    items.append({"id": path.name, "name": manifest.name, "platform": manifest.platform})
        return items

    def install(self, raw):
        if len(raw) > MAX_UPLOAD:
            raise ValueError("El ZIP supera 16 MiB.")
        identity = hashlib.sha256(raw).hexdigest()
        destination = self.resolve(identity)
        self.root.mkdir(parents=True, exist_ok=True)
        expected = {"manifest.json"} | {r + s + ".png" for r in RANKS for s in SUITS}
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) != 53 or {i.filename for i in members} != expected:
                raise ValueError("El ZIP debe contener manifest.json y las 52 cartas PNG en su raíz, sin archivos adicionales.")
            if sum(i.file_size for i in members) > 64 * 1024 * 1024 or any(i.flag_bits & 1 for i in members):
                raise ValueError("El perfil está cifrado o supera el tamaño admitido.")
            with tempfile.TemporaryDirectory(prefix=".import-", dir=self.root) as scratch:
                root = Path(scratch)
                for entry in members:
                    limit = 8192 if entry.filename == "manifest.json" else 2 * 1024 * 1024
                    if entry.file_size > limit:
                        raise ValueError("Una referencia supera el tamaño permitido.")
                    content = archive.read(entry)
                    if entry.filename.endswith(".png"):
                        if content[:8] != b"\x89PNG\r\n\x1a\n" or len(content) < 24:
                            raise ValueError("Las cartas deben ser imágenes PNG válidas.")
                        width, height = struct.unpack(">II", content[16:24])
                        if not 32 <= width <= 1024 or not 32 <= height <= 1024:
                            raise ValueError("Las referencias deben medir entre 32 y 1024 píxeles por lado.")
                    (root / entry.filename).write_bytes(content)
                deck = TemplateDeck.load(root)  # Also checks manifest, all cards and visual features.
                if not destination.exists():
                    os.rename(root, destination)
                return {"id": identity, "name": deck.manifest.name, "platform": deck.manifest.platform}


@router.get("")
async def profiles(request: Request):
    import asyncio
    return {"items": await asyncio.to_thread(request.app.state.card_profiles.list)}


@router.post("", status_code=201)
async def upload_profile(request: Request, file: UploadFile = File(...)):
    import asyncio
    try:
        raw = await file.read(MAX_UPLOAD + 1)
        if len(raw) > MAX_UPLOAD:
            raise HTTPException(413, "El ZIP supera 16 MiB.")
        result = await asyncio.to_thread(request.app.state.card_profiles.install, raw)
        return result
    except (ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        await file.close()
