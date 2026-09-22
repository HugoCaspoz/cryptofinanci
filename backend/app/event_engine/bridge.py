"""Publish observed changes alongside the separately corroborated action events."""


def publish_observed(engine, previous, current, card_events, evidence, frame_id, timestamp):
    if previous != current:
        engine.emit("GAME_STATE_UPDATED", current, frame_id, timestamp)
    for event in card_events:
        field = "hero_cards" if event["type"] in {"HOLE_CARDS_DETECTED", "HERO_CARDS_CLEARED"} else "board"
        reading = evidence[field]
        confidence = reading.confidence if event["cards"] else None
        engine.emit(event["type"], current, frame_id, timestamp, confidence=confidence)
