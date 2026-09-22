"""Exact monetary arithmetic; no implicit currency or big-blind conversion."""
from decimal import Decimal, InvalidOperation


def amount(value):
    if value is None:
        return None
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Importe inválido.") from None
    if not result.is_finite() or result < 0 or result > Decimal("1e15"):
        raise ValueError("Importe fuera de los límites del motor.")
    return result


def metrics(state, hero, opponents, config):
    warnings = []
    result = dict(pot_size=None, unit=state.pot_unit, effective_stack=None,
                  effective_by_seat=[], spr=None, to_call=None, pot_odds=None,
                  required_equity=None)
    pot = amount(state.pot)
    if config.pot_includes_bets is None:
        warnings.append("Indica si el bote observado incluye las apuestas de la calle.")
        pot = None
    elif not config.pot_includes_bets and pot is not None:
        bets = [amount(p.current_bet) for p in state.players]
        if any(b is None for b in bets) or any(p.bet_unit != state.pot_unit for p in state.players):
            pot = None
            warnings.append("No se puede sumar el bote sin todas las apuestas confirmadas y en la misma unidad.")
        else:
            pot += sum(bets)
    if pot is not None:
        known_bets = [amount(p.current_bet) for p in state.players
                      if p.current_bet is not None and p.bet_unit == state.pot_unit]
        if sum(known_bets) > pot:
            warnings.append("Bote incoherente con las apuestas observadas; espera lecturas compatibles.")
            pot = None
    if pot is not None:
        result["pot_size"] = str(pot)
    else:
        warnings.append("Bote total no disponible.")
    stack = amount(hero.stack)
    stacks = [amount(p.stack) for p in opponents]
    if (stack is not None and all(s is not None for s in stacks)
            and all(p.stack_unit == hero.stack_unit for p in opponents)):
        effective = min(stack, max(stacks))
        result["effective_stack"] = str(effective)
        result["effective_unit"] = hero.stack_unit
        result["effective_by_seat"] = [{"seat": p.seat, "stack": str(min(stack, s))}
                                       for p, s in zip(opponents, stacks)]
        if pot is not None and pot > 0 and hero.stack_unit == state.pot_unit:
            result["spr"] = float(effective / pot)
    else:
        warnings.append("Stacks efectivos pendientes: faltan stacks fiables o sus unidades no coinciden.")
    if len(opponents) > 1:
        warnings.append("En multiway el stack efectivo global usa el rival que más cubre a Hero; consulta también cada asiento.")
    players = [hero, *opponents]
    bets = [amount(p.current_bet) for p in players]
    if stack is None or any(b is None for b in bets) or any(p.bet_unit != hero.stack_unit for p in players):
        warnings.append("Importe a igualar pendiente: faltan apuestas/stack fiables o hay unidades distintas.")
        return result, warnings
    outstanding = max(Decimal(0), max(bets) - bets[0])
    call = min(stack, outstanding)
    result["to_call"] = str(call)
    result["to_call_unit"] = hero.stack_unit
    if pot is None or state.pot_unit != hero.stack_unit:
        return result, warnings
    # A single pot does not establish which contributions Hero can win.
    if outstanding > stack or len(opponents) > 1 and (hero.all_in or stack == 0
            or any(p.all_in or s == 0 for p, s in zip(opponents, stacks))):
        warnings.append("Pot odds no disponibles: posible bote lateral o apuesta no cubierta; faltan contribuciones completas.")
    elif call > 0 and pot > 0:
        result["pot_odds"] = float(pot / call)
        result["required_equity"] = float(call / (pot + call))
    elif call == 0:
        warnings.append("No hay importe pendiente de igualar; no se aplica un umbral de equity para call.")
    return result, warnings
