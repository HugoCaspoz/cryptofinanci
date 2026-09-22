"""Texas Hold'em showdown ordering. Higher tuples win; no video dependencies."""
from collections import Counter

RANKS = "23456789TJQKA"
SUITS = "shdc"
DECK = tuple(rank + suit for rank in RANKS for suit in SUITS)


def validate_cards(cards):
    if len(set(cards)) != len(cards) or any(card not in DECK for card in cards):
        raise ValueError("Cartas inválidas o duplicadas.")


def straight(ranks):
    values = set(ranks)
    if 14 in values:
        values.add(1)
    return next((high for high in range(14, 5 - 1, -1)
                 if all(high - offset in values for offset in range(5))), None)


def evaluate(cards):
    """Evaluate the best five of 5–7 cards, including wheel and board-only ties."""
    validate_cards(cards)
    if not 5 <= len(cards) <= 7:
        raise ValueError("Se requieren entre cinco y siete cartas.")
    ranks = [RANKS.index(c[0]) + 2 for c in cards]
    counts = Counter(ranks)
    ordered = sorted(counts, reverse=True)
    flush = next((sorted((RANKS.index(c[0]) + 2 for c in cards if c[1] == suit), reverse=True)
                  for suit in SUITS if sum(c[1] == suit for c in cards) >= 5), None)
    if flush and (high := straight(flush)):
        return (8, high)
    quads = sorted((r for r, n in counts.items() if n == 4), reverse=True)
    if quads:
        return (7, quads[0], max(r for r in ordered if r != quads[0]))
    triples = sorted((r for r, n in counts.items() if n >= 3), reverse=True)
    pairs = sorted((r for r, n in counts.items() if n >= 2), reverse=True)
    if triples and (others := [r for r in pairs if r != triples[0]]):
        return (6, triples[0], others[0])
    if flush:
        return (5, *flush[:5])
    if high := straight(ordered):
        return (4, high)
    if triples:
        return (3, triples[0], *[r for r in ordered if r != triples[0]][:2])
    if len(pairs) >= 2:
        return (2, *pairs[:2], max(r for r in ordered if r not in pairs[:2]))
    if pairs:
        return (1, pairs[0], *[r for r in ordered if r != pairs[0]][:3])
    return (0, *ordered[:5])
