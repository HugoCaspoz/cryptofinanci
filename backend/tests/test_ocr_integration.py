import shutil
import time

import cv2
import pytest
from fastapi.testclient import TestClient

from app.capture_engine.source import Frame
from app.main import create_app
from app.ocr_engine.demo import render_ocr_table
from app.ocr_engine.engine import OcrEngine
from app.table_detector.store import LayoutStore

pytestmark = pytest.mark.skipif(not shutil.which("tesseract"), reason="Requiere Tesseract real; ejecutar con Dockerfile.test")


@pytest.mark.parametrize("changed", [False, True])
def test_real_tesseract_reads_all_twenty_fields_from_compressed_pixels(changed):
    layout, revision = LayoutStore().read()
    image, _ = render_ocr_table(layout, changed)
    image = cv2.imdecode(cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])[1], cv2.IMREAD_COLOR)
    result = OcrEngine(layout, revision).observe(Frame(1, 0, image, 5))
    assert result.status == "ready"
    fields = {r.key: r for r in result.readings}
    assert fields["pot"].value == ("1500" if changed else "750")
    assert fields["blinds"].value == "50 / 100"
    for index, name in enumerate(["Alice", "Bruno", "Clara", "David", "Elena", "Frank"]):
        assert fields[f"players.{index}.nickname"].value == name
        assert fields[f"players.{index}.stack"].value == ("12000" if index == 0 and changed else str(12500 + index * 1000))
        assert fields[f"players.{index}.bet"].value == ("500" if index == 0 and changed else "0")
    assert all(r.confidence >= .80 for r in result.readings)


def test_real_pipeline_keeps_amounts_on_unknown_frames_and_resets_new_capture(tmp_path):
    layout, _ = LayoutStore().read()
    path = tmp_path / "ocr.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 5, (1920, 1080))
    assert writer.isOpened()
    for obscure in [False, True]:
        image, _ = render_ocr_table(layout, obscured=obscure)
        for _ in range(15):
            writer.write(image)
    writer.release()
    with TestClient(create_app()) as client:
        response = client.post("/api/capture/file", files={"file": ("ocr.avi", path.read_bytes())})
        assert response.status_code == 201
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = client.get("/api/capture").json()
            if state["state"] in {"ended", "error"}:
                break
            time.sleep(.05)
        assert state["state"] == "ended"
        fields = state["observation_state"]["ocr"]["fields"]
        assert fields["pot"]["value"] == "750" and fields["pot"]["status"] == "unknown"
        assert fields["players.0.stack"]["value"] == "12500"
        assert fields["players.0.stack"]["status"] == "unknown"
        assert fields["players.0.nickname"]["value"] == "Alice"
        assert state["observation_state"]["cards"]["event_count"] == 2
        game = state["observation_state"]["game_state"]
        assert game["pot"] == "750" and game["street"] == "flop"
        assert game["players"][0]["stack"] == "12500"
        assert game["evidence"]["pot"]["status"] == "unknown"
        assert game["hero_cards"] == ["As", "Jh"]
        assert game["small_blind"] == "50" and game["big_blind"] == "100"
        assert state["pipeline"]["queue_high_watermark"] <= 2
        client.post(f'/api/capture/{state["capture_id"]}/stop')
        next_capture = client.post("/api/capture/screen", json={}).json()
        assert next_capture["observation_state"]["ocr"]["fields"]["pot"]["value"] is None
        assert next_capture["observation_state"]["game_state"]["revision"] == 0
        assert next_capture["observation_state"]["game_state"]["scope_id"] != game["scope_id"]
