"""Explicit export/deletion of closed sessions, in bounded pages and transactions."""
import json
from pathlib import Path
import tempfile
import zipfile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask
import asyncio
from app.session_dashboard import allowed

router = APIRouter(prefix="/api/sessions", tags=["session maintenance"])
SCOPED = ("observed_hands", "observed_events", "preflop_results", "strategy_results", "decision_snapshots",
          "decision_evaluations", "opponent_profiles", "opponent_snapshots", "review_sessions", "review_session_events",
          "manual_corrections", "important_frames", "hand_preflop_contexts")
CHILDREN = {"decision_frames": ("snapshot_id", "decision_snapshots", "id"),
            "decision_explanations": ("snapshot_id", "decision_snapshots", "id"),
            "hand_heroes": ("hand_id", "observed_hands", "hand_id")}


def where(table, marker):
    if table in CHILDREN:
        column, parent, key = CHILDREN[table]
        return f"{column} IN (SELECT {key} FROM {parent} WHERE scope_id={marker})"
    return f"scope_id={marker}"


def export_archive(store, scope):
    descriptor, name = tempfile.mkstemp(prefix="zeros-export-", suffix=".zip")
    import os
    os.close(descriptor)
    try:
        with zipfile.ZipFile(name, "w", zipfile.ZIP_DEFLATED) as archive, store.connection() as db:
            archive.writestr("manifest.json", json.dumps({"format": "zeros-session", "version": 1, "scope_id": scope, "contains_private_images": True}))
            for table in (*SCOPED, *CHILDREN):
                offset = 0
                # JPEG rows are read individually; other records are paged.
                limit = 1 if table in {"decision_frames", "important_frames", "manual_corrections"} else 20
                with archive.open(table + ".jsonl", "w") as output:
                    while True:
                        cursor = db.execute(f"SELECT * FROM {table} WHERE {where(table,store.marker)} LIMIT {store.marker} OFFSET {store.marker}", (scope, limit, offset))
                        columns = [column[0] for column in cursor.description]
                        rows = cursor.fetchall()
                        if not rows:
                            break
                        for row in rows:
                            output.write((json.dumps(dict(zip(columns, row)), ensure_ascii=False) + "\n").encode())
                        offset += len(rows)
        return name
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def delete_archive(store, scope, mode):
    with store.connection() as db:
        row = db.execute(f"SELECT mode,status FROM review_sessions WHERE scope_id={store.marker}", (scope,)).fetchone()
        if not row or row != (mode, "finished"):
            raise ValueError("Solo puedes eliminar una sesión finalizada del modo actual.")
        for table in CHILDREN:
            db.execute(f"DELETE FROM {table} WHERE {where(table,store.marker)}", (scope,))
        for table in SCOPED:
            db.execute(f"DELETE FROM {table} WHERE scope_id={store.marker}", (scope,))


async def require_session(request, scope):
    store, capture = request.app.state.hand_store, request.app.state.capture
    session = await asyncio.to_thread(store.review_session, scope)
    if not session or session["mode"] != capture.mode:
        raise HTTPException(404, "Sesión no encontrada.")
    if not await asyncio.to_thread(allowed, store, capture, session, capture.mode):
        raise HTTPException(403, "La revisión de esta sesión está bloqueada.")
    return session


@router.get("/{scope}/export")
async def export(scope: str, request: Request):
    await require_session(request, scope)
    path = await asyncio.to_thread(export_archive, request.app.state.hand_store, scope)
    try:
        await require_session(request, scope)
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise
    return FileResponse(path, filename="zeros-session.zip", media_type="application/zip", headers={"Cache-Control": "no-store, private"},
                        background=BackgroundTask(Path(path).unlink, missing_ok=True))


class DeleteSession(BaseModel):
    confirm_scope: str


@router.delete("/{scope}")
async def delete(scope: str, body: DeleteSession, request: Request):
    if body.confirm_scope != scope:
        raise HTTPException(422, "Confirma la identidad de la sesión que quieres eliminar.")
    capture = request.app.state.capture
    async with capture._control:
        await require_session(request, scope)
        if capture.state == "running" or capture._task and not capture._task.done():
            raise HTTPException(409, "Detén la captura antes de eliminar una sesión.")
        if any(getattr(worker, "task", None) and not worker.task.done() for worker in (capture.strategy, capture.evaluations, capture.poker)):
            raise HTTPException(409, "Espera a que terminen de guardarse las evaluaciones antes de eliminar.")
        await capture.decisions.flush()
        await capture._save_hands()
        try:
            await asyncio.to_thread(delete_archive, request.app.state.hand_store, scope, capture.mode)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        capture.feedback_revision += 1
        capture._notify()
    return {"deleted": scope}
