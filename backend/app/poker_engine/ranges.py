"""Explicit weighted combo priors; never inferred from future actions."""
from itertools import combinations
import math
import re

from .evaluator import DECK, RANKS


def expand_range(expression: str):
    """random, AA, AK, AKs, AKo, AsKh; optional positive weight per combo."""
    if expression.strip() == "random":
        return tuple((pair, 1.0) for pair in combinations(DECK, 2))
    combos = {}
    for term in expression.split(","):
        parts = term.strip().split(":")
        if len(parts) > 2:
            raise ValueError("Peso de rango inválido.")
        token = parts[0]
        try:
            weight = float(parts[1]) if len(parts) == 2 else 1.0
        except ValueError:
            raise ValueError("Peso de rango inválido.") from None
        if not math.isfinite(weight) or not 0 < weight <= 100:
            raise ValueError("El peso debe ser mayor que cero y como máximo 100.")
        if re.fullmatch(r"[2-9TJQKA][shdc][2-9TJQKA][shdc]", token):
            selected = [tuple(sorted((token[:2], token[2:])))]
            if selected[0][0] == selected[0][1]:
                raise ValueError("Un combo no puede repetir una carta.")
        elif re.fullmatch(r"[2-9TJQKA]{2}[so]?", token):
            a, b, suffix = token[0], token[1], token[2:]
            if RANKS.index(a) < RANKS.index(b) or a == b and suffix:
                raise ValueError("Usa pares sin sufijo y el rango mayor primero: AA, AKs.")
            selected = [tuple(sorted(pair)) for pair in combinations(DECK, 2)
                        if sorted(c[0] for c in pair) == sorted((a, b))
                        and (not suffix or (pair[0][1] == pair[1][1]) == (suffix == "s"))]
        else:
            raise ValueError("Rango inválido: usa random, AA, AKs, AKo o AsKh, separados por comas.")
        for pair in selected:
            if pair in combos:
                raise ValueError("El rango contiene combos repetidos o solapados.")
            combos[pair] = weight
    return tuple(combos.items())
