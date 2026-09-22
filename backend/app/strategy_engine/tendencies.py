"""Villain tendencies from statistics frozen at hand start, and the fold model they drive."""
from app.opponent_model.adaptive import PRIORS, smoothed

# Assumed population rate for the WTSD proxy; not measured data.
WTSD_PRIOR = .28
SHOWN = ("fold_to_cbet", "wtsd", "cbet", "fold_to_three_bet", "aggressive_share")


def counts(decision, seat):
    return {name: (hits, n) for name, hits, n in dict(decision.counts)[seat]}


def profile(decision, seat):
    """Smoothed rates with sample size and data weight; the same shrinkage as the adaptive ranges."""
    values = counts(decision, seat)
    return {"seat": seat, "prior_strength": decision.prior_strength, "statistics": {
        name: smoothed(*values.get(name, (0, 0)), WTSD_PRIOR if name == "wtsd" else PRIORS[name],
                       decision.prior_strength) for name in SHOWN}}


def fold_model(decision, hero_seat, villain_seat, street, to_call):
    """Exploit fold rate of the villain's whole range for one bet size, anchored at the balanced rate.

    Without observations it returns the balanced rate, so the exploit equals the baseline.
    """
    values, strength = counts(decision, villain_seat), decision.prior_strength
    cbet = street == "flop" and decision.preflop_aggressor == hero_seat and not decision.flop_bet_seen and to_call == 0
    if cbet:
        hits, n = values["fold_to_cbet"]
        return (lambda balanced: (hits + strength * balanced) / (n + strength)), {
            "statistic": "fold_to_cbet", "hits": hits, "opportunities": n, "prior_strength": strength,
            "data_weight": n / (n + strength),
            "reason": "Fold to CBet del rival, suavizado hacia la frecuencia equilibrada de cada tamaño."}
    hits, n = values["wtsd"]
    rate = smoothed(hits, n, WTSD_PRIOR, strength)["rate"]
    # Proxy: reaching showdown more often than assumed means folding less, proportionally.
    scale = (1 - rate) / (1 - WTSD_PRIOR)
    return (lambda balanced: min(.99, max(.01, balanced * scale)) if n else balanced), {
        "statistic": "wtsd_proxy", "hits": hits, "opportunities": n, "prior_strength": strength,
        "data_weight": n / (n + strength), "scale": scale,
        "reason": "Sin Fold to CBet aplicable: el WTSD suavizado escala la defensa equilibrada (proxy, sin calibrar)."}
