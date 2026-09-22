"""Synthetic reference for the current layout, not a supported poker platform."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("sample_data/table-layout-demo.avi"))
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / "table_layouts" / "platform_1920x1080.json"
    layout = json.loads(path.read_text(encoding="utf-8"))
    frame = np.full((1080, 1920, 3), (20, 30, 23), dtype=np.uint8)
    cv2.ellipse(frame, (960, 540), (710, 350), 0, 0, 360, (48, 76, 52), -1)
    cv2.ellipse(frame, (960, 540), (710, 350), 0, 0, 360, (86, 115, 88), 5)
    cv2.putText(frame, "ZEROS / SYNTHETIC LAYOUT / NOT A REAL TABLE", (50, 55), cv2.FONT_HERSHEY_SIMPLEX, .8, (185, 205, 180), 2)
    entries = list(layout["regions"].items())
    for i, player in enumerate(layout["players"]):
        entries.extend((f"P{i + 1} {key}", value) for key, value in player.items())
    for name, region in entries:
        x, y, width, height = (region[key] for key in ("x", "y", "width", "height"))
        cv2.rectangle(frame, (x, y), (x + width - 1, y + height - 1), (33, 46, 35), -1)
        cv2.putText(frame, name, (x + 8, y + height // 2 + 5), cv2.FONT_HERSHEY_SIMPLEX, .5, (130, 170, 140), 1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(args.output), cv2.VideoWriter_fourcc(*"MJPG"), 5, (1920, 1080))
    if not writer.isOpened():
        raise RuntimeError("MJPEG encoder unavailable")
    try:
        for _ in range(15):
            writer.write(frame)
    finally:
        writer.release()
    print(args.output.resolve())


if __name__ == "__main__":
    main()
