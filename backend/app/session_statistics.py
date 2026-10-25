"""Conservative Hero statistics from complete, legally replayable preflop rounds."""
import json
from app.opponent_model.models import HandContext
from app.opponent_model.statistics import statistic
from app.poker_engine.metrics import amount
from app.strategy_engine.history import replay
from app.strategy_engine.models import PriorAction
from app.decision_engine.evaluation import ACTIONS


def preflop_statistics(store, db, hand, context, hero):
    if not context or hero not in context.seats:
        return None
    cursor, previous, initial, actions, three_bet = 0, None, None, [], None
    while True:
        rows = db.execute(f"SELECT sequence,payload FROM observed_events WHERE hand_id={store.marker} AND sequence>{store.marker} ORDER BY sequence LIMIT 100", (hand, cursor)).fetchall()
        if not rows:
            return None
        for sequence, payload in rows:
            event = json.loads(payload)
            state = event["state_after"]
            if previous is not None and sequence != previous + 1:
                return None
            previous = sequence
            kind = event["type"]
            if any(p["seat"] not in context.seats and amount(p.get("current_bet")) not in {None, 0} for p in state["players"]):
                return None
            if kind in {"MANUAL_CORRECTION", "ANALYSIS_RESUMED", "CAPTURE_ENDED", "HAND_FINISHED"} or state["street"] != "preflop":
                return None
            if initial is None:
                if kind.startswith("PLAYER_"):
                    return None
                small, big = amount(state.get("small_blind")), amount(state.get("big_blind"))
                if small is None or big is None or not 0 < small < big:
                    continue
                betting = replay(context, (), small / big)
                if amount(state.get("pot")) != small + big or state.get("pot_unit") != state.get("blinds_unit"):
                    continue
                if any(amount(player.get("current_bet")) != betting.bets.get(player["seat"], 0) * big
                       or player.get("bet_unit") != state.get("blinds_unit")
                       or player["seat"] in context.seats and (player.get("folded") or player.get("all_in")
                           or amount(player.get("stack")) is None or amount(player.get("stack")) <= 0)
                       for player in state["players"] if player["seat"] in context.seats):
                    continue
                initial = small / big, big, state["blinds_unit"]
            action = ACTIONS.get(kind)
            if not action:
                continue
            if action in {"ALL_IN", "BET"} or len(actions) >= 128:
                return None
            small, big, unit = initial
            player = next((p for p in state["players"] if p["player_id"] == event.get("player_id")), None)
            if not player or any(p.get("all_in") for p in state["players"] if p["seat"] in context.seats):
                return None
            seat = player["seat"]
            total = amount(event.get("amount"))
            if action in {"CALL", "RAISE"} and (total is None or event.get("unit") != unit):
                return None
            try:
                before = replay(context, actions, small)
                item = PriorAction(seat=seat, action=action, total_bb=total / big if action in {"CALL", "RAISE"} else None)
                after = replay(context, [*actions, item], small)
            except ValueError:
                return None
            if any(amount(p.get("current_bet")) != after.bets.get(p["seat"], 0) * big or p.get("bet_unit") != unit for p in state["players"] if p["seat"] in context.seats):
                return None
            if seat == hero and len(before.raises) == 1 and seat != before.raises[0] and three_bet is None:
                three_bet = action == "RAISE"
            actions.append(item)
            if not after.pending:
                hero_actions = [a.action for a in actions if a.seat == hero]
                return {"vpip": any(a in {"CALL", "RAISE"} for a in hero_actions), "pfr": "RAISE" in hero_actions,
                        "three_bet": three_bet}
        cursor = rows[-1][0]


def hero_statistics(store, scope, mode):
    p, cursor, known, played, complete = store.marker, "", 0, 0, 0
    counts = {key: [0, 0] for key in ("vpip", "pfr", "three_bet")}
    with store.connection() as db:
        while True:
            hands = db.execute(f"SELECT hand_id FROM observed_hands WHERE scope_id={p} AND hand_id>{p} ORDER BY hand_id LIMIT 100", (scope, cursor)).fetchall()
            if not hands:
                break
            for (hand,) in hands:
                seats, cards, context, decision_cursor = set(), False, None, ""
                for seat, cards_seen in db.execute(f"SELECT seat,cards_seen FROM hand_heroes WHERE hand_id={p}", (hand,)).fetchall():
                    seats.add(seat)
                    cards = cards or bool(cards_seen)
                row = db.execute(f"SELECT payload FROM hand_preflop_contexts WHERE hand_id={p} AND scope_id={p} AND mode={p}", (hand, scope, mode)).fetchone()
                if row:
                    context = HandContext.model_validate_json(row[0])
                while True:
                    rows = db.execute(f"SELECT id,payload FROM decision_snapshots WHERE hand_id={p} AND mode={p} AND id>{p} ORDER BY id LIMIT 100", (hand, mode, decision_cursor)).fetchall()
                    if not rows:
                        break
                    for _, payload in rows:
                        frozen = json.loads(payload)
                        seats.add(frozen["hero_seat"])
                        cards = cards or len(frozen["request"]["state"].get("hero_cards", [])) == 2
                        candidate = (frozen.get("opponents") or {}).get("context")
                        if candidate and candidate.get("hand_id") == hand:
                            try:
                                validated = HandContext.model_validate(candidate)
                                if context is not None and context != validated:
                                    seats.add(None)  # Conflicting historical assignments cannot be merged.
                                context = validated
                            except ValueError:
                                pass
                    decision_cursor = rows[-1][0]
                if len(seats) != 1:
                    continue
                known += 1
                played += int(cards)
                stats = preflop_statistics(store, db, hand, context, next(iter(seats)))
                if stats is None:
                    continue
                complete += 1
                for key, value in stats.items():
                    if value is not None:
                        counts[key][0] += int(value)
                        counts[key][1] += 1
            cursor = hands[-1][0]
    return {"hands_played": played if known else None, "hero_identified_hands": known,
            "complete_preflop_hands": complete, **{key: statistic(*value) for key, value in counts.items()},
            "reason": "Manos jugadas: cartas de Hero conocidas en el archivo; cobertura parcial. Porcentajes: solo rondas preflop completas, legales y con inicio confirmado."}
