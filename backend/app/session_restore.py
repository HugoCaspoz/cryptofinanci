"""Restore an exported session to a NEW SQLite archive, never overwrite a database."""
import json
from pathlib import Path
import zipfile
from app.hand_reconstructor.store import HandStore
from app.session_archive import SCOPED, CHILDREN


def restore_session(archive_path, destination):
    destination = Path(destination)
    # Exclusive creation avoids a check/create race against an existing archive.
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb"):
        pass
    try:
        store = HandStore(path=destination)
        store.initialize()
        with zipfile.ZipFile(archive_path) as archive, store.connection() as db:
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != "zeros-session" or manifest.get("version") != 1:
                raise ValueError("Formato de exportación no compatible.")
            expected = {"manifest.json"} | {table + ".jsonl" for table in (*SCOPED, *CHILDREN)}
            if len(archive.namelist()) != len(expected) or set(archive.namelist()) != expected:
                raise ValueError("El archivo tiene tablas ausentes o adicionales.")
            count = 0
            for table in (*SCOPED, *CHILDREN):
                schema = db.execute(f"SELECT * FROM {table} LIMIT 0").description
                columns = [column[0] for column in schema]
                query = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
                with archive.open(table + ".jsonl") as rows:
                    while True:
                        line = rows.readline(16 * 1024 * 1024 + 1)
                        if not line:
                            break
                        if len(line) > 16 * 1024 * 1024:
                            raise ValueError("Un registro supera el límite admitido.")
                        record = json.loads(line)
                        if set(record) != set(columns) or table in SCOPED and record["scope_id"] != manifest["scope_id"]:
                            raise ValueError("Registro incompatible con la sesión exportada.")
                        db.execute(query, [record[column] for column in columns])
                        count += 1
        return {"scope_id": manifest["scope_id"], "records": count, "destination": str(destination)}
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
