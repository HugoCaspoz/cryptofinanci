"""One fixed layout file, atomic saves and optimistic concurrency for browser tabs."""
import hashlib
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock

from .layout import TableLayout

DEFAULT_LAYOUT_PATH = Path(__file__).resolve().parents[2] / "table_layouts" / "platform_1920x1080.json"


class LayoutConflict(Exception):
    pass


class LayoutStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else Path(os.getenv("TABLE_LAYOUT_PATH", str(DEFAULT_LAYOUT_PATH)))
        self._lock = RLock()

    def read(self) -> tuple[TableLayout, str]:
        with self._lock:
            raw = self.path.read_bytes()
            return TableLayout.model_validate_json(raw), f'"{hashlib.sha256(raw).hexdigest()}"'

    def save(self, layout: TableLayout, expected: str) -> tuple[TableLayout, str]:
        with self._lock:
            if self.read()[1] != expected:
                raise LayoutConflict("La configuración cambió. Recarga el layout antes de guardar.")
            temporary = None
            try:
                with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                        prefix=".layout-", suffix=".tmp", delete=False) as file:
                    temporary = Path(file.name)
                    file.write(layout.model_dump_json(indent=2) + "\n")
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
            return self.read()
