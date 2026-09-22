from fastapi import APIRouter, HTTPException, Query, Request
from .models import EventBatch

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("", response_model=EventBatch)
async def events(request: Request, scope_id: str = Query(min_length=1), after: int = Query(default=0, ge=0)):
    engine = request.app.state.capture.observation_state.event_engine
    if scope_id != engine.checkpoint.state.scope_id:
        raise HTTPException(409, "La captura cambió. Consulta el nuevo estado antes de pedir eventos.")
    try:
        return engine.export(after)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
