import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.capture_engine.screen_source import CameraCaptureSource
from app.capture_engine.source import SourceError
from app.main import create_app
from test_capture import wait_state


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "camera.sqlite"))
    with TestClient(create_app()) as current:
        yield current


def jpeg():
    return cv2.imencode(".jpg", np.full((180, 320, 3), 90, np.uint8))[1].tobytes()


def test_camera_source_latest_only_timeout_and_cleanup():
    now = [0.]
    source = CameraCaptureSource(clock=lambda: now[0])
    assert source.kind == "camera"
    source.start()
    source.push(jpeg())
    now[0] = .4
    source.push(jpeg())
    assert source.get_frame().frame_id == 2
    assert source.get_frame() is None
    now[0] = 16
    with pytest.raises(SourceError, match="cámara dejó de enviar"):
        source.get_frame()
    source.stop()
    with pytest.raises(SourceError, match="detenida"):
        source.push(jpeg())


def test_camera_api_preview_source_isolation_stop_and_previous_capture(client):
    response = client.post("/api/capture/camera", json={"capture_fps": 10, "sampling_mode": "adaptive"})
    assert response.status_code == 201
    capture = response.json()
    assert capture["source"] == "camera"
    identity = capture["capture_id"]
    assert client.post("/api/capture/screen", json={}).status_code == 409
    assert client.post(f"/api/capture/{identity}/screen-frame", content=jpeg()).status_code == 409
    assert client.post(f"/api/capture/{identity}/camera-frame", content=jpeg()).status_code == 204
    status = wait_state(client, lambda s: s["frame"] is not None)
    assert status["frame"]["width"] == 320
    assert status["pipeline"]["sampling"]["mode"] == "adaptive"
    assert client.get(f"/api/capture/{identity}/frame").headers["content-type"] == "image/jpeg"
    assert client.post(f"/api/capture/{identity}/stop").status_code == 200
    assert client.post(f"/api/capture/{identity}/camera-frame", content=jpeg()).status_code == 409
    second = client.post("/api/capture/screen", json={}).json()["capture_id"]
    assert client.post(f"/api/capture/{second}/camera-frame", content=jpeg()).status_code == 409
    assert client.post(f"/api/capture/{identity}/camera-frame", content=jpeg()).status_code == 409


@pytest.mark.parametrize("data,status", [(b"", 422), (b"invalid", 422), (b"x" * (4 * 1024 * 1024 + 1), 413)])
def test_camera_invalid_frames_are_rejected(client, data, status):
    identity = client.post("/api/capture/camera", json={}).json()["capture_id"]
    assert client.post(f"/api/capture/{identity}/camera-frame", content=data).status_code == status


@pytest.mark.parametrize("body", [{"capture_fps": 0}, {"capture_fps": 16}, {"sampling_mode": "invalid"}])
def test_camera_configuration_validation(client, body):
    assert client.post("/api/capture/camera", json=body).status_code == 422
