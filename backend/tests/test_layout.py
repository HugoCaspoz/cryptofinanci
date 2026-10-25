from concurrent.futures import ThreadPoolExecutor
from shutil import copyfile

import pytest
from fastapi.testclient import TestClient

from app.config import Mode, Settings
from app.main import create_app
from app.table_detector.layout import TableLayout
from app.table_detector.store import DEFAULT_LAYOUT_PATH, LayoutConflict, LayoutStore


def test_persistent_layout_path_from_environment(layout_path, monkeypatch, tmp_path):
    monkeypatch.setenv("TABLE_LAYOUT_PATH", str(layout_path))
    store = LayoutStore()
    assert store.path == layout_path
    assert store.read() == LayoutStore(layout_path).read()
    explicit = tmp_path / "explicit.json"
    assert LayoutStore(explicit).path == explicit


@pytest.fixture
def layout_path(tmp_path):
    path = tmp_path / "layout.json"
    copyfile(DEFAULT_LAYOUT_PATH, path)
    return path


def make_app(path):
    app = create_app(Settings(mode=Mode.LIVE_REAL_MONEY))
    app.state.layouts = LayoutStore(path)
    return app


@pytest.fixture
def client(layout_path):
    with TestClient(make_app(layout_path)) as client:
        yield client


def test_layout_contract_and_persistence(client, layout_path):
    response = client.get("/api/table-layout")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    layout = response.json()
    assert (layout["width"], layout["height"]) == (1920, 1080)
    assert len(layout["regions"]) + sum(len(p) for p in layout["players"]) == 29
    layout["platform"] = "Test table"
    layout["regions"]["hero_cards"]["x"] = 810
    saved = client.put("/api/table-layout", json=layout, headers={"If-Match": response.headers["etag"]})
    assert saved.status_code == 200
    assert saved.headers["etag"] != response.headers["etag"]
    with TestClient(make_app(layout_path)) as restarted:
        assert restarted.get("/api/table-layout").json() == layout


@pytest.mark.parametrize("field,value", [
    ("x", -1), ("x", 1919), ("y", 1080), ("width", 0), ("height", 1081),
    ("x", 1.5), ("x", True), ("width", "100"),
])
def test_invalid_rectangles_never_replace_file(client, layout_path, field, value):
    original = layout_path.read_bytes()
    response = client.get("/api/table-layout")
    layout = response.json()
    layout["players"][5]["stack"][field] = value
    rejected = client.put("/api/table-layout", json=layout, headers={"If-Match": response.headers["etag"]})
    assert rejected.status_code == 422
    assert layout_path.read_bytes() == original


@pytest.mark.parametrize("change", ["resolution", "missing_region", "seat_count", "extra_field", "empty_platform"])
def test_invalid_layout_schema(client, change):
    response = client.get("/api/table-layout")
    layout = response.json()
    if change == "resolution":
        layout["width"] = 960
    elif change == "missing_region":
        del layout["regions"]["blinds"]
    elif change == "seat_count":
        layout["players"].pop()
    elif change == "extra_field":
        layout["filename"] = "../../other.json"
    else:
        layout["platform"] = "  "
    assert client.put("/api/table-layout", json=layout, headers={"If-Match": response.headers["etag"]}).status_code == 422


def test_stale_tab_cannot_overwrite_saved_layout(client):
    response = client.get("/api/table-layout")
    layout = response.json()
    assert client.put("/api/table-layout", json=layout).status_code == 428
    layout["platform"] = "First writer"
    headers = {"If-Match": response.headers["etag"]}
    assert client.put("/api/table-layout", json=layout, headers=headers).status_code == 200
    layout["platform"] = "Stale writer"
    assert client.put("/api/table-layout", json=layout, headers=headers).status_code == 409
    assert client.get("/api/table-layout").json()["platform"] == "First writer"


def test_corrupt_file_is_reported_and_not_overwritten(client, layout_path):
    valid = client.get("/api/table-layout").json()
    layout_path.write_text("broken", encoding="utf-8")
    assert client.get("/api/table-layout").status_code == 503
    assert client.put("/api/table-layout", json=valid, headers={"If-Match": '"any"'}).status_code == 503
    assert layout_path.read_text() == "broken"


def test_failed_atomic_write_preserves_original(layout_path, monkeypatch):
    store = LayoutStore(layout_path)
    layout, revision = store.read()
    original = layout_path.read_bytes()
    def fail_replace(*args):
        raise PermissionError("unwritable")
    monkeypatch.setattr("app.table_detector.store.os.replace", fail_replace)
    with pytest.raises(PermissionError):
        store.save(layout, revision)
    assert layout_path.read_bytes() == original
    assert list(layout_path.parent.glob(".layout-*.tmp")) == []


def test_concurrent_edits_have_one_winner(layout_path):
    store = LayoutStore(layout_path)
    layout, revision = store.read()
    def save(name):
        proposed = TableLayout.model_validate({**layout.model_dump(), "platform": name})
        try:
            store.save(proposed, revision)
            return True
        except LayoutConflict:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, ["A", "B"])) == [False, True]
