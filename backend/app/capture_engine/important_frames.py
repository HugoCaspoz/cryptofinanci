"""Selective durable images; ordinary capture frames stay only in the ring buffer."""
import base64
import json


class ImportantFrameStore:
    def initialize_important_frames(self, db):
        db.execute("""CREATE TABLE IF NOT EXISTS important_frames (
            id TEXT PRIMARY KEY, capture_id TEXT NOT NULL, scope_id TEXT NOT NULL, mode TEXT,
            frame_id INTEGER NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, jpeg_base64 TEXT NOT NULL,
            UNIQUE(capture_id,frame_id,kind))""")
        db.execute("CREATE INDEX IF NOT EXISTS important_capture_index ON important_frames(capture_id,frame_id,kind)")

    def save_important_frame(self, record, jpeg):
        p = self.marker
        with self.connection() as db:
            db.execute(f"""INSERT INTO important_frames(id,capture_id,scope_id,mode,frame_id,kind,payload,jpeg_base64)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p}) ON CONFLICT(capture_id,frame_id,kind) DO NOTHING""",
                (record["id"], record["capture_id"], record["scope_id"], record["mode"], record["frame_id"],
                 record["kind"], json.dumps(record), base64.b64encode(jpeg).decode("ascii")))

    def important_frames(self, capture_id, mode, offset=0, limit=20):
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("Invalid page")
        p = self.marker
        with self.connection() as db:
            rows = db.execute(f"""SELECT payload FROM important_frames WHERE capture_id={p} AND mode={p}
                ORDER BY frame_id,kind LIMIT {p} OFFSET {p}""", (capture_id, mode, limit + 1, offset)).fetchall()
        return {"items": [json.loads(row[0]) for row in rows[:limit]], "has_more": len(rows) > limit,
                "next_offset": offset + min(len(rows), limit)}

    def important_frame(self, identity, capture_id, mode):
        p = self.marker
        with self.connection() as db:
            row = db.execute(f"SELECT jpeg_base64 FROM important_frames WHERE id={p} AND capture_id={p} AND mode={p}",
                             (identity, capture_id, mode)).fetchone()
        return base64.b64decode(row[0]) if row else None
