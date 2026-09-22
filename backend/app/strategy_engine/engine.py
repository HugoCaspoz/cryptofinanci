"""StrategyEngine: GameState + poker math + opponent model + tournament → baseline and exploit.

It never reads images. Every input is frozen at or before the evaluated frame.
"""
from dataclasses import dataclass

from app.game_state_engine.models import GameState
from app.poker_engine.equity import simulate
from app.poker_engine.evaluator import validate_cards
from app.poker_engine.metrics import amount, metrics
from app.poker_engine.models import PokerConfig
from app.opponent_model.decision import StrategyInput
from app.tournament_context.stage import stage
from .bluff import BluffAnalyzer
from .ev import VERSION, Spot, candidates, evaluate
from .models import StrategyConfig
from .tendencies import fold_model, profile

STREETS = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}


class Waiting(ValueError):
    """Not a Hero decision: nothing to recommend, nothing to archive."""


@dataclass(frozen=True)
class StrategyRequest:
    state: GameState
    poker: PokerConfig
    config: StrategyConfig
    decision: StrategyInput | None
    preflop: dict | None  # Published preflop result plus its Hero seat, only if fresh for this state.
    frame_id: int | None
    timestamp: float | None
    sequence: int
    snapshot_id: str | None = None


def pool_summary(pool):
    return {"available_combos": len(pool), "effective_combos": 1 / sum(w * w for _, w in pool) if pool else 0}


class StrategyEngine:
    def analyze(self, request, actual_option=None):
        state = request.state
        result = {"version": VERSION, "status": "ready", "reason": "", "hand_id": state.hand_id,
                  "street": state.street, "hero_seat": request.poker.hero_seat, "frame_id": request.frame_id,
                  "timestamp": request.timestamp, "event_sequence": request.sequence, "decision": None,
                  "baseline_strategy": None, "exploitative_strategy": None, "adjustments": [],
                  "tournament": None, "bluff": None, "confidence": None, "provenance": None,
                  "basis": "approximate_ev_logit_not_solver"}
        try:
            self._analyze(request, result, actual_option)
        except Waiting as exc:
            result.update(status="waiting", reason=str(exc))
        except ValueError as exc:
            result.update(status="unavailable", reason=str(exc), baseline_strategy=None,
                          exploitative_strategy=None, adjustments=[], bluff=None)
        return result

    def _analyze(self, request, result, actual_option=None):
        state, poker, decision = request.state, request.poker, request.decision
        players = {p.seat: p for p in state.players}
        hero = players.get(poker.hero_seat)
        if hero is None:
            raise ValueError("Asigna Hero en «Motor matemático»: la estrategia usa ese asiento y su convención de bote.")
        if state.hand_status != "active" or state.hand_id is None:
            raise Waiting("Sin mano activa.")
        if hero.folded or state.current_player != hero.player_id:
            raise Waiting("Esperando una decisión de Hero: el turno observado no es suyo.")
        if len(state.hero_cards) != 2 or STREETS.get(len(state.board)) != state.street:
            raise ValueError("Cartas de Hero o calle sin confirmar.")
        validate_cards(state.hero_cards + state.board)
        if request.frame_id is None or request.timestamp is None:
            raise ValueError("Falta el frame evaluado.")
        tournament = decision.tournament if decision and decision.hand_id == state.hand_id else None
        result["tournament"] = stage(tournament)
        if result["tournament"]:
            result["tournament"]["applied"] = request.config.tournament_adjustment and state.street != "preflop"
        if state.street == "preflop":
            self._preflop(request, hero, result)
        else:
            self._postflop(request, players, hero, result, actual_option)

    def _preflop(self, request, hero, result):
        entry = request.preflop
        if entry is None or entry["result"]["hand_id"] != request.state.hand_id:
            raise ValueError("Preflop: aplica «Estrategia preflop» en esta mano; su tabla es la baseline.")
        if entry["hero_seat"] != hero.seat:
            raise ValueError("Hero de «Estrategia preflop» y de «Motor matemático» no coinciden.")
        table = entry["result"]
        if table["status"] != "ready":
            raise ValueError(table["reason"])
        if table["frame_id"] > request.frame_id or table["timestamp"] > request.timestamp:
            raise ValueError("Resultado preflop posterior al estado evaluado.")
        option = {"action": table["action"], "sizing_pot": None, "added_bb": table["additional_bb"],
                  "total_bb": table["sizing_bb"], "all_in": table["action"] == "ALL_IN",
                  "ev_bb": None, "frequency": 1.0}
        baseline = {"basis": "configured_preflop_table", "rule_id": table["rule_id"], "equity": None,
                    "options": [option], "summary": {table["action"]: 1.0}, "highest_ev": None}
        result["baseline_strategy"] = baseline
        result["exploitative_strategy"] = baseline | {"basis": "preflop_table_without_adjustment"}
        result["adjustments"] = [{"input": "preflop", "applied": False,
            "reason": "La tabla preflop es determinista; esta versión no deriva ajustes preflop de las estadísticas."}]
        result["decision"] = {"street": "preflop", "position": table["context"].get("position"),
                              "effective_stack_bb": table["context"].get("effective_stack_bb")}
        result["bluff"] = BluffAnalyzer.preflop()
        result["provenance"] = {"preflop_result_id": table["id"], "frame_id": table["frame_id"],
                                "timestamp": table["timestamp"]}
        result["reason"] = "Tabla preflop configurada; no es una solución GTO ni un cálculo de EV."

    def _postflop(self, request, players, hero, result, actual_option=None):
        state, poker, decision, config = request.state, request.poker, request.decision, request.config
        if decision is None:
            raise ValueError("Confirma el inicio de la mano en «Modelo de rivales»: la estrategia postflop usa su historial.")
        if ((decision.scope_id, decision.hand_id, decision.street, decision.board)
                != (state.scope_id, state.hand_id, state.street, tuple(state.board))):
            raise ValueError("El historial de rivales no corresponde a esta calle o mano.")
        if decision.frame_id > request.frame_id or decision.timestamp > request.timestamp:
            raise ValueError("Historial de rivales posterior al estado evaluado.")
        if hero.seat not in decision.live:
            raise ValueError("Hero no figura como participante activo en el contexto confirmado.")
        villains = [s for s in decision.live if s != hero.seat]
        if len(villains) != 1:
            raise ValueError(f"Esta versión calcula estrategias postflop heads-up; hay {len(villains)} rivales activos.")
        if not decision.pending or decision.pending[0] != hero.seat:
            raise ValueError("El historial confirmado no espera una acción de Hero; revisa el orden de la mano.")
        villain = players.get(villains[0])
        if villain is None or hero.all_in or villain.all_in:
            raise ValueError("No se ofrecen estrategias con all-in observado ni asientos ausentes.")
        values, warnings = metrics(state, hero, [villain], poker)
        big = amount(state.big_blind)
        numbers = [amount(v) for v in (hero.stack, villain.stack, hero.current_bet, villain.current_bet)]
        if big is None or big <= 0 or values["pot_size"] is None or any(v is None for v in numbers):
            raise ValueError("Faltan bote, ciegas, stacks o apuestas confirmados: " + " ".join(warnings))
        if len({state.blinds_unit, state.pot_unit, hero.stack_unit, villain.stack_unit,
                hero.bet_unit, villain.bet_unit}) != 1:
            raise ValueError("Bote, stacks, apuestas y ciegas deben usar la misma unidad.")
        hero_stack, villain_stack, hero_bet, villain_bet = numbers
        bets = dict(decision.bets_bb)
        if hero_bet / big != bets[hero.seat] or villain_bet / big != bets[villain.seat]:
            raise ValueError("Las apuestas observadas no coinciden con el historial confirmado.")
        if hero_stack <= 0 or villain_stack <= 0:
            raise ValueError("Stack cero sin contexto de all-in soportado.")
        order = sorted(decision.live, key=lambda seat: (seat - decision.button_seat - 1) % 6)
        position = "in_position" if order[-1] == hero.seat else "out_of_position"
        tournament = result["tournament"]
        factor = tournament["risk_factor"] if tournament and tournament["applied"] else 1.0
        pot = amount(values["pot_size"])
        spot = Spot(state.street, float(pot / big), float(hero_bet / big), float(villain_bet / big),
                    float(hero_stack / big), float(villain_stack / big),
                    float(decision.high_bb + decision.increment_bb), position, factor)
        options = candidates(spot, config)
        neutral, exploit = dict(decision.neutral_pools)[villain.seat], dict(decision.exploit_pools)[villain.seat]
        if not neutral or not exploit:
            raise ValueError("El rango del rival no tiene combos compatibles.")

        def equity_of(pool, label="continuing"):
            if not pool:
                return 0.0
            return simulate(state.hero_cards, state.board, [(villain.seat, label)], poker.samples,
                            poker.seed, {villain.seat: pool})["equity"]

        observed_fold, source = fold_model(decision, hero.seat, villain.seat, state.street, spot.to_call)
        args = (state.board, state.hero_cards)
        baseline_equity, exploit_equity = equity_of(neutral, "neutral"), equity_of(exploit, "adaptive")
        result["baseline_strategy"] = evaluate(spot, options, config.temperature, baseline_equity,
                                               lambda balanced: balanced, neutral, equity_of, *args) | {
            "basis": "generic_priors_balanced_defense"}
        result["exploitative_strategy"] = evaluate(spot, options, config.temperature, exploit_equity,
                                                   observed_fold, exploit, equity_of, *args) | {
            "basis": "observed_statistics_and_tournament_prior"}
        if actual_option is not None:
            # Evaluate the observed size separately: never change the original menu or its frequencies.
            result["actual_evaluation"] = {}
            for name, pool, equity, rule in (("baseline_strategy", neutral, baseline_equity, lambda f: f),
                                            ("exploitative_strategy", exploit, exploit_equity, observed_fold)):
                matching = next((row for row in result[name]["options"]
                                 if all(row[k] == actual_option[k] for k in ("action", "added_bb", "total_bb", "all_in"))), None)
                result["actual_evaluation"][name] = matching or evaluate(spot, [actual_option], config.temperature,
                    equity, rule, pool, equity_of, *args)["options"][0]
        result["adjustments"] = [
            {"input": "villain_range", "seat": villain.seat, "applied": True,
             "baseline": pool_summary(neutral) | {"equity": baseline_equity},
             "exploit": pool_summary(exploit) | {"equity": exploit_equity},
             "basis": "Mismas acciones; baseline con priors genéricos, explotativa con estadísticas previas a la mano."},
            {"input": "fold_probability", "seat": villain.seat, "applied": source["opportunities"] > 0} | source]
        balanced = {"statistic": None, "reason": "Defensa equilibrada: el farol puro queda en EV 0."}
        result["bluff"] = BluffAnalyzer().analyze(
            spot, state.hero_cards, state.board,
            {"baseline": (result["baseline_strategy"], neutral), "baseline_source": balanced,
             "exploit": (result["exploitative_strategy"], exploit), "exploit_source": source},
            {side: (dict(pools).get(hero.seat, ()), dict(pools)[villain.seat])
             for side, pools in (("baseline", decision.neutral_pools), ("exploit", decision.exploit_pools))},
            poker.samples, poker.seed, profile(decision, villain.seat), values["spr"])
        result["decision"] = {"street": state.street, "position": position, "villain_seat": villain.seat,
            "pot_bb": spot.pot, "to_call_bb": spot.to_call, "hero_stack_bb": spot.hero_stack,
            "villain_stack_bb": spot.villain_stack, "spr": values["spr"],
            "required_equity": values["required_equity"], "realization": spot.realization, "risk_factor": factor}
        result["provenance"] = {"event_sequence": decision.event_sequence, "frame_id": decision.frame_id,
            "timestamp": decision.timestamp, "range_version": decision.version, "samples": poker.samples,
            "seed": poker.seed, "method": "monte_carlo_or_exact_river"}
        result["reason"] = "EV aproximado de una sola decisión; frecuencias logit, sin solver ni re-subidas del rival."
