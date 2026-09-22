"""One-decision EV approximation and logit frequencies. A transparent heuristic, not a solver."""
from dataclasses import dataclass
from math import exp

from app.poker_engine.range_analysis import board_scores

VERSION = "ev-logit-v3"
# Share of showdown equity kept when betting continues; assumed, not measured.
REALIZATION = {"in_position": 1.0, "out_of_position": .9}
EPSILON = 1e-9


@dataclass(frozen=True)
class Spot:
    """Heads-up decision in big blinds. The pot already includes every wager on this street."""
    street: str
    pot: float
    hero_bet: float
    villain_bet: float
    hero_stack: float
    villain_stack: float
    min_raise_to: float
    position: str | None
    risk_factor: float = 1.0

    @property
    def to_call(self):
        return max(0.0, self.villain_bet - self.hero_bet)

    @property
    def realization(self):
        return 1.0 if self.street == "river" else REALIZATION.get(self.position, .95)


def candidates(spot, config):
    to_call, stack = spot.to_call, spot.hero_stack
    options = []

    def aggressive(kind, added, sizing):
        all_in = added >= stack - EPSILON
        added = min(added, stack)
        if added - to_call <= EPSILON or (not all_in and spot.hero_bet + added < spot.min_raise_to - EPSILON):
            return  # Below a legal bet/raise; a short all-in is still offered once.
        if all_in and any(o["all_in"] and o["action"] != "CALL" for o in options):
            return
        options.append({"action": "ALL_IN" if all_in else kind, "sizing_pot": sizing, "added_bb": added,
                        "total_bb": spot.hero_bet + added, "all_in": all_in})

    if to_call <= EPSILON:
        options.append({"action": "CHECK", "sizing_pot": None, "added_bb": 0.0, "total_bb": spot.hero_bet, "all_in": False})
        for size in config.bet_sizes:
            aggressive("BET", size * spot.pot, size)
    else:
        call = min(to_call, stack)
        options.append({"action": "FOLD", "sizing_pot": None, "added_bb": 0.0, "total_bb": spot.hero_bet, "all_in": False})
        options.append({"action": "CALL", "sizing_pot": None, "added_bb": call, "total_bb": spot.hero_bet + call,
                        "all_in": call >= stack - EPSILON})
        if stack > to_call + EPSILON and spot.villain_stack > EPSILON:
            target = max(config.raise_multiplier * spot.villain_bet, spot.min_raise_to)
            aggressive("RAISE", target - spot.hero_bet, None)
    return options


def called(spot, added):
    """Hero's effective chips, final pot and all-in flag when the villain calls a bet or raise."""
    wanted = added - spot.to_call
    paid = min(wanted, spot.villain_stack)
    effective = added - (wanted - paid)  # Uncovered chips are returned to Hero.
    all_in = effective >= spot.hero_stack - EPSILON or paid >= spot.villain_stack - EPSILON
    return effective, spot.pot + effective + paid, all_in


def risky(equity, pot, added, realization, factor):
    """Chips won at showdown minus chips added; lost chips cost `factor` times as much."""
    won = realization * equity
    return won * pot - added - (factor - 1) * (1 - won) * added


def split(pool, board, hero, fold):
    """Villain continues with its strongest (1 - fold) weight by current made hand (draws rank as weak).

    That choice cannot depend on Hero's cards, so the cut is made on the whole range and Hero's
    cards then remove combos from both parts: blockers move the conditional fold rate away from `fold`.
    """
    visible = set(board)
    live = [(cards, weight) for cards, weight in pool if not visible.intersection(cards)]
    total = sum(weight for _, weight in live)
    if not total:
        return None
    scores, _ = board_scores(tuple(board))
    keep, mass, strong, weak = (1 - fold) * total, 0.0, [], []
    groups = {}
    for cards, weight in live:
        groups.setdefault(scores[tuple(sorted(cards))], []).append((cards, weight))
    for score in sorted(groups, reverse=True):
        group = groups[score]
        group_mass = sum(w for _, w in group)
        fraction = min(1.0, max(0.0, keep - mass) / group_mass)
        for cards, weight in group:
            take = weight * fraction
            if take > EPSILON:
                strong.append((cards, take))
            if weight - take > EPSILON:
                weak.append((cards, weight - take))
        mass += group_mass * fraction
    blocked = set(hero)
    calls = [(cards, weight) for cards, weight in strong if not blocked.intersection(cards)]
    calling = sum(weight for _, weight in calls)
    folding = sum(weight for cards, weight in weak if not blocked.intersection(cards))
    if calling + folding <= EPSILON:
        return None
    return {"fold": folding / (calling + folding), "range_fold": fold, "strong": tuple(strong), "weak": tuple(weak),
            "continuing": tuple((cards, weight / calling) for cards, weight in calls) if calling else ()}


def logit(values, scale):
    top = max(values)
    weights = [exp((value - top) / scale) for value in values]
    total = sum(weights)
    return [weight / total for weight in weights]


def evaluate(spot, options, temperature, equity, fold_rule, pool, equity_of, board, hero):
    rows = []
    for option in options:
        row, kind = dict(option), option["action"]
        if kind == "FOLD":
            value = 0.0
        elif kind == "CHECK":
            value = spot.realization * equity * spot.pot
        elif kind == "CALL":
            added = option["added_bb"]
            pot = spot.pot - (spot.to_call - added) + added
            value = risky(equity, pot, added, 1.0 if option["all_in"] else spot.realization, spot.risk_factor)
        else:
            effective, pot, all_in = called(spot, option["added_bb"])
            balanced = effective / (spot.pot + effective)  # Break-even fold rate of a pure bluff.
            range_fold = fold_rule(balanced)
            parts = split(pool, board, hero, range_fold)
            fold = parts["fold"] if parts else range_fold
            called_equity = equity_of(parts["continuing"] if parts else ())
            value = fold * spot.pot + (1 - fold) * risky(called_equity, pot, effective,
                                                         1.0 if all_in else spot.realization, spot.risk_factor)
            row.update(fold_probability=fold, range_fold_probability=range_fold,
                       balanced_fold_probability=balanced, equity_when_called=called_equity)
        row["ev_bb"] = value
        rows.append(row)
    for row, frequency in zip(rows, logit([r["ev_bb"] for r in rows], temperature * spot.pot)):
        row["frequency"] = frequency
    summary = {}
    for row in rows:
        summary[row["action"]] = summary.get(row["action"], 0.0) + row["frequency"]
    best = max(rows, key=lambda r: r["ev_bb"])
    return {"equity": equity, "options": rows, "summary": summary,
            "highest_ev": {"action": best["action"], "total_bb": best["total_bb"], "ev_bb": best["ev_bb"]}}
