"""Generate an annotated 12-second fixture; no poker recognition is simulated."""
import argparse
from pathlib import Path

import cv2
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("sample_data/capture-demo.avi"))
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(args.output), cv2.VideoWriter_fourcc(*"MJPG"), 25, (960, 540))
    if not writer.isOpened():
        raise RuntimeError("MJPEG encoder unavailable")
    try:
        for index in range(300):
            frame = np.full((540, 960, 3), (22, 30, 24), dtype=np.uint8)
            cv2.putText(frame, "ZEROS / CAPTURE TEST", (70, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.25, (150, 220, 190), 2)
            cv2.putText(frame, f"Source time: {index / 25:05.2f}s", (70, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (220, 235, 225), 2)
            cv2.putText(frame, f"Original frame: {index + 1:03d} / 300", (70, 300), cv2.FONT_HERSHEY_SIMPLEX, .7, (140, 160, 150), 2)
            cv2.rectangle(frame, (70, 400), (890, 426), (60, 75, 65), -1)
            cv2.rectangle(frame, (70, 400), (70 + int(820 * index / 299), 426), (130, 230, 190), -1)
            writer.write(frame)
    finally:
        writer.release()
    print(args.output.resolve())


if __name__ == "__main__":
    main()

