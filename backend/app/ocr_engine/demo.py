"""Synthetic OCR reference frames; labels are never supplied to the OCR engine."""
import cv2

from app.card_detector.demo import render_table
from .preprocessing import region_fields


def render_ocr_table(layout, changed=False, obscured=False):
    image = render_table(layout, ("As", "Jh"), ("Js", "7c", "4d"))
    values = {"pot": "1500" if changed else "750", "blinds": "50 / 100"}
    names = ["Alice", "Bruno", "Clara", "David", "Elena", "Frank"]
    for index, name in enumerate(names):
        values.update({f"players.{index}.nickname": name,
                       f"players.{index}.stack": "12000" if changed and index == 0 else str(12500 + index * 1000),
                       f"players.{index}.bet": "500" if changed and index == 0 else "0.00"})
    for key, _, r in region_fields(layout):
        roi = image[r.y:r.y+r.height, r.x:r.x+r.width]
        roi[:] = (26, 35, 27)
        text = values[key]
        if obscured and key in {"pot", "players.0.stack"}:
            continue
        scale = min(.8, (r.height - 10) / 28)
        cv2.putText(roi, text, (8, round(r.height * .73)), cv2.FONT_HERSHEY_SIMPLEX,
                    scale, (238, 241, 235), 1, cv2.LINE_AA)
    return image, values
