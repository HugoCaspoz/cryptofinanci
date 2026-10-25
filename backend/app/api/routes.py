import asyncio
from app.session_dashboard import list_sessions, session_detail, session_opponents
from app.version import PHASE
from fastapi import APIRouter, HTTPException, Request, Query

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict:
    return {
        "status": "ok",
        "service": "zeros-api",
        "phase": PHASE,
        "mode": request.app.state.settings.mode,
        "persistence": request.app.state.hand_store.kind,
    }


@router.get("/api/sessions")
async def sessions(request: Request, offset: int = Query(0, ge=0)) -> dict:
    return await asyncio.to_thread(list_sessions, request.app.state.hand_store, request.app.state.settings.mode, offset)


router.add_api_route("/api/sessions/{session_id}", session_detail, methods=["GET"])
router.add_api_route("/api/sessions/{session_id}/opponents", session_opponents, methods=["GET"])
