"""Descriptive postflop features. No action selection or inferred ranges."""
from collections import Counter
from itertools import combinations

from .evaluator import DECK, RANKS, evaluate, straight, validate_cards
from .metrics import amount

CATEGORIES = ("high_card", "pair", "two_pair", "three_of_a_kind", "straight",
              "flush", "full_house", "four_of_a_kind", "straight_flush")
WINDOWS = [set(range(high - 4, high + 1)) for high in range(6, 15)] + [{14, 2, 3, 4, 5}]


def ranks(cards):
    return {RANKS.index(c[0]) + 2 for c in cards}


def hand_strength(hero, board):
    cards = tuple(hero) + tuple(board)
    score = evaluate(cards)
    best = [combo for combo in combinations(cards, 5) if evaluate(combo) == score]
    used = min(sum(c in hero for c in combo) for combo in best)
    detail = CATEGORIES[score[0]]
    hr, br = ranks(hero), ranks(board)
    if score[0] == 3:
        detail = "set" if len(hr) == 1 and score[1] in hr else "trips" if score[1] in hr else "board_trips"
    elif score[0] == 1:
        pair = score[1]
        if len(hr) == 1:
            detail = "overpair" if pair > max(br) else "underpair" if pair < min(br) else "pocket_pair"
        elif pair not in hr:
            detail = "board_pair"
        else:
            detail = "top_pair" if pair == max(br) else "bottom_pair" if pair == min(br) else "middle_pair"
    return {"category": CATEGORIES[score[0]], "detail": detail, "rank": list(score),
            "minimum_hole_cards_used": used, "plays_board": used == 0}


def draws(hero, board):
    cards = tuple(hero) + tuple(board)
    validate_cards(cards)
    result = {"flush": None, "straight": None, "backdoor_flush_suits": [],
              "backdoor_straight": False, "completion_cards": [], "completion_count": 0}
    if len(board) == 5:
        return result
    score = evaluate(cards)
    remaining = [c for c in DECK if c not in cards]
    suits = Counter(c[1] for c in cards)
    flush_outs = []
    for suit, count in suits.items():
        if not any(c[1] == suit for c in hero):
            continue
        if count == 4 and score[0] < 5:
            flush_outs = [c for c in remaining if c[1] == suit]
            result["flush"] = {"suit": suit, "cards": flush_outs, "count": len(flush_outs)}
        elif count == 3 and len(board) == 3 and score[0] < 5:
            result["backdoor_flush_suits"].append(suit)
    straight_outs = []
    values = ranks(cards)
    if score[0] < 4:
        for card in remaining:
            high = straight(values | ranks((card,)))
            board_high = straight(ranks(tuple(board) + (card,)))
            # A straight entirely on the board is not a Hero draw.
            if high and (not board_high or high > board_high):
                straight_outs.append(card)
        missing = ranks(straight_outs)
        if missing:
            open_ended = any(set(range(low, low + 4)) <= values
                             and (14 if low == 2 else low - 1) in missing and low + 4 in missing
                             for low in range(2, 11))
            interior = any(len(window - values) == 1 and (window - values) <= missing
                           and next(iter(window - values)) not in
                           ({14, 5} if window == {14, 2, 3, 4, 5} else {min(window), max(window)})
                           for window in WINDOWS)
            kind = "open_ended" if open_ended else "double_gutshot" if len(missing) > 1 else "gutshot" if interior else "one_ended"
            result["straight"] = {"kind": kind, "cards": straight_outs, "count": len(straight_outs)}
        elif len(board) == 3:
            result["backdoor_straight"] = any(len(window - values) == 2
                and bool((ranks(hero) - ranks(board)) & window) for window in WINDOWS)
    result["completion_cards"] = sorted(set(flush_outs + straight_outs))
    result["completion_count"] = len(result["completion_cards"])
    return result


def board_texture(board):
    counts = Counter(c[0] for c in board)
    suit_counts = Counter(c[1] for c in board)
    multiplicity = sorted(counts.values(), reverse=True)
    pairing = "quads" if multiplicity[0] == 4 else "full_house" if multiplicity[:2] == [3, 2] else "trips" if multiplicity[0] == 3 else "two_pair" if multiplicity[:2] == [2, 2] else "paired" if multiplicity[0] == 2 else "unpaired"
    values = ranks(board)
    connected = max(len(values & window) for window in WINDOWS)
    max_suit = max(suit_counts.values())
    # Explicit descriptive heuristic, not a solver's board classification.
    texture = "coordinated" if max_suit >= 3 or connected >= 3 else "semi_coordinated" if max_suit == 2 else "dry"
    return {"pairing": pairing, "suit_pattern": sorted(suit_counts.values(), reverse=True),
            "max_same_suit": max_suit, "ranks_in_straight_window": connected,
            "high_card": RANKS[max(values) - 2], "texture": texture}


def position(state, config, opponents):
    context = config.postflop_context
    if not context or context.hand_id != state.hand_id or context.button_seat is None:
        return None
    if context.button_seat not in {p.seat for p in state.players}:
        return None
    active = [p for p in state.players if p.seat == config.hero_seat] + opponents
    try:
        cannot_act = any(p.all_in or amount(p.stack) == 0 for p in active)
    except ValueError:
        return None
    if cannot_act:
        return None
    seats = [config.hero_seat, *(p.seat for p in opponents)]
    ordered = sorted(seats, key=lambda seat: (seat - context.button_seat - 1) % 6)
    index = ordered.index(config.hero_seat)
    return {"button_seat": context.button_seat, "action_order": ordered,
            "relative": "in_position" if index == len(ordered) - 1 else "out_of_position" if index == 0 else "between",
            "basis": "configured_participants_clockwise_seats"}


def bet_sizing(state, metrics):
    """Street contributions / pot at street start; never mislabel as last bet size."""
    if not metrics or metrics["pot_size"] is None:
        return None
    bets = [amount(p.current_bet) for p in state.players]
    if any(b is None for b in bets) or any(p.bet_unit != state.pot_unit for p in state.players):
        return None
    start = amount(metrics["pot_size"]) - sum(bets)
    if start <= 0:
        return None
    return {"street_start_pot": str(start), "unit": state.pot_unit,
            "basis": "total_street_contribution_over_street_start_pot",
            "by_seat": [{"seat": p.seat, "amount": str(bet), "pot_fraction": float(bet / start)}
                        for p, bet in zip(state.players, bets) if bet > 0]}


def analyze_postflop(state, config, opponents, metrics):
    return {"hand_strength": hand_strength(state.hero_cards, state.board),
            "draws": draws(state.hero_cards, state.board), "board_texture": board_texture(state.board),
            "position": position(state, config, opponents), "bet_sizing": bet_sizing(state, metrics),
            "range_comparison": None, "warnings": []}
