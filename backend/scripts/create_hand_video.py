"""Two hands, a brief occlusion and an incomplete ending, played as a real stream."""
from pathlib import Path
import sys
import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.card_detector.demo import render_table
from app.table_detector.store import LayoutStore


def main():
    layout = LayoutStore().read()[0]
    path = Path("sample_data/hands-demo.avi")
    path.parent.mkdir(exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 5, (1920, 1080))
    if not writer.isOpened():
        raise RuntimeError("MJPEG encoder unavailable")
    try:
        for i in range(170):
            t = i / 5
            hero = ("As", "Jh") if 4 <= t < 18 else ("Qh", "Qs") if t >= 24 else ()
            board = ("Js", "7c", "4d") if 9 <= t < 18 else ("Ah", "9d", "2c") if t >= 29 else ()
            image = render_table(layout, hero, board)
            if 13 <= t < 14:
                for region in (layout.regions.hero_cards, layout.regions.board):
                    image[region.y:region.y+region.height, region.x:region.x+region.width] = 0
            cv2.putText(image, f"Hands demo {t:.1f}s / 34s", (50, 120), cv2.FONT_HERSHEY_SIMPLEX, .8, (180, 210, 185), 2)
            writer.write(image)
    finally:
        writer.release()
    print(path.resolve())


if __name__ == "__main__":
    main()
