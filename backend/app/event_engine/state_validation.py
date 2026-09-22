"""Structural validation, without claiming to validate poker action legality."""
import re


def validate_state(state):
    if len(state.players) != 6 or {p.seat for p in state.players} != set(range(1, 7)):
        raise ValueError("Se requieren seis asientos únicos.")
    ids = {p.player_id for p in state.players}
    if len(ids) != 6 or not all(ids):
        raise ValueError("Identificadores de asiento inválidos.")
    if state.current_player is not None and state.current_player not in ids:
        raise ValueError("Turno de un jugador desconocido.")
    if state.button_position is not None and state.button_position not in range(1, 7):
        raise ValueError("Posición del botón inválida.")
    cards = state.hero_cards + state.board
    if len(set(cards)) != len(cards) or any(not re.fullmatch(r"[2-9TJQKA][shdc]", c) for c in cards):
        raise ValueError("Cartas inválidas o duplicadas.")
    if len(state.hero_cards) not in {0, 2} or len(state.board) not in {0, 3, 4, 5}:
        raise ValueError("Número de cartas inválido.")
    street = {3: "flop", 4: "turn", 5: "river"}.get(len(state.board))
    if (street is not None and state.street != street
            or street is None and state.street not in {"unknown", "preflop"}):
        raise ValueError("Calle incompatible con las cartas.")
    amounts = [state.pot, state.small_blind, state.big_blind]
    amounts.extend(value for p in state.players for value in (p.stack, p.current_bet))
    if any(value is not None and not re.fullmatch(r"(?:0|[1-9]\d*)(?:\.\d{1,2})?", value) for value in amounts):
        raise ValueError("Los importes deben ser decimales exactos no negativos.")
    return state
