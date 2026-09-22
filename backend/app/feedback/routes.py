import asyncio
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.config import FeedbackRelease
from .policy import access

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class Configure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release: FeedbackRelease


class Finish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_finished: bool = Field(strict=True)


@router.put("/config")
async def configure(body: Configure, request: Request):
    capture = request.app.state.capture
    async with capture._control:
        if capture.state == "running" or capture._task and not capture._task.done():
            raise HTTPException(409, "Configura la revisión antes de iniciar la siguiente captura.")
        capture.feedback_release = body.release
        capture.feedback_revision += 1
        capture._notify()
        return capture.feedback_status()


@router.get("/hands/{hand_id}")
async def status(hand_id: str, request: Request):
    hand = await asyncio.to_thread(request.app.state.hand_store.review_hand, hand_id)
    if hand is None:
        raise HTTPException(404, "Mano no encontrada.")
    capture = request.app.state.capture
    allowed, reason = access(capture, hand)
    session = hand["session"] if hand["mode"] == capture.mode else None
    return {"allowed": allowed, "reason": reason, "session": session,
        "can_finish": bool(session and (session["status"] in {"stopped", "interrupted"}
                           or session["status"] == "capturing" and hand["scope_id"] == capture.observation_state.current_state.scope_id)
                           and not capture.review_blocked() and capture.state != "running")}


@router.post("/sessions/{scope}/finish")
async def finish(scope: str, body: Finish, request: Request):
    capture = request.app.state.capture
    if not body.session_finished:
        raise HTTPException(422, "Indica que has terminado la sesión de juego de esta captura.")
    async with capture._control:
        if capture.state == "running" or capture._task and not capture._task.done() or capture.review_blocked():
            raise HTTPException(409, "Detén la captura y termina de guardar sus datos antes de cerrar la sesión.")
        try:
            await capture.decisions.flush()
            await capture._save_hands()
            if scope == capture.observation_state.current_state.scope_id:
                await asyncio.to_thread(request.app.state.hand_store.stop_review_capture, scope)
            await asyncio.to_thread(request.app.state.hand_store.finish_review_session, scope, capture.mode)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        capture.feedback_revision += 1
        capture._notify()
    return await asyncio.to_thread(request.app.state.hand_store.review_session, scope)
