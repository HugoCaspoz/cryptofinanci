from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from .defaults import default_rules
from .models import PreflopConfig

router = APIRouter(prefix="/api/preflop", tags=["preflop"])


class ConfigureRequest(PreflopConfig):
    capture_id: str = Field(min_length=1, max_length=64)
    state_revision: int = Field(ge=0)


@router.get("")
async def status(request: Request):
    return request.app.state.capture.status()["preflop"]


@router.get("/defaults")
async def defaults():
    return {"name": "Baseline ilustrativa v1 · sin antes · 20–200 BB",
            "rules": [r.model_dump(mode="json") for r in default_rules()]}


@router.put("/config")
async def configure(body: ConfigureRequest, request: Request):
    capture = request.app.state.capture
    async with capture.preflop.lock:
        state = capture.observation_state.current_state
        if (capture.capture_id != body.capture_id or state.hand_id != body.hand_id
                or capture.observation_state.changes.revision != body.state_revision
                or capture.state != "running" or state.hand_status != "active" or state.street != "preflop"):
            raise HTTPException(409, "La mano o su estado han cambiado. Revisa el contexto preflop antes de aplicarlo.")
        try:
            await capture.preflop.flush()
            capture.preflop.configure(PreflopConfig(**body.model_dump(exclude={"capture_id", "state_revision"})),
                                      capture.observation_state.event_engine.replay.sequence)
            await capture._preflop_locked()
        except Exception:
            capture._notify()
            raise HTTPException(503, "No se pudo guardar el resultado preflop. Se conserva pendiente para reintentar.") from None
        capture._notify()
        return capture.status()["preflop"]
