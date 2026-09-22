"""Heads-up range comparison using only the current board and supplied priors."""
from functools import lru_cache
from itertools import accumulate, combinations
from math import log, sqrt
from random import Random

from .evaluator import DECK, evaluate, validate_cards
from .ranges import expand_range


@lru_cache(maxsize=32)
def board_scores(board):
    available = [c for c in DECK if c not in board]
    scores = {tuple(sorted(combo)): evaluate(board + combo) for combo in combinations(available, 2)}
    return scores, max(scores.values())


@lru_cache(maxsize=32)
def compare_ranges(board, hero_range, opponent_range, samples=1000, seed=42, weighted_opponent=None,
                   weighted_hero=None):
    validate_cards(board)
    if len(board) not in (3, 4, 5) or not 100 <= samples <= 5000:
        raise ValueError("La comparación requiere un board postflop y de 100 a 5000 muestras.")
    scores, nuts = board_scores(board)
    sources = (expand_range(hero_range) if weighted_hero is None else weighted_hero,
               expand_range(opponent_range) if weighted_opponent is None else weighted_opponent)
    pools = [[(tuple(sorted(cards)), weight) for cards, weight in source
              if tuple(sorted(cards)) in scores]
             for source in sources]
    if any(not pool for pool in pools):
        raise ValueError("Un rango de estudio no tiene combos compatibles con el board.")
    distributions = []
    for pool in pools:
        total = sum(weight for _, weight in pool)
        distributions.append({"available_combos": len(pool),
                              "current_nuts_fraction": sum(weight for cards, weight in pool if scores[cards] == nuts) / total})
    exact = len(board) == 5 and len(pools[0]) * len(pools[1]) <= 25000
    share_sum = total_weight = completed = attempts = 0
    if exact:
        for hero, hw in pools[0]:
            for rival, rw in pools[1]:
                attempts += 1
                if set(hero).intersection(rival):
                    continue
                weight = hw * rw
                share_sum += weight * (1 if scores[hero] > scores[rival] else .5 if scores[hero] == scores[rival] else 0)
                total_weight += weight
                completed += 1
        if not completed:
            raise ValueError("Los rangos de estudio no permiten un reparto conjunto sin colisiones.")
        equity = share_sum / total_weight
        interval = [equity, equity]
    else:
        random = Random(seed)
        sampling = [([cards for cards, _ in pool], list(accumulate(w for _, w in pool))) for pool in pools]
        while completed < samples and attempts < samples * 20:
            attempts += 1
            hero, rival = [random.choices(cards, cum_weights=weights, k=1)[0] for cards, weights in sampling]
            if set(hero).intersection(rival):
                continue
            used = set(board + hero + rival)
            runout = board + tuple(random.sample([c for c in DECK if c not in used], 5 - len(board)))
            hs, rs = evaluate(hero + runout), evaluate(rival + runout)
            share_sum += 1 if hs > rs else .5 if hs == rs else 0
            completed += 1
        if completed != samples:
            raise ValueError("Rangos de estudio incompatibles o demasiado solapados; simulación acotada incompleta.")
        equity = share_sum / completed
        radius = sqrt(log(40) / (2 * completed))
        interval = [max(0, equity - radius), min(1, equity + radius)]
    difference = distributions[0]["current_nuts_fraction"] - distributions[1]["current_nuts_fraction"]
    return {"method": "exact_river_joint" if exact else "monte_carlo_joint", "samples": completed,
            "attempts": attempts, "seed": seed, "hero_equity": equity, "opponent_equity": 1 - equity,
            "interval_95": interval,
            "range_advantage": "hero" if interval[0] > .5 else "opponent" if interval[1] < .5 else "undetermined",
            "hero_range": hero_range, "opponent_range": opponent_range,
            "hero": distributions[0], "opponent": distributions[1],
            "nut_advantage_proxy": "hero" if difference > 1e-12 else "opponent" if difference < -1e-12 else "equal",
            "nuts_rank": list(nuts), "blockers": "board_only",
            "nuts_basis": "absolute_current_nuts_density_each_board_conditioned_range"}
