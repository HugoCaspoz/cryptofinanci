"""Heads-up raise / 3bet / call / cbet / fold with a visible hand boundary."""
import argparse
from pathlib import Path
import sys

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.card_detector.demo import render_table
from app.ocr_engine.preprocessing import region_fields
from app.action_engine.vision import render_badge
from app.table_detector.store import LayoutStore

DURATION = 68


def render_opponent_table(layout, timestamp):
    ended = timestamp >= 62
    board = ("Js", "7c", "4d") if 40 <= timestamp < 62 else ()
    image = render_table(layout, () if ended else ("As", "Kh"), board)
    bets, stacks, pot = [50, 100, 0, 0, 0, 0], [9950, 9900, 10000, 10000, 10000, 10000], 150
    labels = [None] * 6
    schedule = [(14, 1, "RAISE", 300), (22, 2, "RAISE", 900), (30, 1, "CALL", 900),
                (44, 2, "BET", 300), (52, 1, "FOLD", None)]
    for start, seat, action, target in schedule:
        if start == 44 and timestamp >= 40:
            bets = [0] * 6
        index = seat - 1
        if start <= timestamp < start + 4:
            labels[index] = "ACTIVE"
        if timestamp >= start + 4:
            if target is not None:
                paid = target - bets[index]
                stacks[index] -= paid
                pot += paid
                bets[index] = target
            if timestamp < start + 8:
                labels[index] = action
    if 40 <= timestamp < 44:
        bets = [0] * 6
    if ended:
        bets, pot = [0] * 6, 0
        stacks[1] += 2100
    values = {"pot": str(pot) if pot else "0.00", "blinds": "50 / 100"}
    for i, name in enumerate(("Alice", "Bruno", "Clara", "David", "Elena", "Frank")):
        values.update({f"players.{i}.nickname": name, f"players.{i}.stack": str(stacks[i]),
                       f"players.{i}.bet": str(bets[i]) if bets[i] else "0.00"})
    for key, _, r in region_fields(layout):
        roi = image[r.y:r.y+r.height, r.x:r.x+r.width]
        roi[:] = (26, 35, 27)
        cv2.putText(roi, values[key], (8, round(r.height * .73)), cv2.FONT_HERSHEY_SIMPLEX,
                    min(.8, (r.height - 10) / 28), (238, 241, 235), 2 if key == "pot" else 1, cv2.LINE_AA)
    for player, label in zip(layout.players, labels):
        r = player.action
        image[r.y:r.y+r.height, r.x:r.x+r.width] = render_badge(r.width, r.height, label)
    cv2.putText(image, "OPPONENT DEMO / SEATS 1,2 / BUTTON 1 / NO ANTES", (50, 120),
                cv2.FONT_HERSHEY_SIMPLEX, .8, (180, 210, 185), 2)
    return image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("sample_data/opponents-demo.avi"))
    args = parser.parse_args()
    layout = LayoutStore().read()[0]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(args.output), cv2.VideoWriter_fourcc(*"MJPG"), 5, (1920, 1080))
    if not writer.isOpened():
        raise RuntimeError("MJPEG encoder unavailable")
    try:
        for index in range(DURATION * 5):
            writer.write(render_opponent_table(layout, index / 5))
    finally:
        writer.release()
    print(args.output.resolve())


if __name__ == "__main__":
    main()
