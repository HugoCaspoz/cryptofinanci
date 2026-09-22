from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict:
    return {
        "status": "ok",
        "service": "zeros-api",
        "phase": 22,
        "mode": request.app.state.settings.mode,
        "persistence": request.app.state.hand_store.kind,
    }


@router.get("/api/sessions")
async def sessions() -> dict:
    # An explicit empty collection until session persistence is implemented.
    return {"items": [], "total": 0, "persistence": "not_implemented"}


@router.get("/api/sessions/{session_id}")
async def session(session_id: str) -> dict:
    raise HTTPException(status_code=404, detail="Sesión no encontrada")
