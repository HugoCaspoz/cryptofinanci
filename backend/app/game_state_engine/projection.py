"""Project stabilized observations; values may come from different source frames."""
from .models import FieldEvidence, GameState, PlayerState


def project(previous, cards, ocr):
    scope_id = previous.scope_id
    fields = ocr.fields
    players = tuple(PlayerState(
        player_id=f"{scope_id}:seat:{index + 1}", seat=index + 1,
        nickname=fields[f"players.{index}.nickname"].value,
        stack=fields[f"players.{index}.stack"].value,
        stack_unit=fields[f"players.{index}.stack"].unit,
        current_bet=fields[f"players.{index}.bet"].value,
        bet_unit=fields[f"players.{index}.bet"].unit,
    ) for index in range(6))
    board = tuple(card.code for card in cards.board.cards)
    hero = tuple(card.code for card in cards.hero.cards)
    # A confirmed empty board alone does not prove a hand is in progress.
    street = {3: "flop", 4: "turn", 5: "river"}.get(len(board), "unknown")
    if not board and hero and (cards.board.status == "empty" or previous.street == "preflop"):
        street = "preflop"
    blinds = fields["blinds"].value
    small, big = blinds.split(" / ") if blinds else (None, None)
    return GameState(scope_id=scope_id, players=players, street=street,
                     pot=fields["pot"].value, pot_unit=fields["pot"].unit,
                     board=board, hero_cards=hero, small_blind=small, big_blind=big,
                     blinds_unit=fields["blinds"].unit)


def collect_evidence(cards, ocr, previous, frame_id, timestamp):
    evidence = {}
    for key, field in ocr.fields.items():
        target = key.replace(".bet", ".current_bet")
        targets = ("small_blind", "big_blind") if key == "blinds" else (target,)
        for target in targets:
            evidence[target] = FieldEvidence(field.status, field.confidence,
                field.confirmed_frame_id, field.confirmed_timestamp, ocr.revision)
    for key, tracker in [("hero_cards", cards.hero), ("board", cards.board)]:
        old = previous.get(key)
        confirmed = tracker.status in {"confirmed", "empty"}
        evidence[key] = FieldEvidence(tracker.status,
            min((card.confidence for card in tracker.cards), default=0.0),
            frame_id if confirmed else old.confirmed_frame_id if old else None,
            timestamp if confirmed else old.confirmed_timestamp if old else None,
            cards.observation.layout_revision)
    return evidence
