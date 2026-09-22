"""Create a real pixel stream with a known synthetic card sequence for phase 5."""
import argparse
from pathlib import Path
import sys

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.card_detector.demo import render_table
from app.table_detector.store import LayoutStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("sample_data/cards-demo.avi"))
    args = parser.parse_args()
    layout = LayoutStore().read()[0]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(args.output), cv2.VideoWriter_fourcc(*"MJPG"), 5, (1920, 1080))
    if not writer.isOpened():
        raise RuntimeError("MJPEG encoder unavailable")
    try:
        for index in range(110):
            second = index / 5
            hero = ("As", "Jh") if 1 <= second < 17 or second >= 19 else ()
            board = ()
            if 4 <= second < 17:
                board = ("Js", "7c", "4d")
                if second >= 7:
                    board += ("2h",)
                if second >= 10:
                    board += ("Tc",)
            image = render_table(layout, hero, board)
            if 13 <= second < 14:
                for region in (layout.regions.hero_cards, layout.regions.board):
                    image[region.y:region.y + region.height, region.x:region.x + region.width] = 0
            cv2.putText(image, f"Source: {second:.1f}s / 22s", (50, 120),
                        cv2.FONT_HERSHEY_SIMPLEX, .8, (180, 210, 185), 2)
            writer.write(image)
    finally:
        writer.release()
    print(args.output.resolve())


if __name__ == "__main__":
    main()
