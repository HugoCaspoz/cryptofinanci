"""Deterministic synthetic artwork, exclusively for the Zeros demo profile."""
import cv2
import numpy as np

from .models import RANKS, SUITS

CARD_SIZE = (96, 128)
EMPTY_BGR = (45, 80, 45)


def render_card(code: str) -> np.ndarray:
    if len(code) != 2 or code[0] not in RANKS or code[1] not in SUITS:
        raise ValueError("Invalid card code")
    image = np.full((128, 96, 3), 245, np.uint8)
    color = (40, 40, 190) if code[1] in "hd" else (28, 28, 28)
    cv2.putText(image, code[0], (12, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.3, color, 3, cv2.LINE_AA)
    if code[1] == "d":
        cv2.fillConvexPoly(image, np.array([(48, 60), (70, 86), (48, 112), (26, 86)]), color)
    elif code[1] == "h":
        cv2.circle(image, (36, 77), 15, color, -1, cv2.LINE_AA)
        cv2.circle(image, (60, 77), 15, color, -1, cv2.LINE_AA)
        cv2.fillConvexPoly(image, np.array([(22, 81), (74, 81), (48, 113)]), color)
    elif code[1] == "s":
        cv2.fillConvexPoly(image, np.array([(48, 58), (23, 87), (73, 87)]), color)
        cv2.circle(image, (35, 88), 13, color, -1, cv2.LINE_AA)
        cv2.circle(image, (61, 88), 13, color, -1, cv2.LINE_AA)
        cv2.fillConvexPoly(image, np.array([(48, 88), (37, 113), (59, 113)]), color)
    else:
        for center in [(48, 74), (32, 91), (64, 91)]:
            cv2.circle(image, center, 14, color, -1, cv2.LINE_AA)
        cv2.fillConvexPoly(image, np.array([(48, 88), (38, 116), (58, 116)]), color)
    return image


def render_table(layout, hero=(), board=()) -> np.ndarray:
    image = np.full((1080, 1920, 3), (20, 30, 23), np.uint8)
    cv2.ellipse(image, (960, 540), (710, 350), 0, 0, 360, EMPTY_BGR, -1)
    cv2.putText(image, "ZEROS / SYNTHETIC CARDS / NOT A REAL TABLE", (50, 70),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (180, 210, 185), 2)
    for region, codes in [(layout.regions.hero_cards, hero), (layout.regions.board, board)]:
        roi = image[region.y:region.y + region.height, region.x:region.x + region.width]
        roi[:] = EMPTY_BGR
        height = min(116, region.height - 12)
        width = round(height * .75)
        gap = 12
        if height < 32 or len(codes) * (width + gap) - gap > region.width - 8:
            raise ValueError("Las regiones del layout son demasiado pequeñas para la demo.")
        for index, code in enumerate(codes):
            x, y = 4 + index * (width + gap), 6
            roi[y:y + height, x:x + width] = cv2.resize(render_card(code), (width, height), interpolation=cv2.INTER_AREA)
    return image
