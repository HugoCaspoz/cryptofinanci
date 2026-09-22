import cv2
import numpy as np

ROW_HEIGHT = 96
ROW_WIDTH = 1024


def region_fields(layout):
    fields = [("pot", "amount", layout.regions.pot), ("blinds", "blinds", layout.regions.blinds)]
    for index, player in enumerate(layout.players):
        for name in ("nickname", "stack", "bet"):
            fields.append((f"players.{index}.{name}", "nickname" if name == "nickname" else "amount", getattr(player, name)))
    return fields


def prepare(crop):
    """Contrast, scale, grayscale and Otsu threshold; white padding isolates each line."""
    strip = np.full((ROW_HEIGHT, ROW_WIDTH), 255, np.uint8)
    if crop.size == 0:
        return strip, False
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if gray.size == 0 or float(gray.std()) < 8:
        return strip, False
    gray = cv2.GaussianBlur(gray, (3, 3), 1.0)
    ratio = min(64 / gray.shape[0], (ROW_WIDTH - 32) / gray.shape[1])
    gray = cv2.resize(gray, (max(1, round(gray.shape[1] * ratio)), max(1, round(gray.shape[0] * ratio))), interpolation=cv2.INTER_CUBIC)
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    border = np.concatenate((binary[0], binary[-1], binary[:, 0], binary[:, -1]))
    if border.mean() < 127:
        binary = 255 - binary
    y = (ROW_HEIGHT - binary.shape[0]) // 2
    strip[y:y + binary.shape[0], 16:16 + binary.shape[1]] = binary
    return strip, True


def atlas(image, fields):
    rows, active = [], []
    for _, _, region in fields:
        crop = image[region.y:region.y + region.height, region.x:region.x + region.width]
        row, has_text = prepare(crop)
        rows.append(row)
        active.append(has_text)
    return np.vstack(rows), active
