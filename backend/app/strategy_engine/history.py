"""Preflop betting order and full-raise history, in exact BB units."""
from dataclasses import dataclass
from decimal import Decimal


def positions(seats, button):
    seats = sorted(seats)
    start = seats.index(button)
    clockwise = seats[start:] + seats[:start]
    if len(seats) == 2:
        return {clockwise[0]: "BTN/SB", clockwise[1]: "BB"}, clockwise, clockwise[0], clockwise[1]
    labels = ["BTN", "SB", "BB"] + {3: [], 4: ["CO"], 5: ["HJ", "CO"], 6: ["UTG", "HJ", "CO"]}[len(seats)]
    return dict(zip(clockwise, labels)), clockwise[3:] + clockwise[:3], clockwise[1], clockwise[2]


@dataclass
class BettingContext:
    positions: dict
    bets: dict
    folded: set
    pending: list
    high: Decimal
    increment: Decimal
    raises: list
    callers: int


def replay(config, actions, small_blind_bb):
    labels, order, small, big = positions(config.seats, config.button_seat)
    bets = {seat: Decimal(0) for seat in config.seats}
    bets[small], bets[big] = small_blind_bb, Decimal(1)
    context = BettingContext(labels, bets, set(), list(order), Decimal(1), Decimal(1), [], 0)
    for item in actions:
        if not context.pending or item.seat != context.pending[0]:
            raise ValueError("El historial no respeta el orden preflop; confirma las acciones anteriores.")
        seat, action = item.seat, item.action
        if action == "ALL_IN":
            raise ValueError("Historial con all-in: las reaperturas y botes laterales quedan fuera de esta fase.")
        if action == "CHECK" and bets[seat] != context.high:
            raise ValueError("Check incompatible con una apuesta pendiente.")
        if action == "CALL" and (item.total_bb != context.high or bets[seat] >= context.high):
            raise ValueError("Call incompatible con la apuesta máxima del historial.")
        context.pending.pop(0)
        if action == "FOLD":
            context.folded.add(seat)
        elif action == "CALL":
            bets[seat] = item.total_bb
            context.callers += 1
        elif action == "RAISE":
            if item.total_bb < context.high + context.increment:
                raise ValueError("La subida anterior no alcanza el mínimo legal de una subida completa.")
            context.increment = item.total_bb - context.high
            context.high = bets[seat] = item.total_bb
            context.raises.append(seat)
            context.callers = 0
            at = order.index(seat)
            context.pending = [s for s in order[at + 1:] + order[:at] if s not in context.folded]
        if len(config.seats) - len(context.folded) < 2:
            context.pending.clear()
    return context
