import asyncio

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.config import Mode
from app.feedback.policy import require_access

router = APIRouter(prefix="/api/decisions", tags=["decisions"])


@router.get("")
async def archive(request: Request, hand_id: str = Query(min_length=1, max_length=128),
                  after: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100)):
    await require_access(request, hand_id)
    result = await asyncio.to_thread(request.app.state.hand_store.list_decisions, hand_id, request.app.state.settings.mode, after, limit)
    await require_access(request, hand_id)
    return result


@router.get("/{identity}")
async def detail(identity: str, request: Request):
    record = await asyncio.to_thread(request.app.state.hand_store.get_decision, identity)
    if record is None:
        if request.app.state.settings.mode == Mode.LIVE_REAL_MONEY:
            raise HTTPException(403, "No hay una decisión desbloqueada con esa identidad.")
        raise HTTPException(404, "No se encontró esta instantánea.")
    await require_access(request, record["hand_id"], record["mode"], record["scope_id"])
    return record


@router.get("/{identity}/evaluation")
async def evaluation(identity: str, request: Request):
    record = await detail(identity, request)
    result = await asyncio.to_thread(request.app.state.hand_store.get_evaluation, identity)
    await require_access(request, record["hand_id"], record["mode"], record["scope_id"])
    return result


@router.get("/{identity}/frame")
async def frame(identity: str, request: Request):
    record = await detail(identity, request)
    jpeg = await asyncio.to_thread(request.app.state.hand_store.get_decision_frame, identity)
    await require_access(request, record["hand_id"], record["mode"], record["scope_id"])
    if jpeg is None:
        raise HTTPException(404, "Esta decisión no tiene un fotograma guardado.")
    return Response(jpeg, media_type="image/jpeg")
