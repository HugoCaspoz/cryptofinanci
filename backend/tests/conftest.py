import pytest


@pytest.fixture(autouse=True)
def isolated_hand_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("HAND_DB_PATH", str(tmp_path / "hands.sqlite3"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
