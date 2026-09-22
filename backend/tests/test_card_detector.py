import json
from shutil import copyfile

import cv2
import numpy as np
import pytest

from app.card_detector.demo import EMPTY_BGR, render_card, render_table
from app.card_detector.detector import CardDetector
from app.card_detector.models import RANKS, SUITS
from app.card_detector.templates import TemplateDeck
from app.capture_engine.source import Frame
from app.table_detector.store import DEFAULT_LAYOUT_PATH, LayoutStore
from app.vision_engine import VisionEngine


@pytest.fixture(scope="module")
def detector():
    return CardDetector(TemplateDeck.load())


@pytest.mark.parametrize("code", [r + s for r in RANKS for s in SUITS])
def test_full_deck_survives_resizing_noise_and_jpeg(detector, code):
    image = cv2.resize(render_card(code), (74, 98), interpolation=cv2.INTER_AREA)
    noise = np.random.default_rng(23).normal(0, 1.5, image.shape)
    image = np.clip(image.astype(float) + noise, 0, 255).astype(np.uint8)
    image = cv2.imdecode(cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 65])[1], cv2.IMREAD_COLOR)
    card = detector.classify(image)
    assert card is not None and card.code == code
    assert detector.MIN_SCORE <= card.confidence <= 1


def test_blank_unknown_and_ambiguous_regions_are_not_guessed(detector):
    empty = np.full((130, 620, 3), EMPTY_BGR, np.uint8)
    assert detector.read(empty, {3, 4, 5}).status == "empty"
    for value in [0, 245, (180, 30, 30)]:
        assert detector.read(np.full_like(empty, value), {3, 4, 5}).status == "unknown"
    deck = TemplateDeck.load()
    # A deliberately ambiguous reference pack cannot choose arbitrarily between equal matches.
    deck.templates[1] = (deck.templates[1][0], deck.templates[0][1].copy())
    assert CardDetector(deck).classify(render_card(deck.templates[0][0])) is None


def test_detector_rejects_partial_and_repeated_cards(detector):
    layout = LayoutStore().read()[0]
    for hero in [("As",), ("As", "As")]:
        image = render_table(layout, hero)
        r = layout.regions.hero_cards
        assert detector.read(image[r.y:r.y+r.height, r.x:r.x+r.width], {2}).status == "unknown"
    image = render_table(layout, ("As", "Jh"))
    r = layout.regions.hero_cards
    assert detector.read(image[r.y:r.y+r.height, r.x+15:r.x+r.width], {2}).status == "unknown"


def test_vision_uses_pixels_and_rejects_cross_region_duplicates():
    layout = LayoutStore().read()[0]
    vision = VisionEngine(LayoutStore())
    image = render_table(layout, ("As", "Jh"), ("Js", "7c", "4d"))
    observed = vision.observe(Frame(7, 1.4, image, 5))
    assert observed.cards.status == "ready" and observed.recognition_available
    assert [c.code for c in observed.cards.hero.cards] == ["As", "Jh"]
    assert [c.code for c in observed.cards.board.cards] == ["Js", "7c", "4d"]
    duplicate = vision.observe(Frame(8, 1.6, render_table(layout, ("As", "Jh"), ("As", "7c", "4d")), 5))
    assert duplicate.cards.status == "duplicate_cards"
    assert duplicate.cards.hero.status == "unknown"
    small = vision.observe(Frame(9, 1.8, cv2.resize(image, (960, 540)), 5))
    assert small.cards.status == "resolution_mismatch" and not small.recognition_available


def write_layout(path, **updates):
    data = json.loads(DEFAULT_LAYOUT_PATH.read_text())
    data.update(updates)
    path.write_text(json.dumps(data), encoding="utf-8")
    return LayoutStore(path)


def test_layout_is_frozen_and_invalid_profiles_do_not_fall_back_to_demo(tmp_path):
    path = tmp_path / "layout.json"
    copyfile(DEFAULT_LAYOUT_PATH, path)
    store = LayoutStore(path)
    vision = VisionEngine(store)
    old_revision = vision.revision
    layout, revision = store.read()
    layout.platform = "Different platform"
    store.save(layout, revision)
    assert vision.status == "ready" and vision.revision == old_revision
    assert VisionEngine(store).status == "platform_mismatch"
    assert VisionEngine(store, str(tmp_path / "missing")).status == "templates_unavailable"
    path.write_text("invalid", encoding="utf-8")
    assert VisionEngine(store).status == "layout_unavailable"


def test_external_reference_pack_requires_calibration_and_all_52_images(tmp_path):
    directory = tmp_path / "deck"
    directory.mkdir()
    (directory / "manifest.json").write_text(json.dumps({"name": "Test reference pack", "platform": "Test", "empty_bgr": EMPTY_BGR}))
    for rank in RANKS:
        for suit in SUITS:
            cv2.imwrite(str(directory / f"{rank}{suit}.png"), render_card(rank + suit))
    store = write_layout(tmp_path / "layout.json", platform="Test", calibrated=False)
    assert VisionEngine(store, str(directory)).status == "uncalibrated_layout"
    store = write_layout(tmp_path / "layout.json", platform="Test", calibrated=True)
    vision = VisionEngine(store, str(directory))
    assert vision.status == "ready" and not vision.demo
    (directory / "As.png").unlink()
    assert VisionEngine(store, str(directory)).status == "templates_unavailable"
