import asyncio
from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api/hands", tags=["hands"])


@router.get("")
async def hands(request: Request, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                scope_id: str | None = None):
    try:
        return await asyncio.to_thread(request.app.state.hand_store.list_hands, limit, offset, scope_id)
    except Exception:
        raise HTTPException(503, "No se pueden consultar las manos guardadas.") from None


@router.get("/{hand_id}")
async def hand(request: Request, hand_id: str, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)):
    try:
        result = await asyncio.to_thread(request.app.state.hand_store.get, hand_id, after, limit)
    except Exception:
        raise HTTPException(503, "No se puede consultar esta mano.") from None
    if result is None:
        raise HTTPException(404, "Mano no encontrada")
    return result
