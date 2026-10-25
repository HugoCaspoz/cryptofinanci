"""Compare an observed action with a frozen decision. Later board/results never enter the math."""
from decimal import Decimal

from app.strategy_engine.engine import StrategyEngine
from app.strategy_engine.ev import VERSION

ACTIONS = {"PLAYER_FOLDED": "FOLD", "PLAYER_CHECKED": "CHECK", "PLAYER_CALLED": "CALL",
           "PLAYER_BET": "BET", "PLAYER_RAISED": "RAISE", "PLAYER_ALL_IN": "ALL_IN"}


def resolve_action(snapshot, events, ended=False, truncated=False):
    """Resolve only the first action after the decision; never skip an intervening action/street."""
    state = snapshot["request"]["state"]
    hero = next(p for p in state["players"] if p["seat"] == snapshot["hero_seat"])
    previous = snapshot["event_sequence"]
    for event in events:
        if event["scope_id"] != snapshot["scope_id"] or event["sequence"] <= snapshot["event_sequence"]:
            raise ValueError("Historial ajeno o anterior al punto de decisión.")
        if event["sequence"] != previous + 1:
            return {"link_status": "unavailable", "reason": "Faltan eventos entre la instantánea y la acción.", "actual_event": None}
        previous = event["sequence"]
        kind, after = event["type"], event["state_after"]
        if (event["hand_id"] != snapshot["hand_id"] or after["street"] != state["street"]
                or after["board"] != state["board"]
                or kind in {"HAND_STARTED", "HAND_FINISHED", "CAPTURE_ENDED", "HERO_DECISION_REQUIRED", "MANUAL_CORRECTION", "ANALYSIS_RESUMED"}):
            return {"link_status": "unavailable", "reason": "El turno terminó o cambió antes de observar una acción inequívoca de Hero.", "actual_event": None}
        if kind.startswith("PLAYER_"):
            if (event["player_id"] != hero["player_id"] or event["frame_id"] < snapshot["frame_id"]
                    or event["timestamp"] < snapshot["timestamp"]):
                return {"link_status": "unavailable", "reason": "Otra acción intermedia impide atribuir la decisión a Hero.", "actual_event": None}
            return {"link_status": "matched", "reason": "Primera acción confirmada tras la instantánea.",
                    "actual_event": {k: v for k, v in event.items() if k != "state_after"}}
    if ended or truncated:
        return {"link_status": "unavailable", "reason": "No se conservó una acción de Hero con historial suficiente.", "actual_event": None}
    return None


def actual_option(request, event):
    """Amounts are street totals. Validate against the old stacks/bets, not the resulting state."""
    state = request.state
    hero = next(p for p in state.players if p.seat == request.poker.hero_seat)
    if (event["scope_id"] != state.scope_id or event["hand_id"] != state.hand_id
            or event["player_id"] != hero.player_id or event["sequence"] <= request.sequence
            or event["frame_id"] < request.frame_id or event["timestamp"] < request.timestamp):
        raise ValueError("La acción no corresponde al instante guardado.")
    kind = ACTIONS.get(event["type"])
    if kind is None:
        raise ValueError("Tipo de acción no soportado.")
    big = Decimal(state.big_blind)
    bet, stack = Decimal(hero.current_bet) / big, Decimal(hero.stack) / big
    decision = request.decision
    high = decision.high_bb if decision else max(Decimal(p.current_bet) / big for p in state.players if not p.folded)
    owed = max(Decimal(0), high - bet)
    added, total, all_in = Decimal(0), bet, False
    if kind == "CHECK" and owed > 0:
        raise ValueError("El check observado no encaja con la apuesta pendiente.")
    if kind not in {"CHECK", "FOLD"}:
        if event["amount"] is None or event["unit"] != state.blinds_unit:
            raise ValueError("Falta un importe de acción con unidades coherentes.")
        total = Decimal(event["amount"]) / big
        added = total - bet
        if not 0 < added <= stack:
            raise ValueError("El importe observado supera el stack congelado o no lo incrementa.")
        all_in = added == stack
        if kind == "ALL_IN":
            if not all_in:
                raise ValueError("El all-in no coincide con el stack congelado.")
            # An all-in label can denote a call, bet or raise.
            kind = "CALL" if added <= owed else "ALL_IN"
        if kind == "CALL":
            if owed <= 0 or added != min(owed, stack):
                raise ValueError("El call no coincide con el importe pendiente.")
        else:
            if (added <= owed or kind == "BET" and high > 0 or kind == "RAISE" and high == 0):
                raise ValueError("La apuesta/subida no encaja con el estado congelado.")
            if decision is None:
                if state.street != "preflop":
                    raise ValueError("Falta historial para comprobar la subida mínima.")
            elif total < decision.high_bb + decision.increment_bb and not all_in:
                raise ValueError("La subida observada queda por debajo del mínimo legal.")
            if all_in:
                kind = "ALL_IN"
    return {"action": kind, "added_bb": float(added), "total_bb": float(total), "all_in": all_in,
            "sizing_pot": None}


class DecisionEvaluator:
    def __init__(self, engine=None):
        self.engine = engine or StrategyEngine()

    def evaluate(self, snapshot, link):
        payload = snapshot.payload()
        result = {"version": "decision-evaluation-v1", "decision_snapshot_id": snapshot.id,
            "hand_id": payload["hand_id"], "mode": payload["mode"], "status": "unavailable",
            "reason": link["reason"], "actual_action": None, "baseline": None, "exploitative": None,
            "confidence": {"level": "insufficient", "value": None,
                "reason": "Sin probabilidad de acierto calibrada."},
            "strategy_result": None, "source_event_sequence": payload["source_event_sequence"]}
        event = link["actual_event"]
        if event is None:
            return result
        result["actual_action"] = {"action": ACTIONS.get(event["type"], event["type"]),
            "observed_type": event["type"], "amount": event["amount"], "unit": event["unit"],
            "event_sequence": event["sequence"], "frame_id": event["frame_id"], "timestamp": event["timestamp"],
            "observation_confidence": event["confidence"], "evidence": event.get("action_evidence", [])}
        try:
            if payload["ev_model_version"] != VERSION:
                raise ValueError("El motor actual no coincide con la versión guardada; no se reinterpreta el pasado.")
            request = snapshot.request()
            option = actual_option(request, event)
            result["actual_action"].update(option)
            strategy = self.engine.analyze(request, actual_option=option)
            result["strategy_result"] = strategy
            if strategy["status"] != "ready":
                raise ValueError(strategy["reason"])
            for output, key in (("baseline", "baseline_strategy"), ("exploitative", "exploitative_strategy")):
                choices = strategy[key]["options"]
                best = max(choices, key=lambda row: row["ev_bb"] if row["ev_bb"] is not None else row["frequency"])
                observed = strategy.get("actual_evaluation", {}).get(key)
                matches = [row for row in choices if row["action"] == option["action"]
                           and (option["action"] in {"FOLD", "CHECK", "CALL"}
                                or row["total_bb"] == option["total_bb"])]
                delta = observed["ev_bb"] - best["ev_bb"] if observed is not None else None
                result[output] = {"recommendation": {k: best[k] for k in ("action", "total_bb", "ev_bb")},
                    "actual_ev_bb": observed["ev_bb"] if observed else None, "ev_difference_bb": delta,
                    "configured_frequency": sum(row["frequency"] for row in matches),
                    "size_in_original_menu": bool(matches)}
            result["status"] = "table_only" if request.state.street == "preflop" else "ready"
            result["reason"] = ("Comparación con la tabla preflop; no hay un modelo de EV preflop."
                if result["status"] == "table_only" else
                "EV de la acción real menos el mejor EV entre los tamaños configurados. Estimación, no pérdida realizada.")
            result["confidence"] = {"level": "limited", "value": None,
                "reason": "Modelo heurístico sin calibrar; la confianza visual no es confianza estratégica.",
                "history_complete": payload["history_complete"], "samples": request.poker.samples}
        except (ValueError, ArithmeticError, KeyError) as exc:
            result["reason"] = str(exc)
        return result
