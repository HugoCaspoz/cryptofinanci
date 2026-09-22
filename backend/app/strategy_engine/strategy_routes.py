import asyncio

from fastapi import APIRouter, HTTPException, Query, Request

from app.config import Mode
from .models import StrategyConfig
from app.feedback.policy import require_access

router = APIRouter(prefix="/api/strategy", tags=["strategy"])


@router.get("")
async def status(request: Request):
    capture = request.app.state.capture
    return capture.strategy.snapshot(capture.state == "running")


@router.get("/defaults")
async def defaults():
    return StrategyConfig().model_dump(mode="json")


@router.put("/config")
async def configure(body: StrategyConfig, request: Request):
    # Sizing preferences only; hand facts come from the other confirmed contexts.
    capture = request.app.state.capture
    capture.strategy.configure(body)
    capture._analyze()
    capture._notify()
    return capture.strategy.snapshot(capture.state == "running")


@router.get("/archive")
async def archive(request: Request, hand_id: str = Query(min_length=1, max_length=128)):
    await require_access(request, hand_id)
    records = await asyncio.to_thread(request.app.state.hand_store.list_strategy, hand_id)
    await require_access(request, hand_id)
    return {"items": [r for r in records if r.get("mode") == request.app.state.settings.mode]}
