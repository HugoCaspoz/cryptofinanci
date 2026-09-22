from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field

from .engine import CaptureConflict, CaptureEngine
from .file_source import FileVideoSource
from .screen_source import ScreenCaptureSource
from .source import SourceError

router = APIRouter(prefix="/api/capture", tags=["capture"])
MAX_UPLOAD_BYTES = 256 * 1024 * 1024
MAX_FRAME_BYTES = 4 * 1024 * 1024
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


def engine(request: Request) -> CaptureEngine:
    return request.app.state.capture


class ScreenConfig(BaseModel):
    capture_fps: float = Field(default=5, ge=1, le=15)
    name: str = Field(default="Pantalla o ventana", min_length=1, max_length=80)


@router.get("")
async def status(request: Request):
    return engine(request).status()


@router.post("/file", status_code=201)
async def start_file(request: Request, file: UploadFile = File(...),
                     capture_fps: float = Form(default=5, ge=1, le=15)):
    capture = engine(request)
    name = (file.filename or "video").replace("\\", "/").split("/")[-1][:120]
    suffix = Path(name).suffix.lower()
    path = capture.upload_dir / f"{uuid4()}{suffix}"
    owned = False
    try:
        if capture.state == "running":
            raise CaptureConflict("Detén la captura actual antes de abrir otra fuente.")
        if suffix not in VIDEO_EXTENSIONS:
            raise HTTPException(415, "Usa un archivo MP4, MOV, MKV, AVI o WebM.")
        size = 0
        with path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "El tamaño máximo de vídeo es 256 MB.")
                destination.write(chunk)
        if size == 0:
            raise HTTPException(422, "El archivo está vacío.")
        result = await capture.start(FileVideoSource(path, name, capture_fps), owned_path=path)
        owned = True
        return result
    except CaptureConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except SourceError as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        await file.close()
        if not owned:
            path.unlink(missing_ok=True)


@router.post("/screen", status_code=201)
async def start_screen(config: ScreenConfig, request: Request):
    try:
        return await engine(request).start(ScreenCaptureSource(config.name, config.capture_fps))
    except CaptureConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{capture_id}/screen-frame", status_code=204)
async def screen_frame(capture_id: str, request: Request):
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_FRAME_BYTES:
            raise HTTPException(413, "El frame supera el límite de 4 MB.")
    if not content:
        raise HTTPException(422, "El frame está vacío.")
    try:
        await engine(request).push_screen(capture_id, bytes(content))
    except CaptureConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except SourceError as exc:
        raise HTTPException(422, str(exc)) from exc
    return Response(status_code=204)


@router.post("/{capture_id}/stop")
async def stop(capture_id: str, request: Request):
    try:
        return await engine(request).stop(capture_id)
    except CaptureConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{capture_id}/frame")
async def frame(capture_id: str, request: Request, after: int = 0):
    capture = engine(request)
    if capture_id != capture.capture_id:
        raise HTTPException(409, "Esta captura ya no es la actual.")
    preview = capture.preview
    if preview is None or preview[0]["frame_id"] <= after:
        return Response(status_code=204, headers={"Cache-Control": "no-store"})
    metadata, jpeg = preview
    return Response(jpeg, media_type="image/jpeg", headers={
        "Cache-Control": "no-store",
        "X-Frame-Id": str(metadata["frame_id"]),
        "X-Frame-Width": str(metadata["width"]),
        "X-Frame-Height": str(metadata["height"]),
        "X-Frame-Timestamp": str(metadata["timestamp"]),
        "X-Capture-Fps": str(metadata["fps"]),
    })
