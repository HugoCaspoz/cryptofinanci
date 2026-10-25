"""Bounded, retrospective summaries of archived evaluations; never runs a solver."""
import asyncio
import json
import math

from fastapi import HTTPException, Query, Request
from app.config import Mode
from app.session_statistics import hero_statistics


def list_sessions(store, mode, offset=0):
    p = store.marker
    with store.connection() as db:
        total = db.execute(f"SELECT COUNT(*) FROM review_sessions WHERE mode={p}", (mode,)).fetchone()[0]
        rows = db.execute(f"""SELECT s.scope_id,s.status,s.created_at,s.finished_at,
            (SELECT COUNT(*) FROM observed_hands h WHERE h.scope_id=s.scope_id)
            FROM review_sessions s WHERE s.mode={p} ORDER BY s.created_at DESC,s.scope_id LIMIT 20 OFFSET {p}""", (mode, offset)).fetchall()
    return {"items": [dict(zip(("scope_id", "status", "created_at", "finished_at", "hands"), row)) for row in rows],
            "total": total, "offset": offset, "persistence": store.kind}


def allowed(store, capture, session, mode):
    if session["status"] == "capturing":
        return False
    if mode == Mode.TRAINING:
        return True
    if session["status"] != "finished" or capture.review_blocked():
        return False
    with store.connection() as db:
        return not db.execute(f"SELECT 1 FROM observed_hands WHERE scope_id={store.marker} AND status='active' LIMIT 1", (session["scope_id"],)).fetchone()


def summarize(store, scope, mode, opponent_offset=0):
    p = store.marker
    result = {"hands_observed": 0, "hands_incomplete": 0, "decisions": 0,
              "comparable": 0, "ev_loss_bb": None, "top_costs": [], "best_decisions": [],
              "missed_bluffs": [], "costly_aggression": [], "leaks": [],
              "hero_statistics": {"hands_played": None, "vpip": None, "pfr": None, "three_bet": None,
                                  "reason": "El archivo no certifica todas las oportunidades preflop de Hero."}}
    groups, loss, cursor = {}, 0.0, ""
    with store.connection() as db:
        result["hands_observed"] = db.execute(f"SELECT COUNT(*) FROM observed_hands WHERE scope_id={p}", (scope,)).fetchone()[0]
        result["hands_incomplete"] = db.execute(f"SELECT COUNT(*) FROM observed_hands WHERE scope_id={p} AND status!='finished'", (scope,)).fetchone()[0]
        while True:
            rows = db.execute(f"""SELECT d.id,d.hand_id,d.payload,e.result FROM decision_snapshots d
                LEFT JOIN decision_evaluations e ON e.snapshot_id=d.id AND e.scope_id=d.scope_id
                    AND e.hand_id=d.hand_id AND e.mode=d.mode
                WHERE d.scope_id={p} AND d.mode={p} AND d.id>{p} ORDER BY d.id LIMIT 100""", (scope, mode, cursor)).fetchall()
            if not rows:
                break
            for identity, hand, payload, evaluation in rows:
                result["decisions"] += 1
                value = json.loads(evaluation) if evaluation else {}
                delta = (value.get("baseline") or {}).get("ev_difference_bb")
                if value.get("status") != "ready" or isinstance(delta, bool) or not isinstance(delta, (float, int)) or not math.isfinite(delta):
                    continue
                snapshot = json.loads(payload)
                cost = max(0.0, -delta)
                loss += cost
                result["comparable"] += 1
                action = (value.get("actual_action") or {}).get("action", "unknown")
                street = snapshot.get("request", {}).get("state", {}).get("street", "unknown")
                row = {"id": identity, "hand_id": hand, "frame_id": snapshot.get("frame_id"),
                       "street": street, "action": action, "ev_loss_bb": cost, "ev_difference_bb": delta,
                       "history_complete": snapshot.get("history_complete", False)}
                result["best_decisions"] = sorted(result["best_decisions"] + [row], key=lambda r: (r["ev_loss_bb"], r["id"]))[:10]
                if cost <= 0:
                    continue
                result["top_costs"] = sorted(result["top_costs"] + [row], key=lambda r: (-r["ev_loss_bb"], r["id"]))[:10]
                strategy = value.get("strategy_result") or {}
                bluff = (strategy.get("bluff") or {}).get("baseline_strategy") or {}
                equity = ((strategy.get("actual_evaluation") or {}).get("baseline_strategy") or {}).get("equity_when_called")
                category = f"{street}: {action}"
                gain = bluff.get("ev_gain_bb")
                if (bluff.get("bluff_candidate") and bluff.get("classification") in {"bluff", "semi_bluff"}
                        and isinstance(gain, (int, float)) and not isinstance(gain, bool) and math.isfinite(gain)
                        and gain > 0 and action in {"CHECK", "CALL", "FOLD"}):
                    category = "Oportunidad de farol no tomada"
                    result["missed_bluffs"] = sorted(result["missed_bluffs"] + [row], key=lambda r: (-r["ev_loss_bb"], r["id"]))[:10]
                elif action in {"BET", "RAISE", "ALL_IN"} and isinstance(equity, (int, float)) and not isinstance(equity, bool) and 0 <= equity < .5:
                    category = "Agresi\u00f3n costosa con equity baja"
                    result["costly_aggression"] = sorted(result["costly_aggression"] + [row], key=lambda r: (-r["ev_loss_bb"], r["id"]))[:10]
                group = groups.setdefault(category, {"label": category, "count": 0, "ev_loss_bb": 0.0})
                group["count"] += 1
                group["ev_loss_bb"] += cost
            cursor = rows[-1][0]
    result["ev_loss_bb"] = loss if result["comparable"] else None
    result["leaks"] = sorted(groups.values(), key=lambda r: -r["ev_loss_bb"])[:5]
    result["not_comparable"] = result["decisions"] - result["comparable"]
    result["hero_statistics"] = hero_statistics(store, scope, mode)
    result["opponents"] = store.list_opponent_profiles(scope, mode, limit=20, offset=opponent_offset)
    with store.connection() as db:
        result["opponents_total"] = db.execute(f"SELECT COUNT(*) FROM opponent_profiles WHERE scope_id={p} AND mode={p}", (scope, mode)).fetchone()[0]
    return result


async def session_detail(session_id: str, request: Request, opponent_offset: int = Query(0, ge=0)):
    store, capture, mode = request.app.state.hand_store, request.app.state.capture, request.app.state.settings.mode
    session = await asyncio.to_thread(store.review_session, session_id)
    if not session or session["mode"] != mode:
        raise HTTPException(404, "Sesi\u00f3n no encontrada")
    access = await asyncio.to_thread(allowed, store, capture, session, mode)
    summary = await asyncio.to_thread(summarize, store, session_id, mode, opponent_offset) if access else None
    access = access and await asyncio.to_thread(allowed, store, capture, session, mode)
    return {"session": session, "allowed": access, "summary": summary if access else None,
            "reason": "Det\u00e9n la captura y confirma que has terminado la sesi\u00f3n de juego para consultar el resumen.",
            "partial": session["status"] != "finished"}


async def session_opponents(session_id: str, request: Request, offset: int = Query(0, ge=0)):
    from app.session_archive import require_session
    await require_session(request, session_id)
    store, mode = request.app.state.hand_store, request.app.state.settings.mode
    items = await asyncio.to_thread(store.list_opponent_profiles, session_id, mode, 20, offset)
    await require_session(request, session_id)
    return {"items": items, "offset": offset, "has_more": len(items) == 20}
