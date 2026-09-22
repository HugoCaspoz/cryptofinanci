"""Pure GameState → Analysis. This module never reads images or chooses actions."""
from .equity import simulate
from .evaluator import validate_cards
from .metrics import metrics
from .models import PokerConfig
from .postflop import analyze_postflop
from .range_analysis import compare_ranges


class PokerEngine:
    def analyze(self, state, config: PokerConfig, adaptive=None):
        result = {"scope_id": state.scope_id, "hand_id": state.hand_id, "street": state.street,
                  "hero_seat": config.hero_seat, "metrics": None, "equity": None,
                  "postflop": None, "warnings": [], "range_source": config.range_source, "range_provenance": None}
        players = {p.seat: p for p in state.players}
        hero = players.get(config.hero_seat)
        if hero is None or not config.opponents:
            result["warnings"].append("Configura Hero y los asientos que participan en la mano.")
            return result
        if hero.folded:
            result["warnings"].append("Hero se ha retirado; no se calcula equity de una mano activa.")
            return result
        if any(p.seat not in players for p in config.opponents):
            result["warnings"].append("Hay asientos configurados que no existen en este estado.")
            return result
        opponents = [players[p.seat] for p in config.opponents if not players[p.seat].folded]
        if not opponents:
            result["warnings"].append("No quedan rivales configurados sin retirarse.")
            return result
        try:
            result["metrics"], warnings = metrics(state, hero, opponents, config)
            result["warnings"].extend(warnings)
        except ValueError as exc:
            result["warnings"].append(str(exc))
        if len(state.hero_cards) != 2 or state.street != {0: "preflop", 3: "flop", 4: "turn", 5: "river"}.get(len(state.board)):
            result["warnings"].append("Equity pendiente: cartas o calle sin confirmar.")
            return result
        try:
            validate_cards(state.hero_cards + state.board)
        except ValueError as exc:
            result["warnings"].append(str(exc))
            return result
        weighted = None
        if config.range_source == "adaptive":
            if (adaptive is None or adaptive.scope_id != state.scope_id or adaptive.hand_id != state.hand_id
                    or adaptive.board != tuple(state.board) or state.hand_status != "active"):
                result["warnings"].append("Rangos adaptativos pendientes: confirma el inicio y un historial completo de esta mano.")
                return result
            weighted = dict(adaptive.pools)
            if set(weighted) != {hero.seat, *(p.seat for p in opponents)}:
                result["warnings"].append("Los participantes del cálculo no coinciden con el contexto de rangos adaptativos.")
                return result
            if any(p.seat not in weighted or not weighted[p.seat] for p in opponents):
                result["warnings"].append("Falta un rango adaptativo compatible para algún rival seleccionado.")
                return result
            result["range_provenance"] = {"version": adaptive.version, "event_sequence": adaptive.event_sequence,
                "frame_id": adaptive.frame_id, "timestamp": adaptive.timestamp}
            result["warnings"].append("Rangos adaptativos heurísticos, sin calibrar; el intervalo de equity solo mide error de simulación.")
        if len(state.board) >= 3:
            postflop = result["postflop"] = analyze_postflop(state, config, opponents, result["metrics"])
            context = config.postflop_context
            if context is None or context.hand_id != state.hand_id:
                postflop["warnings"].append("Confirma el contexto postflop para esta mano si deseas estudiar rangos y posición.")
            elif context.hero_range:
                if len(opponents) != 1:
                    postflop["warnings"].append("La comparación de rangos está disponible solo con un rival; la equity de la mano sí admite multiway.")
                else:
                    expression = ("adaptive" if weighted is not None else
                                  next(p.range for p in config.opponents if p.seat == opponents[0].seat))
                    try:
                        postflop["range_comparison"] = compare_ranges(tuple(state.board), context.hero_range,
                                                                      expression, config.samples, config.seed,
                                                                      weighted[opponents[0].seat] if weighted is not None else None)
                    except ValueError as exc:
                        postflop["warnings"].append(str(exc))
        try:
            ranges = [(p.seat, "adaptive" if weighted is not None else p.range)
                      for p in config.opponents if not players[p.seat].folded]
            result["equity"] = simulate(state.hero_cards, state.board, ranges, config.samples, config.seed, weighted)
        except ValueError as exc:
            result["warnings"].append(str(exc))
        return result
