"""Versioned, deliberately heuristic range likelihoods; not a calibrated solver."""
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from math import exp

from app.poker_engine.evaluator import RANKS
from app.poker_engine.range_analysis import board_scores
from app.poker_engine.ranges import expand_range

VERSION = "action-likelihood-v1"
PRIORS = {"vpip": .28, "pfr": .18, "three_bet": .07, "fold_to_three_bet": .55,
          "cbet": .55, "fold_to_cbet": .45, "aggressive_share": .5, "four_bet_proxy": .04}


def smoothed(hits, opportunities, prior, strength):
    return {"hits": hits, "opportunities": opportunities, "prior_rate": prior,
            "prior_strength": strength, "rate": (hits + strength * prior) / (opportunities + strength),
            "data_weight": opportunities / (opportunities + strength)}


def normalize(pool):
    total = sum(w for _, w in pool)
    return tuple((cards, weight / total) for cards, weight in pool) if total else ()


def hand_class(cards):
    a, b = sorted(cards, key=lambda c: RANKS.index(c[0]), reverse=True)
    return a[0] + b[0] + ("" if a[0] == b[0] else "s" if a[1] == b[1] else "o")


@lru_cache(maxsize=32)
def strengths(board):
    if board:
        scores, _ = board_scores(board)
    else:
        scores = {}
        for cards, _ in expand_range("random"):
            a, b = sorted((RANKS.index(c[0]) + 2 for c in cards), reverse=True)
            # Ordering proxy only: pair/high cards/suitedness/connectivity.
            scores[tuple(sorted(cards))] = (a + b + (16 if a == b else 0)
                                           + 3 * (cards[0][1] == cards[1][1]) - max(0, a - b - 1))
    counts = defaultdict(int)
    for score in scores.values():
        counts[score] += 1
    percentiles, below = {}, 0
    for score, count in sorted(counts.items()):
        percentiles[score] = (below + count / 2) / len(scores)
        below += count
    return {cards: percentiles[score] for cards, score in scores.items()}


def reweight(pool, rank, rate, action):
    result = []
    for cards, weight in pool:
        score = rank[cards]
        likelihood = exp((1 + 3 * (1 - rate)) * (score - 1))
        if action == "CALL":
            likelihood *= 1 - .65 * score  # Passive continuation proxy; strongest hands remain possible.
        result.append((cards, weight * likelihood))
    return normalize(result)


@dataclass(frozen=True)
class AdaptiveInput:
    scope_id: str
    hand_id: str
    board: tuple[str, ...]
    event_sequence: int
    frame_id: int
    timestamp: float
    pools: tuple  # (seat, immutable tuple of (two cards, normalized weight))
    version: str = VERSION


class AdaptiveRanges:
    def __init__(self, context, profiles):
        self.context = context
        self.board = ()
        self.history = []
        self.folded = set()
        self.stats = {s: deepcopy(profiles[s]["counts"]) | {
            "aggressive_share": [profiles[s]["aggressive"], profiles[s]["aggressive"] + profiles[s]["calls"]]}
            for s in context.seats}
        self.priors = {s: next((p.range for p in context.range_priors if p.seat == s), "random")
                       for s in context.seats}
        self.pools = {s: normalize([(tuple(sorted(c)), w) for c, w in expand_range(prior)])
                      for s, prior in self.priors.items()}
        # Same actions under generic priors only: the non-exploitative reference for strategy.
        self.neutral = dict(self.pools)

    def evidence(self, seat, action, hand):
        complement = False
        if hand["street"] == "preflop":
            raises = hand["betting"].raises
            if len(raises) == 2 and seat == raises[0] and action != "RAISE":
                stat, complement = "fold_to_three_bet", True
            elif action == "RAISE":
                stat = "pfr" if not raises else "three_bet" if len(raises) == 1 else "four_bet_proxy"
            else:
                stat = "vpip"
        elif hand["street"] == "flop" and seat == hand["aggressor"] and not hand["flop_bet_seen"]:
            stat = "cbet"
        elif (hand["street"] == "flop" and hand["cbet_actor"] is not None
              and seat != hand["cbet_actor"] and hand["betting"].high == hand["cbet_total"]):
            stat, complement = "fold_to_cbet", True
        else:
            stat = "aggressive_share"
        hits, n = self.stats[seat].get(stat, (0, 0))
        tournament = self.context.tournament
        population = tournament.population_prior if tournament else None
        use_population = population is not None and stat in {"vpip", "pfr", "three_bet"}
        prior = getattr(population, stat) if use_population else PRIORS[stat]
        strength = population.strength if use_population else self.context.prior_strength
        evidence = smoothed(hits, n, prior, strength)
        source = ({"kind": "tournament", "policy": "explicit-population-v1", "label": population.label,
                   "buy_in": str(tournament.buy_in), "currency": tournament.currency,
                   "tournament_type": tournament.tournament_type} if use_population else {"kind": "generic"})
        return evidence | {"statistic": stat, "complement": complement, "prior_source": source,
                           "prior_weight": 1 - evidence["data_weight"],
                           "continuation_rate": 1 - evidence["rate"] if complement else evidence["rate"],
                           "neutral_continuation_rate": 1 - PRIORS[stat] if complement else PRIORS[stat]}

    def act(self, event, seat, action, evidence):
        if len(self.history) >= 128:
            raise ValueError("Límite de acciones del modelo de rangos alcanzado.")
        self.history.append({"event_sequence": event.sequence, "frame_id": event.frame_id,
            "timestamp": event.timestamp, "seat": seat, "action": action, "board": list(self.board),
            "amount": event.amount, "evidence": evidence,
            "update": "neutral" if action in {"CHECK", "FOLD"} else "likelihood"})
        if action == "FOLD":
            self.folded.add(seat)
        if action in {"FOLD", "CHECK"}:
            return  # Do not equate a check with weakness or discard possible traps.
        rank = strengths(self.board)
        self.pools[seat] = reweight(self.pools[seat], rank, evidence["continuation_rate"], action)
        self.neutral[seat] = reweight(self.neutral[seat], rank, evidence["neutral_continuation_rate"], action)

    def deal(self, event):
        board = tuple(event.state_after.board)
        if board[:len(self.board)] != self.board:
            raise ValueError("El board cambió cartas ya utilizadas por el modelo de rangos.")
        self.board = board
        self.pools, self.neutral = ({s: normalize([(c, w) for c, w in pool if not set(c).intersection(board)])
                                     for s, pool in pools.items()} for pools in (self.pools, self.neutral))

    def snapshot(self, valid, finished):
        summaries = []
        for seat, pool in self.pools.items():
            masses = defaultdict(float)
            for cards, weight in pool:
                masses[hand_class(cards)] += weight
            last = next((h for h in reversed(self.history) if h["seat"] == seat), None)
            summaries.append({"seat": seat, "prior": self.priors[seat], "available_combos": len(pool),
                "effective_combos": 1 / sum(w * w for _, w in pool) if pool else 0,
                "status": "invalid" if not valid else "folded" if seat in self.folded else
                          "empty" if not pool else "finished" if finished else "active",
                "top_classes": [{"hand": h, "weight": w} for h, w in sorted(masses.items(), key=lambda p: (-p[1], p[0]))[:8]],
                "last_update": deepcopy(last)})
        return {"version": VERSION, "board": list(self.board), "prior_strength": self.context.prior_strength,
                "tournament": self.context.tournament.summary() if self.context.tournament else None,
                "historical_counts": deepcopy(self.stats), "history": deepcopy(self.history), "ranges": summaries}
