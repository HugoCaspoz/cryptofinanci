import asyncio
from typing import Literal
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .engine import CaptureConflict, CaptureEngine
from .file_source import FileVideoSource
from .screen_source import ScreenCaptureSource, CameraCaptureSource
from .source import SourceError
from app.game_state_engine.corrections import CorrectionRequest

router = APIRouter(prefix="/api/capture", tags=["capture"])
MAX_UPLOAD_BYTES = 256 * 1024 * 1024
MAX_FRAME_BYTES = 4 * 1024 * 1024
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}


def engine(request: Request) -> CaptureEngine:
    return request.app.state.capture


class ScreenConfig(BaseModel):
    sampling_mode: Literal["fixed", "adaptive"] = "fixed"
    capture_fps: float = Field(default=5, ge=1, le=15)
    name: str = Field(default="Pantalla o ventana", min_length=1, max_length=80)


class CameraConfig(ScreenConfig):
    name: str = Field(default="Cámara del móvil", min_length=1, max_length=80)


@router.get("")
async def status(request: Request):
    return engine(request).status()


@router.post("/file", status_code=201)
async def start_file(request: Request, file: UploadFile = File(...),
                     capture_fps: float = Form(default=5, ge=1, le=15),
                     sampling_mode: Literal["fixed", "adaptive"] = Form(default="fixed")):
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
        source = FileVideoSource(path, name, 10 if sampling_mode == "adaptive" else capture_fps)
        source.sampling_mode = sampling_mode
        result = await capture.start(source, owned_path=path)
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
        source = ScreenCaptureSource(config.name, 10 if config.sampling_mode == "adaptive" else config.capture_fps)
        source.sampling_mode = config.sampling_mode
        return await engine(request).start(source)
    except CaptureConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{capture_id}/screen-frame", status_code=204)
async def screen_frame(capture_id: str, request: Request):
    return await browser_frame(capture_id, request, "screen")


@router.post("/camera", status_code=201)
async def start_camera(config: CameraConfig, request: Request):
    try:
        source = CameraCaptureSource(config.name, 10 if config.sampling_mode == "adaptive" else config.capture_fps)
        source.sampling_mode = config.sampling_mode
        return await engine(request).start(source)
    except CaptureConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{capture_id}/camera-frame", status_code=204)
async def camera_frame(capture_id: str, request: Request):
    return await browser_frame(capture_id, request, "camera")


async def browser_frame(capture_id: str, request: Request, kind: str):
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_FRAME_BYTES:
            raise HTTPException(413, "El frame supera el límite de 4 MB.")
    if not content:
        raise HTTPException(422, "El frame está vacío.")
    try:
        await engine(request).push_screen(capture_id, bytes(content), kind)
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


def temporal_buffer(capture_id, request):
    capture = engine(request)
    if capture_id != capture.capture_id or capture.pipeline is None:
        raise HTTPException(409, "Esta captura ya no es la actual.")
    return capture.pipeline.buffer


@router.get("/{capture_id}/buffer")
async def buffer_index(capture_id: str, request: Request):
    buffer = temporal_buffer(capture_id, request)
    return JSONResponse({"frames": buffer.index()}, headers={"Cache-Control": "no-store"})


def buffered_response(frame):
    if frame is None:
        raise HTTPException(404, "El frame no está en el buffer. Actualiza el historial.",
                            headers={"Cache-Control": "no-store"})
    return Response(frame.jpeg, media_type="image/jpeg", headers={
        "Cache-Control": "no-store", "X-Frame-Id": str(frame.frame_id),
        "X-Frame-Timestamp": str(frame.timestamp), "X-Frame-Width": str(frame.width),
        "X-Frame-Height": str(frame.height),
    })


@router.post("/{capture_id}/analysis/pause")
async def pause_analysis(capture_id: str, request: Request):
    try:
        return await engine(request).pause_analysis(capture_id)
    except CaptureConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{capture_id}/analysis/resume")
async def resume_analysis(capture_id: str, request: Request):
    try:
        return await engine(request).resume_analysis(capture_id)
    except CaptureConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{capture_id}/corrections")
async def correct(capture_id: str, body: CorrectionRequest, request: Request):
    try:
        return await engine(request).correct(capture_id, body)
    except CaptureConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, "No se pudo guardar la corrección. El análisis sigue pausado; reintenta.") from exc


@router.get("/{capture_id}/corrections")
async def correction_dataset(capture_id: str, request: Request,
                             after: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100)):
    capture = engine(request)
    records = await asyncio.to_thread(capture.hand_store.corrections, capture_id, after, limit)
    records = [r for r in records if r["mode"] == capture.mode]
    return JSONResponse({"records": records, "next_after": records[-1]["revision"] if records else after},
                        headers={"Cache-Control": "no-store"})


@router.get("/{capture_id}/important-frames")
async def important_frames(capture_id: str, request: Request,
                           offset: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100)):
    capture = engine(request)
    result = await asyncio.to_thread(capture.hand_store.important_frames, capture_id, capture.mode, offset, limit)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.get("/{capture_id}/important-frames/{identity}")
async def important_image(capture_id: str, identity: str, request: Request):
    capture = engine(request)
    image = await asyncio.to_thread(capture.hand_store.important_frame, identity, capture_id, capture.mode)
    if image is None:
        raise HTTPException(404, "No se guardó esa imagen en esta captura y modo.")
    return Response(image, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/{capture_id}/corrections/{identity}/frame")
async def correction_image(capture_id: str, identity: str, request: Request):
    capture = engine(request)
    record = await asyncio.to_thread(capture.hand_store.correction, identity)
    if not record or record["capture_id"] != capture_id or record["mode"] != capture.mode:
        raise HTTPException(404, "No existe esa corrección.")
    image = await asyncio.to_thread(capture.hand_store.correction, identity, True)
    if image is None:
        raise HTTPException(404, "No se conservó una imagen para esa corrección.")
    return Response(image, media_type="image/jpeg", headers={"Cache-Control": "no-store",
        "X-Frame-Id": str(record["frame_id"]), "X-Frame-Timestamp": str(record["timestamp"])})


@router.get("/{capture_id}/buffer/frame")
async def buffer_at(capture_id: str, request: Request,
                    timestamp: float = Query(ge=0, allow_inf_nan=False)):
    return buffered_response(temporal_buffer(capture_id, request).get(timestamp=timestamp))


@router.get("/{capture_id}/buffer/frames/{frame_id}")
async def buffer_frame(capture_id: str, frame_id: int, request: Request):
    return buffered_response(temporal_buffer(capture_id, request).get(frame_id=frame_id))


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
