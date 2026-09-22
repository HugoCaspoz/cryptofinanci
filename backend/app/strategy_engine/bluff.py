"""BluffAnalyzer: is Hero's best bet or raise a bluff, and does it earn more than giving up?

Reuses the EV rows of the strategy engine; adds card removal, showdown value, draws and
perceived-range context. Heuristic and heads-up only, like the model it builds on.
"""
from app.poker_engine.postflop import board_texture, draws, hand_strength
from app.poker_engine.range_analysis import compare_ranges
from .ev import EPSILON, split

VERSION = "bluff-analyzer-v1"
AGGRESSIVE = {"BET", "RAISE", "ALL_IN"}


def card_effects(parts, hero, board):
    """Share of the continuing and folding weight that each Hero card removes."""
    reference = 2 / (52 - len(board))  # What a random unseen card removes from a uniform range.
    effects = []
    for card in hero:
        shares = []
        for part in (parts["strong"], parts["weak"]):
            total = sum(w for _, w in part)
            shares.append(sum(w for cards, w in part if card in cards) / total if total else 0.0)
        effects.append({"card": card, "continuing_removed": shares[0], "folding_removed": shares[1],
                        "random_card_reference": reference})
    return ([e for e in effects if e["continuing_removed"] > e["folding_removed"] + EPSILON],
            [e for e in effects if e["folding_removed"] < reference - EPSILON])


def showdown_category(equity):
    return "high" if equity >= .5 else "medium" if equity >= .25 else "low"


def perceived_ranges(board, hero_pool, villain_pool, samples, seed):
    if not hero_pool or not villain_pool:
        return None
    try:
        result = compare_ranges(tuple(board), "perceived_hero", "villain", samples, seed, villain_pool, hero_pool)
    except ValueError:
        return None
    return {key: result[key] for key in ("hero_equity", "interval_95", "range_advantage", "nut_advantage_proxy",
                                         "method", "samples")} | {
        "hero_nuts_fraction": result["hero"]["current_nuts_fraction"],
        "villain_nuts_fraction": result["opponent"]["current_nuts_fraction"],
        "basis": "rangos percibidos por las acciones de la mano, sin las cartas reales de Hero"}


def case(spot, strategy, pool, board, hero, completion, source):
    aggressive = [o for o in strategy["options"] if o["action"] in AGGRESSIVE]
    passive = [o for o in strategy["options"] if o["action"] not in AGGRESSIVE]
    if not aggressive:
        return {"applicable": False, "bluff_candidate": False, "classification": None,
                "reason": "No hay apuesta ni subida legal en esta decisión."}
    best = max(aggressive, key=lambda o: o["ev_bb"])
    alternative = max(passive, key=lambda o: o["ev_bb"])
    parts = split(pool, board, hero, best["range_fold_probability"])
    blockers, unblockers = card_effects(parts, hero, board) if parts else ([], [])
    called = best["equity_when_called"]
    kind = ("value" if called >= .5 else "semi_bluff" if spot.street != "river" and completion else "bluff")
    gain = best["ev_bb"] - alternative["ev_bb"]
    candidate = kind != "value" and gain > 0
    fold, required = best["fold_probability"], best["balanced_fold_probability"]
    if kind == "value":
        reason = f"Apuesta de valor: {round(called * 100)} % de equity si el rival paga."
    elif candidate:
        reason = (f"{'Semifarol' if kind == 'semi_bluff' else 'Farol'} rentable: fold estimado {round(fold * 100)} % "
                  f"frente a {round(required * 100)} % necesario; mejora en {gain:.1f} BB a {alternative['action'].lower()}.")
        if blockers:
            reason += f" Bloquea combos que continúan: {', '.join(e['card'] for e in blockers)}."
    else:
        reason = (f"No compensa: rinde {-gain:.1f} BB menos que {alternative['action'].lower()}; "
                  f"fold estimado {round(fold * 100)} % frente a {round(required * 100)} % necesario.")
        if showdown_category(strategy["equity"]) != "low":
            reason += f" Conserva valor de showdown ({round(strategy['equity'] * 100)} % de equity)."
    return {"applicable": True, "bluff_candidate": candidate, "classification": kind, "reason": reason,
            "recommended_sizing": {k: best[k] for k in ("action", "sizing_pot", "added_bb", "total_bb", "all_in")},
            "estimated_fold_frequency": fold, "range_fold_frequency": best["range_fold_probability"],
            "required_fold_frequency": required, "fold_shift_from_blockers": fold - best["range_fold_probability"],
            "equity_when_called": called, "ev_bb": best["ev_bb"], "passive_action": alternative["action"],
            "passive_ev_bb": alternative["ev_bb"], "ev_gain_bb": gain,
            "commitment": best["added_bb"] / spot.hero_stack,
            # Share the strategy gives to bets/raises when they are bluffs; value bets count as zero.
            "bluff_frequency": sum(o["frequency"] for o in aggressive) if kind != "value" else 0.0,
            "blockers": blockers, "unblockers": unblockers, "fold_source": source}


class BluffAnalyzer:
    @staticmethod
    def preflop():
        return {"version": VERSION, "applicable": False, "bluff_candidate": False,
                "reason": "Esta versión analiza faroles postflop; el preflop sigue la tabla configurada."}

    def analyze(self, spot, hero, board, cases, perceived, samples, seed, tendencies, spr):
        texture, strength, hero_draws = board_texture(board), hand_strength(hero, board), draws(hero, board)
        completion = hero_draws["completion_count"]
        baseline = case(spot, *cases["baseline"], board, hero, completion, cases["baseline_source"])
        exploit = case(spot, *cases["exploit"], board, hero, completion, cases["exploit_source"])
        equity = cases["baseline"][0]["equity"]
        return {"version": VERSION, "applicable": exploit["applicable"],
                "bluff_candidate": exploit["bluff_candidate"],
                "recommended_sizing": exploit.get("recommended_sizing"),
                "estimated_fold_frequency": exploit.get("estimated_fold_frequency"),
                "blockers": exploit.get("blockers", []), "unblockers": exploit.get("unblockers", []),
                "reason": exploit["reason"],
                "showdown_value": {"equity": equity, "category": showdown_category(equity),
                                   "hand": strength["detail"], "category_basis": "equity_vs_full_neutral_range"},
                "draws": {"completion_count": completion, "flush": bool(hero_draws["flush"]),
                          "straight": hero_draws["straight"]["kind"] if hero_draws["straight"] else None,
                          "backdoor": bool(hero_draws["backdoor_flush_suits"]) or hero_draws["backdoor_straight"]},
                "board_texture": texture, "spr": spr, "player_tendencies": tendencies,
                "range_advantage": {"baseline": perceived_ranges(board, *perceived["baseline"], samples, seed),
                                    "exploit": perceived_ranges(board, *perceived["exploit"], samples, seed)},
                "baseline_strategy": baseline, "exploit_strategy": exploit}
