import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.capture_engine.file_source import FileVideoSource
from app.capture_engine.screen_source import ScreenCaptureSource
from app.capture_engine.source import EndOfSource, SourceError
from app.main import create_app


def make_video(path, frames=40, fps=10):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (160, 90))
    assert writer.isOpened()
    for index in range(frames):
        writer.write(np.full((90, 160, 3), index * 5 % 255, dtype=np.uint8))
    writer.release()
    return path


def wait_state(client, predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get("/api/capture").json()
        if predicate(status):
            return status
        time.sleep(0.02)
    raise AssertionError(f"Capture did not reach expected state: {status}")


def test_file_sampling_uses_media_clock_without_duplicate_frames(tmp_path):
    now = [0.0]
    source = FileVideoSource(make_video(tmp_path / "sample.avi"), "sample.avi", clock=lambda: now[0])
    source.start()
    try:
        first = source.get_frame()
        assert first.frame_id == 1 and first.timestamp == 0
        assert first.fps == 5 and first.image.shape == (90, 160, 3)
        assert source.get_frame() is None
        now[0] = 0.2
        assert source.get_frame().timestamp == 0.2
        now[0] = 2.0
        frame = source.get_frame()
        assert frame.frame_id == 3 and frame.timestamp == 2.0
        assert source.duration == 4
        now[0] = 4
        with pytest.raises(EndOfSource):
            source.get_frame()
    finally:
        source.stop()


def test_screen_retains_only_latest_frame_and_times_out():
    now = [10.0]
    source = ScreenCaptureSource(clock=lambda: now[0])
    encoded = cv2.imencode(".jpg", np.zeros((90, 160, 3), dtype=np.uint8))[1].tobytes()
    source.start()
    assert source.get_frame() is None
    now[0] = 10.2
    source.push(encoded)
    source.push(encoded)
    frame = source.get_frame()
    assert frame.frame_id == 2 and frame.timestamp == pytest.approx(0.2)
    assert source.get_frame() is None
    now[0] = 26
    with pytest.raises(SourceError, match="dejó de enviar"):
        source.get_frame()
    source.stop()
    with pytest.raises(SourceError, match="detenida"):
        source.push(encoded)


def test_file_api_preview_conflict_stop_and_cleanup(tmp_path):
    data = make_video(tmp_path / "sample.avi").read_bytes()
    with TestClient(create_app()) as client:
        result = client.post("/api/capture/file", files={"file": ("sample.avi", data)}, data={"capture_fps": "5"})
        assert result.status_code == 201
        capture_id = result.json()["capture_id"]
        status = wait_state(client, lambda value: value["frame"] and value["frame"]["frame_id"] >= 2)
        assert status["state"] == "running"
        assert 0 < status["frame"]["timestamp"] < 4
        assert client.post("/api/capture/screen", json={}).status_code == 409
        assert client.post("/api/capture/wrong/stop").status_code == 409
        response = client.get(f"/api/capture/{capture_id}/frame")
        assert response.headers["content-type"] == "image/jpeg"
        assert cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR).shape == (90, 160, 3)
        assert client.get(f"/api/capture/{capture_id}/frame?after=999999").status_code == 204
        assert client.post(f"/api/capture/{capture_id}/stop").json()["state"] == "stopped"
        assert client.get(f"/api/capture/{capture_id}/frame").status_code == 204
        assert not list(client.app.state.capture.upload_dir.iterdir())


def test_file_reaches_eof_in_real_time_and_shutdown_cleans_temp(tmp_path):
    data = make_video(tmp_path / "short.avi", frames=8, fps=10).read_bytes()
    with TestClient(create_app()) as client:
        started = time.monotonic()
        response = client.post("/api/capture/file", files={"file": ("short.avi", data)})
        assert response.status_code == 201
        directory = client.app.state.capture.upload_dir
        state = wait_state(client, lambda value: value["state"] == "ended")
        assert time.monotonic() - started >= 0.7
        assert state["frame"]["frame_id"] <= 5
        assert not list(directory.iterdir())
        assert client.get(f'/api/capture/{state["capture_id"]}/frame').status_code == 200
    assert not directory.exists()


def test_screen_ingress_rejects_invalid_data_and_previous_capture():
    with TestClient(create_app()) as client:
        assert client.post("/api/capture/screen", json={"capture_fps": 0}).status_code == 422
        result = client.post("/api/capture/screen", json={"capture_fps": 10})
        capture_id = result.json()["capture_id"]
        url = f"/api/capture/{capture_id}/screen-frame"
        assert client.post(url, content=b"invalid").status_code == 422
        jpeg = cv2.imencode(".jpg", np.zeros((90, 160, 3), np.uint8))[1].tobytes()
        assert client.post(url, content=jpeg).status_code == 204
        state = wait_state(client, lambda value: value["frame"] is not None)
        assert state["frame"]["fps"] == 10
        client.post(f"/api/capture/{capture_id}/stop")
        new = client.post("/api/capture/screen", json={}).json()
        assert new["capture_id"] != capture_id
        assert client.post(url, content=jpeg).status_code == 409
        assert client.get(f"/api/capture/{capture_id}/frame").status_code == 409


def test_upload_errors_leave_no_temp_files(monkeypatch):
    with TestClient(create_app()) as client:
        for name, data, expected in [("bad.txt", b"bad", 415), ("empty.mp4", b"", 422), ("broken.mp4", b"not a video", 422)]:
            response = client.post("/api/capture/file", files={"file": (name, data)})
            assert response.status_code == expected
            assert client.get("/api/capture").json()["state"] == "idle"
            assert not list(client.app.state.capture.upload_dir.iterdir())
        monkeypatch.setattr("app.capture_engine.routes.MAX_UPLOAD_BYTES", 32)
        assert client.post("/api/capture/file", files={"file": ("large.avi", b"x" * 33)}).status_code == 413
        assert not list(client.app.state.capture.upload_dir.iterdir())


def test_app_shutdown_stops_an_active_capture():
    with TestClient(create_app()) as client:
        client.post("/api/capture/screen", json={})
        capture = client.app.state.capture
        directory = capture.upload_dir
        assert capture.state == "running"
    assert capture.state == "stopped"
    assert not directory.exists()

