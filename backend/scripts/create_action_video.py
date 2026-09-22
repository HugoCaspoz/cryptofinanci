import argparse
from pathlib import Path
import sys

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.action_engine.demo import DURATION, render_action_table
from app.table_detector.store import LayoutStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("sample_data/actions-demo.avi"))
    args = parser.parse_args()
    layout = LayoutStore().read()[0]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(args.output), cv2.VideoWriter_fourcc(*"MJPG"), 5, (1920, 1080))
    if not writer.isOpened():
        raise RuntimeError("MJPEG encoder unavailable")
    try:
        for index in range(DURATION * 5):
            writer.write(render_action_table(layout, index / 5))
    finally:
        writer.release()
    print(args.output.resolve())


if __name__ == "__main__":
    main()
