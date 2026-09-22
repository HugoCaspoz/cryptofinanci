from decimal import Decimal

from app.poker_engine.evaluator import validate_cards
from app.poker_engine.metrics import amount
from app.poker_engine.ranges import expand_range
from .history import replay
from .models import StrategyResult


class PreflopEngine:
    """Deterministic configurable baseline. Abstain on unsupported or inconsistent inputs."""
    def analyze(self, state, config, actions):
        try:
            return self._analyze(state, config, actions)
        except ValueError as exc:
            return StrategyResult(status="unavailable", reason=str(exc))

    def _analyze(self, state, config, actions):
        if state.hand_id != config.hand_id or state.hand_status != "active" or state.street != "preflop" or state.board:
            raise ValueError("Se requiere la mano preflop activa que se confirmó en la configuración.")
        if len(state.hero_cards) != 2:
            raise ValueError("Faltan las dos cartas confirmadas de Hero.")
        validate_cards(state.hero_cards)
        small, big = amount(state.small_blind), amount(state.big_blind)
        if small is None or big is None or not 0 < small < big:
            raise ValueError("Faltan ciegas confirmadas y coherentes.")
        table = {p.seat: p for p in state.players}
        if any(s not in table for s in config.seats):
            raise ValueError("Asientos configurados ausentes del estado.")
        hero = table[config.hero_seat]
        context = replay(config, actions, small / big)
        if not context.pending or context.pending[0] != hero.seat or state.current_player != hero.player_id:
            raise ValueError("El turno de Hero debe coincidir en el historial y en la mesa observada.")
        if hero.folded or any(a.seat == hero.seat for a in actions):
            raise ValueError("Esta versión cubre la primera decisión preflop de Hero; no resuelve vueltas posteriores.")
        players = [table[s] for s in config.seats]
        if any(p.all_in for p in players):
            raise ValueError("No se ofrecen estrategias frente a all-ins observados en esta fase.")
        if any(p.bet_unit != state.blinds_unit or p.stack_unit != state.blinds_unit for p in players):
            raise ValueError("Stacks, apuestas y ciegas deben usar la misma unidad.")
        totals = {}
        for player in players:
            stack, bet = amount(player.stack), amount(player.current_bet)
            if stack is None or bet is None:
                raise ValueError("Faltan stacks o apuestas confirmados de los participantes.")
            if bet / big != context.bets[player.seat] or player.folded and player.seat not in context.folded:
                raise ValueError("Las apuestas o folds observados no coinciden con el historial confirmado.")
            if stack <= 0 and player.seat not in context.folded:
                raise ValueError("Stack cero sin contexto de all-in soportado.")
            totals[player.seat] = (stack + bet) / big
        pot = amount(state.pot)
        if pot is None or state.pot_unit != state.blinds_unit:
            raise ValueError("Falta un bote confirmado en la unidad de las ciegas.")
        expected = sum(context.bets.values()) + config.ante_total_bb
        observed = pot / big + (Decimal(0) if config.pot_includes_bets else sum(context.bets.values()))
        if observed != expected:
            raise ValueError("Bote, ciegas, antes e historial no cuadran; revisa el contexto de la mano.")
        live = [s for s in config.seats if s != hero.seat and s not in context.folded]
        effective = min(totals[hero.seat], max(totals[s] for s in live))
        if len(context.raises) > 1:
            raise ValueError("Los botes con varias subidas quedan fuera de las tablas iniciales.")
        scenario = "single_raise" if context.raises else "limped" if context.callers else "unopened"
        position = context.positions[hero.seat]
        opener = context.positions[context.raises[0]] if context.raises else None
        details = {"position": position, "opener_position": opener, "scenario": scenario,
                   "players_dealt": len(config.seats), "players_remaining": len(live) + 1,
                   "effective_stack_bb": float(effective), "raise_to_bb": float(context.high),
                   "ante_total_bb": float(config.ante_total_bb), "previous_actions": len(actions)}
        matches = [r for r in config.rules if r.scenario == scenario and position in r.positions
                   and (not r.opener_positions or opener in r.opener_positions)
                   and r.min_players <= len(config.seats) <= r.max_players
                   and Decimal(str(r.min_stack_bb)) <= effective <= Decimal(str(r.max_stack_bb))
                   and Decimal(str(r.min_raise_bb)) <= context.high <= Decimal(str(r.max_raise_bb))
                   and Decimal(str(r.min_ante_bb)) <= config.ante_total_bb <= Decimal(str(r.max_ante_bb))]
        if len(matches) != 1:
            return StrategyResult(status="unavailable", reason="No hay una única regla aplicable; faltan tablas o se solapan sus condiciones.", context=details)
        rule = matches[0]
        combo = tuple(sorted(state.hero_cards))
        raise_combos = {c for c, _ in expand_range(rule.raise_range)} if rule.raise_range else set()
        call_combos = {c for c, _ in expand_range(rule.call_range)} if rule.call_range else set()
        current = context.bets[hero.seat]
        if combo in raise_combos:
            target = (context.high * Decimal(str(rule.raise_multiplier)) if context.raises
                      else Decimal(str(rule.open_to_bb))) + context.callers * Decimal(str(rule.extra_per_caller_bb))
            target = min(totals[hero.seat], max(target, context.high + context.increment))
            action = "ALL_IN" if target == totals[hero.seat] else "RAISE"
        elif current == context.high:
            target, action = current, "CHECK"
        elif combo in call_combos:
            target = min(context.high, totals[hero.seat])
            action = "ALL_IN" if target == totals[hero.seat] else "CALL"
        else:
            target, action = current, "FOLD"
        if action == "ALL_IN" and combo in raise_combos and target <= context.high:
            raise ValueError("La subida de la tabla no es posible con el stack disponible; no se sustituye por un call.")
        return StrategyResult(status="ready", reason="Aplicación de la tabla configurada; no es una solución GTO ni garantiza rentabilidad.",
                              action=action, sizing_bb=float(target) if action not in {"FOLD", "CHECK"} else None,
                              additional_bb=float(target - current) if action not in {"FOLD", "CHECK"} else 0,
                              rule_id=rule.id, context=details)
