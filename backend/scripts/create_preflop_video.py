"""Synthetic preflop turn, then a corroborated raise and the flop."""
import argparse
from pathlib import Path
import sys

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.card_detector.demo import render_table
from app.ocr_engine.preprocessing import region_fields
from app.action_engine.vision import render_badge
from app.table_detector.store import LayoutStore


def render_preflop_table(layout, timestamp):
    image = render_table(layout, ("As", "Ks"), ("Js", "7c", "4d") if timestamp >= 26 else ())
    bets = [50, 100, 300 if timestamp >= 20 else 0, 0, 0, 0]
    stacks = [10000 - b for b in bets]
    values = {"pot": str(sum(bets)), "blinds": "50 / 100"}
    for i, name in enumerate(("Alice", "Bruno", "Clara", "David", "Elena", "Frank")):
        values.update({f"players.{i}.nickname": name, f"players.{i}.stack": str(stacks[i]),
                       f"players.{i}.bet": str(bets[i]) if bets[i] else "0.00"})
    for key, _, r in region_fields(layout):
        roi = image[r.y:r.y+r.height, r.x:r.x+r.width]
        roi[:] = (26, 35, 27)
        cv2.putText(roi, values[key], (8, round(r.height * .73)), cv2.FONT_HERSHEY_SIMPLEX,
                    min(.8, (r.height - 10) / 28), (238, 241, 235), 2 if key == "pot" else 1, cv2.LINE_AA)
    for i, player in enumerate(layout.players):
        label = ("ACTIVE" if timestamp < 20 else "RAISE" if timestamp < 26 else None) if i == 2 else None
        r = player.action
        image[r.y:r.y+r.height, r.x:r.x+r.width] = render_badge(r.width, r.height, label)
    cv2.putText(image, "PREFLOP DEMO / HERO 3 / BUTTON 6 / NO ANTES", (50, 120),
                cv2.FONT_HERSHEY_SIMPLEX, .8, (180, 210, 185), 2)
    return image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("sample_data/preflop-demo.avi"))
    args = parser.parse_args()
    layout = LayoutStore().read()[0]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(args.output), cv2.VideoWriter_fourcc(*"MJPG"), 5, (1920, 1080))
    if not writer.isOpened():
        raise RuntimeError("MJPEG encoder unavailable")
    try:
        for index in range(30 * 5):
            writer.write(render_preflop_table(layout, index / 5))
    finally:
        writer.release()
    print(args.output.resolve())


if __name__ == "__main__":
    main()
