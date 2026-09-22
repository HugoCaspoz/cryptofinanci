import subprocess

import numpy as np
import pytest

from app.capture_engine.source import Frame
from app.config import Mode, Settings
from app.game_state_engine.ocr_state import OcrState
from app.ocr_engine.engine import OcrEngine
from app.ocr_engine.models import OcrObservation, TextReading
from app.ocr_engine.parsing import parse
from app.ocr_engine.preprocessing import ROW_HEIGHT, prepare
from app.ocr_engine.tesseract import OcrFailure, TesseractReader, parse_tsv
from app.table_detector.store import LayoutStore


@pytest.mark.parametrize("text,separator,expected", [
    ("12500", ".", ("12500", None)), ("0.00", ".", ("0", None)),
    ("12,500", ".", ("12500", None)), ("12.500", ",", ("12500", None)),
    ("1,234.50", ".", ("1234.5", None)), ("1.234,50", ",", ("1234.5", None)),
    ("$0.25", ".", ("0.25", "$")), ("12.5 BB", ".", ("12.5", "BB")),
    ("1.25k", ".", ("1250", None)), ("2M", ".", ("2000000", None)),
    ("125OO", ".", None), ("", ".", None), ("All-in", ".", None),
    ("-5", ".", None), ("NaN", ".", None), ("1e3", ".", None),
    ("1,23", ".", None), ("1.234", ".", None), ("$12 BB", ".", None),
    ("1000000000001", ".", None),
])
def test_amounts_are_exact_and_follow_explicit_decimal_convention(text, separator, expected):
    assert parse(text, "amount", separator) == expected


def test_blinds_and_nicknames_are_not_ocr_corrected():
    assert parse("50 / 100", "blinds") == ("50 / 100", None)
    assert parse("0.5 / 1 BB", "blinds") == ("0.5 / 1", "BB")
    for invalid in ["100 / 50", "0 / 100", "50", "5O / 100", "$1 / €2"]:
        assert parse(invalid, "blinds") is None
    assert parse("Player_01", "nickname") == ("Player_01", None)
    assert parse("", "nickname") is None
    assert parse("x" * 33, "nickname") is None
    with pytest.raises(ValueError):
        Settings(Mode.TRAINING, ocr_decimal_separator="auto")


def send(state, index, text="12500", confidence=.95, sampled=True, status="ready", value="12500", unit=None):
    reading = TextReading("players.0.stack", "amount", text, confidence, value, unit)
    state.accept(OcrObservation(status, sampled, (reading,)), index, index * .6)
    return state.snapshot()["fields"][reading.key]


def test_three_of_five_survives_occasional_bad_characters_but_rejects_new_noise():
    state = OcrState()
    assert send(state, 1)["value"] is None
    assert send(state, 2)["value"] is None
    assert send(state, 3, "125OO", .99, value=None)["value"] is None
    result = send(state, 4)
    assert result["value"] == "12500" and result["status"] == "confirmed"
    assert send(state, 5, "9500", value="9500")["value"] == "12500"
    result = send(state, 6, "0", .5, value="0")
    assert result["value"] == "12500" and result["status"] == "unknown"
    assert result["raw_text"] == "0" and result["latest_confidence"] == .5
    assert send(state, 7, "", value=None)["value"] == "12500"
    for i in range(8, 11):
        result = send(state, i, "12000", value="12000")
    assert result["value"] == "12000"
    assert result["confirmed_frame_id"] == 10


def test_unsampled_frames_do_not_count_and_errors_interrupt_votes():
    state = OcrState()
    send(state, 1)
    for i in range(2, 50):
        send(state, i, status="not_sampled", sampled=False)
    assert state.snapshot()["last_sample_frame_id"] == 1
    assert state.snapshot()["fields"]["players.0.stack"]["value"] is None
    send(state, 50)
    send(state, 51)
    send(state, 52, status="engine_timeout")
    assert send(state, 53)["value"] is None
    assert send(state, 54)["value"] is None
    assert send(state, 55)["value"] == "12500"


def test_units_need_their_own_votes_and_history_is_bounded():
    state = OcrState()
    for i in range(1, 4):
        send(state, i, value="10", unit="$" )
    assert send(state, 4, value="10", unit="BB")["unit"] == "$"
    assert send(state, 5, value="10", unit="BB")["unit"] == "$"
    assert send(state, 6, value="10", unit="BB")["unit"] == "BB"
    for i in range(7, 1000):
        send(state, i)
    assert all(len(field.history) <= 5 for field in state.fields.values())
    assert len(state.fields) == 20
    assert OcrState().snapshot()["fields"]["pot"]["value"] is None


def test_tsv_geometry_preserves_empty_rows_and_rejects_cross_region_tokens():
    header = "level\tleft\ttop\theight\tconf\ttext\n"
    text = header + f"5\t16\t10\t30\t95\t750\n5\t16\t{ROW_HEIGHT*2+10}\t30\t90\tAlice\n"
    text += f"5\t16\t{ROW_HEIGHT-5}\t20\t99\twrong\n5\t16\t10\t20\tnan\tbad\n"
    assert parse_tsv(text, 3) == [("750", .95), ("", 0), ("Alice", .9)]


def test_timeout_and_missing_engine_are_explicit(monkeypatch):
    image = np.full((96, 1024), 255, np.uint8)
    reader = TesseractReader("missing-tesseract-for-test")
    with pytest.raises(OcrFailure, match="engine_unavailable"):
        reader.read(image, 1)
    reader.executable = "test"
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("tesseract", 2)
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(OcrFailure, match="engine_timeout"):
        reader.read(image, 1)


def test_sampling_resolution_and_calibration_are_independent_of_card_references():
    layout, revision = LayoutStore().read()
    class Reader:
        calls = 0
        def read(self, image, count):
            self.calls += 1
            return [("12500", .99)] * count
    reader = Reader()
    engine = OcrEngine(layout, revision, reader=reader)
    image = np.zeros((1080, 1920, 3), np.uint8)
    first = engine.observe(Frame(1, 0, image, 5))
    assert first.status == "ready" and len(first.readings) == 20
    assert all(r.value is None for r in first.readings)  # Empty pixels override spurious backend text.
    assert engine.observe(Frame(2, .2, image, 5)).sampled is False
    assert reader.calls == 1
    assert engine.observe(Frame(3, .6, image, 5)).sampled
    assert engine.observe(Frame(4, .8, image[:500], 5)).status == "resolution_mismatch"
    layout.platform = "Uncalibrated test"
    assert engine.observe(Frame(5, 1, image, 5)).status == "uncalibrated_layout"


def test_preprocessing_preserves_both_text_polarities():
    image = np.full((40, 200, 3), 20, np.uint8)
    import cv2
    cv2.putText(image, "12500", (5, 30), cv2.FONT_HERSHEY_SIMPLEX, .8, (240, 240, 240), 1)
    normal, active = prepare(image)
    inverted, active_inverted = prepare(255-image)
    assert active and active_inverted
    assert normal.shape == (96, 1024)
    assert (normal != inverted).mean() < .02
