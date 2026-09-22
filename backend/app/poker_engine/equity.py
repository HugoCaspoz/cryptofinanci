"""Bounded, reproducible simulation of showdown share, not monetary EV."""
from itertools import accumulate
from math import log, sqrt
from random import Random

from .evaluator import DECK, evaluate, validate_cards
from .ranges import expand_range


def simulate(hero, board, ranges, samples=1000, seed=42, weighted_ranges=None):
    known = tuple(hero) + tuple(board)
    validate_cards(known)
    if len(hero) != 2 or len(board) not in (0, 3, 4, 5) or not 1 <= len(ranges) <= 5:
        raise ValueError("Se requieren dos cartas de Hero, board válido y entre uno y cinco rivales.")
    if not 100 <= samples <= 5000:
        raise ValueError("La simulación admite de 100 a 5000 muestras.")
    blocked = set(known)
    pools, summaries = [], []
    for seat, expression in ranges:
        source = expand_range(expression) if weighted_ranges is None else weighted_ranges[seat]
        pool = [(cards, weight) for cards, weight in source if not blocked.intersection(cards)]
        summaries.append({"seat": seat, "range": expression, "available_combos": len(pool)})
        if not pool:
            raise ValueError(f"El rango del asiento {seat} no tiene combos compatibles con las cartas conocidas.")
        pools.append(([p[0] for p in pool], list(accumulate(p[1] for p in pool))))
    random = Random(seed)
    wins = ties = attempts = 0
    shares = []
    # Heads-up river can enumerate every legal combo exactly (at most 990).
    exact = len(board) == 5 and len(pools) == 1
    if exact:
        cards, cumulative = pools[0]
        weights = [cumulative[0]] + [b - a for a, b in zip(cumulative, cumulative[1:])]
        hero_score = evaluate(known)
        for combo in cards:
            score = evaluate(tuple(board) + combo)
            shares.append(1.0 if hero_score > score else .5 if hero_score == score else 0.0)
        total = sum(weights)
        equity = sum(s * w for s, w in zip(shares, weights)) / total
        win = sum(w for s, w in zip(shares, weights) if s == 1) / total
        tie = sum(w for s, w in zip(shares, weights) if s == .5) / total
        interval = [equity, equity]
        attempts = len(shares)
    else:
        while len(shares) < samples and attempts < samples * 20:
            attempts += 1
            # Draw independently, then reject the WHOLE joint deal on collision.
            # Sequentially renormalizing each next range would bias joint priors.
            hands = [random.choices(cards, cum_weights=weights, k=1)[0] for cards, weights in pools]
            dealt = [c for hand in hands for c in hand]
            if len(set(dealt)) != len(dealt):
                continue
            used = blocked.union(dealt)
            runout = tuple(board) + tuple(random.sample([c for c in DECK if c not in used], 5 - len(board)))
            scores = [evaluate(tuple(hero) + runout)] + [evaluate(hand + runout) for hand in hands]
            best = max(scores)
            count = scores.count(best)
            share = 1 / count if scores[0] == best else 0.0
            shares.append(share)
            wins += share == 1
            ties += 0 < share < 1
        if len(shares) < samples:
            raise ValueError("Rangos incompatibles o demasiado solapados: no se completó la simulación acotada.")
        equity = sum(shares) / len(shares)
        win, tie = wins / len(shares), ties / len(shares)
        # Hoeffding bound avoids claiming certainty after an all-win random sample.
        radius = sqrt(log(40) / (2 * len(shares)))
        interval = [max(0, equity - radius), min(1, equity + radius)]
    return {"method": "exact_river_heads_up" if exact else "monte_carlo", "equity": equity,
            "win_probability": win, "tie_probability": tie, "samples": len(shares),
            "attempts": attempts, "seed": seed, "interval_95": interval, "ranges": summaries}
