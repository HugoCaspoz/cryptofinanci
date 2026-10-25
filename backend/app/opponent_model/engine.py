"""Incremental counters from confirmed actions and an explicitly anchored hand."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

from app.poker_engine.metrics import amount
from app.strategy_engine.history import replay
from app.strategy_engine.models import PriorAction
from .statistics import STATS, confidence, statistic
from .adaptive import AdaptiveInput, AdaptiveRanges
from .decision import strategy_input

ACTIONS = {"PLAYER_FOLDED": "FOLD", "PLAYER_CHECKED": "CHECK", "PLAYER_CALLED": "CALL",
           "PLAYER_BET": "BET", "PLAYER_RAISED": "RAISE", "PLAYER_ALL_IN": "ALL_IN"}


class OpponentModel:
    MAX_PROFILES = 128

    def __init__(self, scope_id):
        self.scope_id = scope_id
        self.cursor = self.revision = self.frame_id = 0
        self.timestamp = 0
        self.profiles, self.active = {}, {}
        self.identities_created = 0
        self.hand = None
        self.pending_showdowns = []
        self.coverage = "Confirma el inicio de una mano para estadísticas con contexto."
        self.last_action_hand = None

    def identities(self, state):
        changed = False
        for player in state.players:
            key = self.active.get(player.seat)
            profile = self.profiles.get(key)
            if profile and player.nickname and profile["nickname"] and player.nickname != profile["nickname"]:
                profile["active"] = False
                profile = None
                changed = True
            if profile is None:
                if len(self.profiles) >= self.MAX_PROFILES:
                    pinned = {identity for item in self.pending_showdowns for identity in item["profiles"].values()}
                    victim = next(k for k, p in self.profiles.items() if not p["active"] and k not in pinned)
                    del self.profiles[victim]
                self.identities_created += 1
                key = f"{self.scope_id}:{player.seat}:{self.identities_created}"
                profile = {"id": key, "seat": player.seat, "nickname": player.nickname,
                           "active": True, "hands": 0, "last_hand": None, "actions": 0,
                           "counts": {s: [0, 0] for s in STATS}, "aggressive": 0, "calls": 0}
                self.profiles[key] = profile
                self.active[player.seat] = key
                self.revision += 1
            elif player.nickname and profile["nickname"] is None:
                profile["nickname"] = player.nickname
                self.revision += 1
        if changed:
            self.invalidate("Cambió un nombre observado: se abrió un perfil nuevo para ese asiento.")

    def touch(self, seat, hand_id):
        profile = self.profiles[self.active[seat]]
        if profile["last_hand"] != hand_id:
            profile["hands"] += 1
            profile["last_hand"] = hand_id
        return profile

    def add(self, seat, stat, hit):
        hand = self.hand
        key = (seat, stat)
        if key not in hand["counted"]:
            self.profiles[hand["profiles"][seat]]["counts"][stat][0] += int(hit)
            self.profiles[hand["profiles"][seat]]["counts"][stat][1] += 1
            hand["counted"].add(key)

    def configure(self, context, state):
        if self.hand and self.hand["id"] == context.hand_id:
            raise ValueError("Esta mano ya tiene contexto; no se puede volver a contar ni corregir con información posterior.")
        if self.last_action_hand == context.hand_id:
            raise ValueError("Ya se observaron acciones en esta mano; confirma el contexto antes de la primera acción.")
        if state.hand_id != context.hand_id or state.hand_status != "active" or state.street != "preflop":
            raise ValueError("Se necesita la mano actual, activa y preflop.")
        players = {p.seat: p for p in state.players}
        if any(s not in players for s in context.seats):
            raise ValueError("Asiento ajeno a la mesa.")
        small, big = amount(state.small_blind), amount(state.big_blind)
        if small is None or big is None or not 0 < small < big:
            raise ValueError("Confirma ambas ciegas antes de registrar el contexto.")
        initial = replay(context, (), small / big)
        for seat, player in players.items():
            if seat not in context.seats:
                if amount(player.current_bet) not in {None, Decimal(0)}:
                    raise ValueError("Hay una apuesta en un asiento excluido; revisa los participantes.")
                continue
            expected = initial.bets.get(seat, Decimal(0)) * big
            if (amount(player.current_bet) != expected or player.bet_unit != state.blinds_unit
                    or seat in context.seats and (amount(player.stack) is None or amount(player.stack) <= 0
                    or player.stack_unit != state.blinds_unit or player.folded or player.all_in)):
                raise ValueError("El inicio debe mostrar solo SB y BB, stacks confirmados y ninguna acción previa.")
        if amount(state.pot) != small + big or state.pot_unit != state.blinds_unit:
            raise ValueError("Esta fase requiere bote inicial igual a SB + BB, sin antes ni apuestas adicionales.")
        self.identities(state)
        for seat in context.seats:
            self.touch(seat, context.hand_id)
        self.hand = {"id": context.hand_id, "context": context, "profiles": dict(self.active),
                     "small": small / big, "big": big, "unit": state.blinds_unit,
                     "actions": [], "betting": initial, "counted": set(), "valid": True,
                     "preflop_complete": False, "street": "preflop", "saw_flop": [],
                     "finished": False,
                     "aggressor": None, "cbet_actor": None, "cbet_total": None, "flop_bet_seen": False}
        self.hand["ranges"] = AdaptiveRanges(context, {s: self.profiles[self.active[s]] for s in context.seats})
        self.coverage = "Inicio confirmado; esperando acciones."
        self.revision += 1

    def invalidate(self, reason):
        if self.hand:
            self.hand["valid"] = False
        self.coverage = reason
        self.revision += 1

    def finish_preflop(self):
        hand = self.hand
        if hand["preflop_complete"]:
            return
        for seat in hand["context"].seats:
            actions = [a.action for a in hand["actions"] if a.seat == seat]
            self.add(seat, "vpip", any(a in {"CALL", "RAISE"} for a in actions))
            self.add(seat, "pfr", "RAISE" in actions)
        hand["preflop_complete"] = True
        raises = hand["betting"].raises
        hand["aggressor"] = raises[-1] if raises else None

    def preflop_action(self, event, seat, action):
        h = self.hand
        before = h["betting"]
        if action in {"BET", "ALL_IN"}:
            raise ValueError("Preflop con all-in o apuesta inicial no estándar: oportunidades suspendidas.")
        total = Decimal(event.amount) / h["big"] if event.amount is not None else None
        item = PriorAction(seat=seat, action=action, total_bb=total)
        after = replay(h["context"], [*h["actions"], item], h["small"])
        self.check_bets(event, after.bets)
        if len(before.raises) == 1 and seat != before.raises[0]:
            self.add(seat, "three_bet", action == "RAISE")
        if len(before.raises) == 2 and seat == before.raises[0]:
            self.add(seat, "fold_to_three_bet", action == "FOLD")
        h["actions"].append(item)
        h["betting"] = after
        if not after.pending:
            self.finish_preflop()

    def check_bets(self, event, bets):
        h = self.hand
        for p in event.state_after.players:
            if p.seat not in h["context"].seats:
                if amount(p.current_bet) not in {None, Decimal(0)}:
                    raise ValueError("Hay una apuesta fuera de los participantes confirmados.")
                continue
            if amount(p.current_bet) != bets.get(p.seat, Decimal(0)) * h["big"] or p.bet_unit != h["unit"]:
                raise ValueError("Las apuestas no coinciden con las acciones observadas; faltan datos de la mano.")

    def street(self, event):
        h = self.hand
        target = event.state_after.street
        expected = {"preflop": "flop", "flop": "turn", "turn": "river"}.get(h["street"])
        if target != expected or h["betting"].pending:
            raise ValueError("Cambio de calle sin cerrar la ronda anterior; no se inventan acciones ausentes.")
        if target == "flop":
            self.finish_preflop()
        remaining = [s for s in h["context"].seats if s not in h["betting"].folded]
        if len(remaining) < 2:
            raise ValueError("Board incompatible con una mano terminada por folds.")
        if target == "flop":
            h["saw_flop"] = remaining
        order = sorted(remaining, key=lambda s: (s - h["context"].button_seat - 1) % 6)
        h["street"] = target
        h["betting"] = SimpleNamespace(bets={s: Decimal(0) for s in h["context"].seats},
            folded=set(h["betting"].folded), pending=order, high=Decimal(0), increment=Decimal(1), raises=[])

    def postflop_action(self, event, seat, action):
        h, ctx = self.hand, deepcopy(self.hand["betting"])
        if not ctx.pending or ctx.pending[0] != seat or action == "ALL_IN":
            raise ValueError("Orden incompleto o all-in: no se calcula la oportunidad contextual.")
        old_high = ctx.high
        total = Decimal(event.amount) / h["big"] if event.amount is not None else None
        if action == "CHECK" and ctx.bets[seat] != ctx.high or action == "CALL" and (total != ctx.high or ctx.bets[seat] >= ctx.high):
            raise ValueError("Check o call incompatible con las apuestas anteriores.")
        if action in {"BET", "RAISE"}:
            if total < ctx.high + ctx.increment or (action == "BET") != (ctx.high == 0):
                raise ValueError("Tamaño o tipo de apuesta incompatible con la ronda.")
        ctx.pending.pop(0)
        if action == "FOLD":
            ctx.folded.add(seat)
        elif action == "CALL":
            ctx.bets[seat] = total
        elif action in {"BET", "RAISE"}:
            ctx.increment, ctx.high, ctx.bets[seat] = total - ctx.high, total, total
            order = sorted(h["context"].seats)
            at = order.index(seat)
            ctx.pending = [s for s in order[at + 1:] + order[:at] if s not in ctx.folded]
        if len(h["context"].seats) - len(ctx.folded) < 2:
            ctx.pending.clear()
        self.check_bets(event, ctx.bets)
        if h["street"] == "flop":
            if seat == h["aggressor"] and not h["flop_bet_seen"]:
                self.add(seat, "cbet", action == "BET")
                if action == "BET":
                    h["cbet_actor"], h["cbet_total"] = seat, total
            if h["cbet_actor"] is not None and seat != h["cbet_actor"] and old_high == h["cbet_total"]:
                self.add(seat, "fold_to_cbet", action == "FOLD")
            if action in {"BET", "RAISE"}:
                h["flop_bet_seen"] = True
        h["betting"] = ctx

    def raw_action(self, event, seat, action):
        profile = self.touch(seat, event.hand_id)
        profile["actions"] += 1
        if event.state_after.street not in {"flop", "turn", "river"}:
            return
        if action == "ALL_IN":
            other = [amount(p.current_bet) for p in event.state_after.players if p.seat != seat]
            units = {p.bet_unit for p in event.state_after.players}
            if any(v is None for v in other) or units != {event.unit}:
                return
            action = "RAISE" if amount(event.amount) > max(other) else "CALL"
        profile["aggressive"] += action in {"BET", "RAISE"}
        profile["calls"] += action == "CALL"

    def consume(self, event):
        if event.sequence <= self.cursor:
            return
        if (event.scope_id != self.scope_id or event.sequence != self.cursor + 1
                or event.frame_id < self.frame_id or event.timestamp < self.timestamp):
            self.invalidate("Hueco o desorden en el historial; se necesitan nuevas oportunidades confirmadas.")
            self.cursor = max(self.cursor, event.sequence)
            return
        self.cursor, self.frame_id, self.timestamp = event.sequence, event.frame_id, event.timestamp
        self.identities(event.state_after)
        if event.type == "HAND_STARTED" and self.hand and event.hand_id != self.hand["id"]:
            self.hand = None
            self.coverage = "Nueva mano: confirma su inicio para mantener estadísticas con contexto."
            self.revision += 1
        action = ACTIONS.get(event.type)
        if action:
            self.last_action_hand = event.hand_id
            player = next(p for p in event.state_after.players if p.player_id == event.player_id)
            self.raw_action(event, player.seat, action)
            self.revision += 1
        h = self.hand
        if not h or event.hand_id != h["id"]:
            return
        if event.type in {"CAPTURE_ENDED", "MANUAL_CORRECTION", "ANALYSIS_RESUMED"}:
            self.invalidate("Captura interrumpida: no se da por terminada la mano ni se infiere showdown.")
            return
        if not h["valid"]:
            return
        if h["finished"]:
            return
        try:
            if action:
                if event.state_after.street != h["street"] or player.seat not in h["context"].seats or len(h["actions"]) >= 128:
                    raise ValueError("Acción fuera del contexto confirmado.")
                if any(p.seat in h["context"].seats and not p.folded and (p.all_in or amount(p.stack) == 0)
                       for p in event.state_after.players):
                    raise ValueError("All-in observado: se suspenden las oportunidades contextuales de esta mano.")
                evidence = h["ranges"].evidence(player.seat, action, h)
                if h["street"] == "preflop":
                    self.preflop_action(event, player.seat, action)
                else:
                    self.postflop_action(event, player.seat, action)
                h["ranges"].act(event, player.seat, action, evidence)
                self.coverage = "Oportunidades actualizadas tras la última acción confirmada."
            elif event.type in {"FLOP_DEALT", "TURN_DEALT", "RIVER_DEALT"}:
                self.street(event)
                h["ranges"].deal(event)
                self.revision += 1
            elif event.type == "HAND_FINISHED":
                if h["betting"].pending:
                    raise ValueError("Final de mano sin cierre de apuestas observado; WTSD pendiente sin contabilizar.")
                remaining = [s for s in h["context"].seats if s not in h["betting"].folded]
                if h["saw_flop"]:
                    if len(remaining) == 1:
                        for seat in h["saw_flop"]:
                            self.add(seat, "wtsd", False)
                    elif h["street"] == "river":
                        self.pending_showdowns.append({"hand_id": h["id"], "remaining": remaining,
                            "saw_flop": list(h["saw_flop"]), "profiles": dict(h["profiles"])})
                        self.pending_showdowns = self.pending_showdowns[-20:]
                h["finished"] = True
                self.revision += 1
        except ValueError as exc:
            self.invalidate(str(exc))

    def confirm_showdown(self, hand_id):
        record = next((r for r in self.pending_showdowns if r["hand_id"] == hand_id), None)
        if record is None:
            raise ValueError("Esta mano no tiene un showdown pendiente de confirmar.")
        for seat in record["saw_flop"]:
            count = self.profiles[record["profiles"][seat]]["counts"]["wtsd"]
            count[0] += seat in record["remaining"]
            count[1] += 1
        self.pending_showdowns.remove(record)
        self.revision += 1

    def adaptive_input(self, state):
        h = self.hand
        if (not h or not h["valid"] or h["finished"] or state.scope_id != self.scope_id
                or state.hand_id != h["id"] or state.hand_status != "active"
                or state.street != h["street"] or tuple(state.board) != h["ranges"].board):
            return None
        return AdaptiveInput(self.scope_id, h["id"], h["ranges"].board, self.cursor, self.frame_id,
                             self.timestamp, tuple((s, p) for s, p in h["ranges"].pools.items()
                                                   if s not in h["ranges"].folded))

    def strategy_input(self, state):
        return strategy_input(self, state)

    def snapshot(self):
        profiles = []
        for p in self.profiles.values():
            stats = {s: statistic(*p["counts"][s]) for s in STATS}
            af_n = p["aggressive"] + p["calls"]
            stats["aggression_factor"] = {"value": p["aggressive"] / p["calls"] if p["calls"] else None,
                "aggressive_actions": p["aggressive"], "calls": p["calls"], "confidence": confidence(af_n),
                "reason": None if p["calls"] else "no_calls" if af_n else "no_actions"}
            profiles.append({k: p[k] for k in ("id", "seat", "nickname", "active", "hands", "actions")} | {"stats": stats})
        return {"scope_id": self.scope_id, "revision": self.revision, "event_sequence": self.cursor,
                "frame_id": self.frame_id, "timestamp": self.timestamp, "coverage": self.coverage,
                "profiles": profiles, "profile_limit": self.MAX_PROFILES,
                "identities_created": self.identities_created,
                "evicted_profiles": self.identities_created - len(self.profiles), "context": self.hand["context"].model_dump(mode="json") if self.hand else None,
                "context_valid": bool(self.hand and self.hand["valid"]),
                "adaptive": self.hand["ranges"].snapshot(self.hand["valid"], self.hand["finished"]) if self.hand else None,
                "pending_showdowns": [{"hand_id": r["hand_id"], "seats": r["remaining"]} for r in self.pending_showdowns]}
