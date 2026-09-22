import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.config import Mode
from app.strategy_engine.service import PreflopService
from .models import HandContext

router = APIRouter(prefix="/api/opponents", tags=["opponents"])


class ConfigureRequest(HandContext):
    capture_id: str = Field(min_length=1, max_length=128)
    state_revision: int = Field(ge=0)


class ShowdownRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capture_id: str = Field(min_length=1, max_length=128)
    hand_id: str = Field(min_length=1, max_length=128)
    showdown_observed: Literal[True]


@router.get("")
async def status(request: Request):
    return request.app.state.capture.opponents.snapshot()


@router.put("/context")
async def configure(body: ConfigureRequest, request: Request):
    capture = request.app.state.capture
    async with capture.opponents.lock:
        game = capture.observation_state
        if (body.capture_id != capture.capture_id or capture.state != "running"
                or body.state_revision != game.changes.revision or body.hand_id != game.current_state.hand_id):
            raise HTTPException(409, "La captura o la mano cambió; revisa el contexto actual.")
        try:
            await capture._opponents_locked()
            # Persistence can yield while vision accepts another frame or capture.
            if (body.capture_id != capture.capture_id or capture.observation_state is not game
                    or body.state_revision != game.changes.revision or capture.state != "running"):
                raise HTTPException(409, "El estado cambió mientras se guardaban los datos; revisa el inicio.")
            observation = game.last_observation
            clean = PreflopService.clean_state(game.current_state, game.evidence,
                observation.source_timestamp if observation else None)
            config = HandContext(**body.model_dump(exclude={"capture_id", "state_revision"}))
            capture.opponents.model.configure(config, clean)
            await capture.opponents.save()
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, "No se pudieron guardar las estadísticas.") from exc
    capture._analyze()
    capture._notify()
    return capture.opponents.snapshot()


@router.put("/showdown")
async def showdown(body: ShowdownRequest, request: Request):
    capture = request.app.state.capture
    async with capture.opponents.lock:
        if body.capture_id != capture.capture_id:
            raise HTTPException(409, "Esta captura ya no es la actual.")
        try:
            await capture.opponents.flush()
            capture.opponents.model.confirm_showdown(body.hand_id)
            await capture.opponents.save()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, "No se pudo guardar la confirmación.") from exc
    capture._notify()
    return capture.opponents.snapshot()


@router.get("/archive/{scope_id}")
async def archive(scope_id: str, request: Request):
    if request.app.state.settings.mode != Mode.TRAINING:
        raise HTTPException(403, "El archivo de estadísticas está disponible en entrenamiento.")
    record = await asyncio.to_thread(request.app.state.hand_store.get_opponents, scope_id)
    if record is None:
        raise HTTPException(404, "No hay estadísticas para esta captura.")
    if record.get("mode") != Mode.TRAINING:
        raise HTTPException(403, "El archivo de dinero real sigue reservado para revisión posterior.")
    return record
