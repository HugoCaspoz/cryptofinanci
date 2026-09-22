import asyncio
from fastapi import HTTPException

from app.config import Mode, FeedbackRelease


def access(capture, hand, record_mode=None, scope=None):
    """Fail closed. Record mode and persisted session policy cannot be overridden by the browser."""
    if record_mode is not None and record_mode != capture.mode:
        return False, "Este archivo pertenece a otro modo de uso."
    if capture.mode == Mode.TRAINING:
        if hand and hand["mode"] != Mode.TRAINING:
            return False, "Este archivo no es de entrenamiento."
        return True, "Revisión disponible en entrenamiento."
    if capture.review_blocked():
        return False, "Revisión oculta mientras se observa una mano activa o se confirma el inicio de la captura."
    if not hand or hand["mode"] != Mode.LIVE_REAL_MONEY or scope is not None and scope != hand["scope_id"]:
        return False, "No hay un contexto de archivo verificado para desbloquear esta mano."
    session = hand["session"]
    if not session or session["mode"] != Mode.LIVE_REAL_MONEY or hand["status"] == "active":
        return False, "La mano sigue activa o falta su política de revisión."
    if session["status"] == "finished":
        return True, "Revisión desbloqueada al finalizar la sesión."
    if (session["release_policy"] == FeedbackRelease.HAND_FINISHED
            and hand["status"] == "finished" and hand["finished_confirmed"]):
        return True, "Revisión desbloqueada por el final confirmado de la mano."
    return False, ("Declara finalizada la sesión de esta captura para abrir la revisión."
                   if session["release_policy"] == FeedbackRelease.SESSION_FINISHED else
                   "Falta confirmar el final de la mano; una parada o desconexión no lo confirma.")


async def require_access(request, hand_id, record_mode=None, scope=None):
    hand = await asyncio.to_thread(request.app.state.hand_store.review_hand, hand_id)
    allowed, reason = access(request.app.state.capture, hand, record_mode, scope)
    if not allowed:
        raise HTTPException(403, reason)
    return hand
