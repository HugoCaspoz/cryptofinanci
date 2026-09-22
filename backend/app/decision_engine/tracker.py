from decimal import Decimal

from app.poker_engine.evaluator import validate_cards
from .models import DecisionSnapshot


class DecisionTracker:
    """GameState-owned projection: one snapshot per turn opportunity, not per frame/config change."""
    def __init__(self):
        self.cursor = 0
        self.hand_id = None
        self.actions = []
        self.complete = False
        self.last_action = 0
        self.seen = set()
        self.active = None
        self.reason = "Asigna Hero y espera un turno confirmado."

    def observe(self, events, sequence, state, frame, timestamp):
        if sequence < self.cursor:
            self.reason = "El cursor del historial retrocedió."
            return False
        if self.hand_id != state.hand_id:
            self.hand_id, self.actions, self.seen, self.complete = state.hand_id, [], set(), False
            self.last_action = 0
        selected = [e for e in events if e.sequence > self.cursor]
        if any(e.scope_id != state.scope_id or frame is None or timestamp is None
               or e.sequence > sequence or e.frame_id > frame or e.timestamp > timestamp for e in selected):
            self.active = None
            self.reason = "Historial ajeno o posterior al fotograma."
            return False
        if sequence != self.cursor:
            if (not selected or selected[0].sequence != self.cursor + 1 or selected[-1].sequence != sequence
                    or any(b.sequence != a.sequence + 1 for a, b in zip(selected, selected[1:]))):
                self.complete = False
            for event in selected:
                if event.type == "HAND_STARTED" and event.hand_id == state.hand_id:
                    self.hand_id, self.actions, self.seen = event.hand_id, [], set()
                    self.complete, self.last_action = True, 0
                if event.hand_id == state.hand_id and event.type.value.startswith("PLAYER_"):
                    self.last_action = event.sequence
                    if len(self.actions) < 512:
                        self.actions.append(event.model_dump(mode="json", exclude={"state_after"}))
                    else:
                        self.complete = False
            self.cursor = sequence
        return True

    def detect(self, request, *, mode, events, evidence, opponents, preflop_config, running):
        state = request.state
        self.active = None
        if not self.observe(events, request.sequence, state, request.frame_id, request.timestamp):
            return None
        hero = next((p for p in state.players if p.seat == request.poker.hero_seat), None)
        if not running or state.hand_status != "active" or hero is None or hero.folded or hero.all_in or state.current_player != hero.player_id:
            self.reason = "Esperando un turno observado de Hero."
            return None
        if (request.frame_id is None or request.timestamp is None or len(state.hero_cards) != 2
                or state.street != {0: "preflop", 3: "flop", 4: "turn", 5: "river"}.get(len(state.board))
                or any(v is None for v in (state.pot, state.small_blind, state.big_blind))
                or any(p.stack is None or p.current_bet is None for p in state.players)):
            self.reason = "Turno de Hero observado; faltan cartas o importes confirmados."
            return None
        try:
            validate_cards(state.hero_cards + state.board)
            if Decimal(hero.stack) <= 0 or not 0 < Decimal(state.small_blind) < Decimal(state.big_blind):
                raise ValueError()
            if any(v.confirmed_frame_id is not None and v.confirmed_frame_id > request.frame_id
                   or v.confirmed_timestamp is not None and v.confirmed_timestamp > request.timestamp for v in evidence.values()):
                raise ValueError()
            decision = request.decision
            if decision is not None:
                if ((decision.scope_id, decision.hand_id, decision.street, decision.board)
                        != (state.scope_id, state.hand_id, state.street, state.board)
                        or decision.frame_id > request.frame_id or decision.timestamp > request.timestamp
                        or decision.event_sequence > request.sequence or not decision.pending or decision.pending[0] != hero.seat):
                    raise ValueError()
                bets = dict(decision.bets_bb)
                if any(Decimal(p.current_bet) / Decimal(state.big_blind) != bets[p.seat]
                       for p in state.players if p.seat in bets):
                    raise ValueError()
        except (ValueError, ArithmeticError):
            self.reason = "El turno y los datos de la decisión no son coherentes."
            return None
        key = f"{state.scope_id}:{state.hand_id}:{hero.player_id}:{state.street}:{self.last_action}"
        if key in self.seen:
            self.active = key
            self.reason = "Decisión ya congelada; los cambios posteriores no la reescriben."
            return None
        snapshot = DecisionSnapshot.create(request, mode=mode, decision_key=key, actions=self.actions,
            history_complete=self.complete, evidence=evidence, opponents=opponents, preflop_config=preflop_config)
        self.seen.add(key)
        self.active = key
        self.reason = "Decisión congelada con la información disponible en este instante."
        return snapshot
