import argparse
from pathlib import Path
import sys

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.ocr_engine.demo import render_ocr_table
from app.table_detector.store import LayoutStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("sample_data/ocr-demo.avi"))
    args = parser.parse_args()
    layout = LayoutStore().read()[0]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(args.output), cv2.VideoWriter_fourcc(*"MJPG"), 5, (1920, 1080))
    if not writer.isOpened():
        raise RuntimeError("MJPEG encoder unavailable")
    try:
        for index in range(80):
            timestamp = index / 5
            image, _ = render_ocr_table(layout, changed=timestamp >= 8, obscured=5 <= timestamp < 7)
            cv2.putText(image, f"OCR DEMO / SYNTHETIC TABLE / {timestamp:.1f}s", (50, 120),
                        cv2.FONT_HERSHEY_SIMPLEX, .8, (180, 210, 185), 2)
            writer.write(image)
    finally:
        writer.release()
    print(args.output.resolve())


if __name__ == "__main__":
    main()
