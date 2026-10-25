"""Append-only human labels and their source image, on the existing SQL store."""
import base64
import json


class CorrectionStore:
    def initialize_corrections(self, db):
        db.execute("""CREATE TABLE IF NOT EXISTS manual_corrections (
            id TEXT PRIMARY KEY, capture_id TEXT NOT NULL, scope_id TEXT NOT NULL,
            revision INTEGER NOT NULL, payload TEXT NOT NULL, jpeg_base64 TEXT,
            UNIQUE(scope_id,revision))""")
        db.execute("CREATE INDEX IF NOT EXISTS corrections_capture_index ON manual_corrections(capture_id,revision)")

    def correction(self, identity, image=False):
        with self.connection() as db:
            row = db.execute(f"SELECT payload,jpeg_base64 FROM manual_corrections WHERE id={self.marker}", (identity,)).fetchone()
        if row is None:
            return None
        if image:
            return base64.b64decode(row[1]) if row[1] else None
        return json.loads(row[0])

    def corrections(self, capture_id, after, limit):
        p = self.marker
        with self.connection() as db:
            rows = db.execute(f"SELECT payload FROM manual_corrections WHERE capture_id={p} AND revision>{p} ORDER BY revision LIMIT {p}",
                              (capture_id, after, limit)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_correction(self, record, event, hand_record, jpeg):
        p = self.marker
        with self.connection() as db:
            db.execute(f"INSERT INTO manual_corrections(id,capture_id,scope_id,revision,payload,jpeg_base64) VALUES ({p},{p},{p},{p},{p},{p})",
                       (record["id"], record["capture_id"], record["scope_id"], record["revision"],
                        json.dumps(record, allow_nan=False), base64.b64encode(jpeg).decode("ascii") if jpeg else None))
            db.execute(f"INSERT INTO observed_events(scope_id,sequence,hand_id,payload) VALUES ({p},{p},{p},{p})",
                       (event.scope_id, event.sequence, event.hand_id, event.model_dump_json()))
            if hand_record:
                db.execute(f"UPDATE observed_hands SET payload={p} WHERE hand_id={p}",
                           (json.dumps(hand_record), hand_record["hand_id"]))
            self._resolve_decisions(db, event.scope_id)
