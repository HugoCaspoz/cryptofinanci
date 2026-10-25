import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.decision_engine.routes import detail
from app.feedback.policy import require_access
from .models import ExplanationRequest
from .service import ExplanationBusy

router = APIRouter(prefix="/api/decisions", tags=["explanations"])


@router.post("/{identity}/explanation")
async def explanation(identity: str, body: ExplanationRequest, request: Request):
    record = await detail(identity, request)
    store = request.app.state.hand_store

    async def check_access():
        await require_access(request, record["hand_id"], record["mode"], record["scope_id"])

    evaluation = (await asyncio.to_thread(store.get_evaluation, identity))["result"]
    strategy = evaluation.get("strategy_result") if evaluation else None
    if strategy is None:
        strategy = await asyncio.to_thread(store.get_decision_strategy, record)
    await check_access()
    if not strategy or strategy.get("status") != "ready":
        raise HTTPException(409, "Todavía no hay un resultado de estrategia guardado que se pueda explicar.")
    try:
        return await request.app.state.explainer.explain(record, strategy, evaluation, body.style, check_access)
    except ExplanationBusy:
        raise HTTPException(429, "Hay otra explicación en marcha. Vuelve a intentarlo en unos segundos.",
                            headers={"Retry-After": "2"}) from None
