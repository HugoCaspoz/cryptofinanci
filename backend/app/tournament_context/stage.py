"""Tournament stage from declared places and an explicit risk proxy. This is not ICM."""
from math import ceil

POLICY = "bubble-factor-proxy-v1"
# Assumed cost of a lost chip relative to a won chip; illustrative, not fitted to payouts.
FACTORS = {"unknown": 1.0, "early": 1.0, "approaching_money": 1.1, "bubble": 1.3, "in_the_money": 1.15}


def stage(tournament):
    if tournament is None:
        return None
    prizes = tournament.prize_structure
    paid, remaining = (prizes[-1].last_place if prizes else None), tournament.remaining_players
    if paid is None or remaining is None:
        name = "unknown"
    elif remaining <= paid:
        name = "in_the_money"
    elif remaining <= paid + max(1, ceil(paid * .1)):
        name = "bubble"
    elif remaining <= ceil(paid * 1.5):
        name = "approaching_money"
    else:
        name = "early"
    factor = FACTORS[name]
    flat = bool(prizes) and len({p.amount for p in prizes}) == 1
    if tournament.tournament_type == "satellite" or flat:
        # Equal prizes: survival is everything before the money and nothing inside it.
        factor = {"bubble": 1.6, "approaching_money": 1.2, "in_the_money": 1.0}.get(name, factor)
    return {"policy": POLICY, "stage": name, "paid_places": paid, "remaining_players": remaining,
            "risk_factor": factor, "tournament_type": tournament.tournament_type,
            "average_stack_estimate": (tournament.starting_stack * tournament.players / remaining
                                       if remaining else None),
            "average_stack_basis": "starting_stack_x_players_over_remaining_without_rebuys"}
