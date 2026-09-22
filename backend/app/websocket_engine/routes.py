import asyncio
import anyio
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.config import Mode

router = APIRouter()
SEND_TIMEOUT = 5


@router.websocket("/ws/live")
async def live(websocket: WebSocket) -> None:
    await websocket.accept()
    connection_id, sequence = str(uuid4()), 0
    hub = websocket.app.state.capture_hub
    subscribed = asyncio.Event()
    queue = None
    send_lock = asyncio.Lock()

    async def emit(event_type, payload):
        nonlocal sequence
        async with send_lock:
            sequence += 1
            await asyncio.wait_for(websocket.send_json({
                "version": 1, "type": event_type, "connection_id": connection_id,
                "sequence": sequence, "timestamp": datetime.now(timezone.utc).isoformat(),
                "payload": payload,
            }), timeout=SEND_TIMEOUT)

    async def commands():
        nonlocal queue
        while True:
            incoming = await websocket.receive()
            if incoming["type"] == "websocket.disconnect":
                return
            raw = incoming.get("text")
            if raw is None:
                await websocket.close(code=1003, reason="Se requiere JSON de texto")
                return
            if len(raw) > 4096:
                await websocket.close(code=1009, reason="Mensaje demasiado grande")
                return
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await emit("system.error", {"code": "INVALID_JSON"})
                continue
            if not isinstance(message, dict):
                await emit("system.error", {"code": "UNSUPPORTED_MESSAGE"})
            elif message.get("type") == "ping":
                await emit("system.pong", {})
            elif message.get("type") == "capture.subscribe":
                if queue is None:
                    queue = hub.subscribe()
                    subscribed.set()
            else:
                await emit("system.error", {"code": "UNSUPPORTED_MESSAGE"})

    async def snapshots():
        await subscribed.wait()
        while True:
            snapshot = await queue.get()
            await emit("capture.snapshot", {"capture": snapshot})
            # Capture never waits for sockets; intermediate snapshots are coalesced.
            await asyncio.sleep(.2)

    try:
        await emit("system.ready", {
            "mode": websocket.app.state.settings.mode, "phase": 22,
            "capture_available": True, "strategy_available": websocket.app.state.settings.mode == Mode.TRAINING,
        })
        async with anyio.create_task_group() as tasks:
            async def forward():
                try:
                    await snapshots()
                except (TimeoutError, WebSocketDisconnect, OSError, RuntimeError):
                    try:
                        await asyncio.wait_for(websocket.close(code=1013, reason="Cliente demasiado lento"), timeout=1)
                    except (TimeoutError, RuntimeError, WebSocketDisconnect, OSError):
                        pass
                    tasks.cancel_scope.cancel()

            tasks.start_soon(forward)
            try:
                await commands()
            except (TimeoutError, WebSocketDisconnect, OSError):
                try:
                    await asyncio.wait_for(websocket.close(code=1013), timeout=1)
                except (TimeoutError, RuntimeError, WebSocketDisconnect, OSError):
                    pass
            finally:
                tasks.cancel_scope.cancel()
    except TimeoutError:
        try:
            await asyncio.wait_for(websocket.close(code=1013, reason="Cliente demasiado lento"), timeout=1)
        except (TimeoutError, RuntimeError, WebSocketDisconnect):
            pass
    except (WebSocketDisconnect, OSError):
        pass
    finally:
        if queue is not None:
            hub.unsubscribe(queue)
