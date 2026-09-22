from math import sqrt

STATS = ("vpip", "pfr", "three_bet", "fold_to_three_bet", "cbet", "fold_to_cbet", "wtsd")


def confidence(n):
    return "none" if n == 0 else "low" if n < 30 else "medium" if n < 100 else "high"


def statistic(hits, opportunities):
    interval = None
    if opportunities:
        p, z = hits / opportunities, 1.96
        denominator = 1 + z * z / opportunities
        middle = (p + z * z / (2 * opportunities)) / denominator
        radius = z * sqrt(p * (1 - p) / opportunities + z * z / (4 * opportunities**2)) / denominator
        interval = [max(0, middle - radius), min(1, middle + radius)]
    return {"hits": hits, "opportunities": opportunities,
            "value": hits / opportunities if opportunities else None,
            "interval_95": interval, "confidence": confidence(opportunities)}
