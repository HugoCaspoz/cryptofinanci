from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from .models import PokerConfig

router = APIRouter(prefix="/api/poker", tags=["poker"])


class ConfigureRequest(PokerConfig):
    capture_id: str = Field(min_length=1, max_length=64)


@router.get("")
async def status(request: Request):
    return request.app.state.capture.poker.snapshot()


@router.put("/config")
async def configure(body: ConfigureRequest, request: Request):
    capture = request.app.state.capture
    if body.capture_id != capture.capture_id:
        raise HTTPException(409, "Esta captura ya no es la actual.")
    if body.postflop_context and body.postflop_context.hand_id != capture.observation_state.current_state.hand_id:
        raise HTTPException(409, "El contexto postflop pertenece a otra mano. Revisa los rangos y el botón.")
    capture.poker.configure(PokerConfig(**body.model_dump(exclude={"capture_id"})))
    capture._analyze()
    capture._notify()
    return capture.poker.snapshot()
