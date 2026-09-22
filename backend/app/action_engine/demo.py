"""Synthetic demonstration of six actions, starting on the flop."""
import cv2

from app.card_detector.demo import render_table
from app.ocr_engine.preprocessing import region_fields
from .vision import render_badge

DURATION = 56
ACTIONS = ("CHECK", "BET", "CALL", "RAISE", "FOLD", "ALL-IN")


def render_action_table(layout, timestamp):
    image = render_table(layout, ("As", "Jh"), ("Js", "7c", "4d"))
    stacks, bets, pot = [15000] * 5 + [1000], [0] * 6, 1000
    labels = [None] * 6
    for actor, action in enumerate(ACTIONS):
        start = 4 + actor * 8
        if start <= timestamp < start + 4:
            labels[actor] = "ACTIVE"
        if timestamp >= start + 4:
            amount = {1: 500, 2: 500, 3: 1000, 5: 1000}.get(actor, 0)
            bets[actor] = amount
            stacks[actor] -= amount
            pot += amount
            if timestamp < start + 8 or actor == 5:
                labels[actor] = action
    values = {"pot": str(pot), "blinds": "50 / 100"}
    for i, name in enumerate(["Alice", "Bruno", "Clara", "David", "Elena", "Frank"]):
        values.update({f"players.{i}.nickname": name, f"players.{i}.stack": str(stacks[i]) if stacks[i] else "0.00",
                       f"players.{i}.bet": str(bets[i]) if bets[i] else "0.00"})
    for key, _, r in region_fields(layout):
        roi = image[r.y:r.y+r.height, r.x:r.x+r.width]
        roi[:] = (26, 35, 27)
        cv2.putText(roi, values[key], (8, round(r.height * .73)), cv2.FONT_HERSHEY_SIMPLEX,
                    min(.8, (r.height - 10) / 28), (238, 241, 235), 2 if key == "pot" else 1, cv2.LINE_AA)
    for player, label in zip(layout.players, labels):
        r = player.action
        image[r.y:r.y+r.height, r.x:r.x+r.width] = render_badge(r.width, r.height, label)
    return image
