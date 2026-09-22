"""Transactional archive. PostgreSQL in Compose; SQLite for local development."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from app.feedback.store import FeedbackStore


class HandStore(FeedbackStore):
    def __init__(self, database_url=None, path="data/hands.sqlite3"):
        self.database_url, self.path = database_url, Path(path)
        self.kind = "postgresql" if database_url else "sqlite"
        self.marker = "%s" if database_url else "?"

    @contextmanager
    def connection(self):
        if self.database_url:
            import psycopg
            connection = psycopg.connect(self.database_url, connect_timeout=5,
                                        options="-c statement_timeout=5000")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        with self.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS observed_hands (
                hand_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, status TEXT NOT NULL,
                started_at DOUBLE PRECISION NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS observed_events (
                scope_id TEXT NOT NULL, sequence INTEGER NOT NULL, hand_id TEXT,
                payload TEXT NOT NULL, PRIMARY KEY(scope_id, sequence))""")
            db.execute("CREATE INDEX IF NOT EXISTS hand_events_index ON observed_events(hand_id, sequence)")
            db.execute("CREATE INDEX IF NOT EXISTS hand_scope_index ON observed_hands(scope_id, started_at)")
            db.execute("""CREATE TABLE IF NOT EXISTS preflop_results (
                id TEXT PRIMARY KEY, hand_id TEXT NOT NULL, scope_id TEXT NOT NULL, payload TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS preflop_hand_index ON preflop_results(hand_id)")
            db.execute("""CREATE TABLE IF NOT EXISTS strategy_results (
                id TEXT PRIMARY KEY, hand_id TEXT NOT NULL, scope_id TEXT NOT NULL,
                frame_id INTEGER NOT NULL, payload TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS strategy_hand_index ON strategy_results(hand_id, frame_id)")
            db.execute("""CREATE TABLE IF NOT EXISTS decision_snapshots (
                id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, hand_id TEXT NOT NULL,
                event_sequence INTEGER NOT NULL, mode TEXT NOT NULL, payload TEXT NOT NULL,
                UNIQUE(scope_id, event_sequence))""")
            db.execute("CREATE INDEX IF NOT EXISTS decision_hand_index ON decision_snapshots(hand_id, event_sequence)")
            db.execute("""CREATE TABLE IF NOT EXISTS decision_evaluations (
                snapshot_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, hand_id TEXT NOT NULL,
                action_sequence INTEGER, mode TEXT NOT NULL, input TEXT NOT NULL, result TEXT,
                UNIQUE(scope_id, action_sequence))""")
            db.execute("CREATE INDEX IF NOT EXISTS evaluation_pending_index ON decision_evaluations(mode, snapshot_id)")
            db.execute("""CREATE TABLE IF NOT EXISTS opponent_snapshots (
                scope_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)""")
            # Single backend worker: open records from a previous process are incomplete.
            rows = db.execute("SELECT hand_id, payload FROM observed_hands WHERE status='active'").fetchall()
            for hand_id, payload in rows:
                record = json.loads(payload)
                record.update(status="incomplete", reason="backend_restart")
                record["state"]["hand_status"] = "incomplete"
                db.execute(f"UPDATE observed_hands SET status='incomplete', payload={self.marker} WHERE hand_id={self.marker}",
                           (json.dumps(record), hand_id))
            self._resolve_decisions(db)  # Recover actions saved before a process interruption.
            self.initialize_feedback(db)

    def save(self, records, events, context):
        p = self.marker
        with self.connection() as db:
            for record in records:
                value = {**record, "context": context}
                db.execute(f"""INSERT INTO observed_hands(hand_id,scope_id,status,started_at,created_at,payload)
                    VALUES ({p},{p},{p},{p},{p},{p}) ON CONFLICT(hand_id) DO UPDATE SET
                    status=excluded.status, payload=excluded.payload""",
                    (record["hand_id"], record["scope_id"], record["status"], record["started_timestamp"],
                     datetime.now(timezone.utc).isoformat(), json.dumps(value)))
            for event in events:
                db.execute(f"""INSERT INTO observed_events(scope_id,sequence,hand_id,payload)
                    VALUES ({p},{p},{p},{p}) ON CONFLICT(scope_id,sequence) DO NOTHING""",
                    (event.scope_id, event.sequence, event.hand_id, event.model_dump_json()))
            for scope in {e.scope_id for e in events}:
                self._resolve_decisions(db, scope)

    def _resolve_decisions(self, db, scope=None):
        from app.decision_engine.evaluation import resolve_action
        p, cursor = self.marker, ""
        while True:
            args = [cursor] + ([scope] if scope is not None else [])
            rows = db.execute(f"""SELECT d.id,d.payload,h.status FROM decision_snapshots d
                LEFT JOIN observed_hands h ON h.hand_id=d.hand_id
                WHERE d.id>{p} {f'AND d.scope_id={p}' if scope is not None else ''}
                AND NOT EXISTS (SELECT 1 FROM decision_evaluations e WHERE e.snapshot_id=d.id)
                ORDER BY d.id LIMIT 100""", args).fetchall()
            if not rows:
                break
            for identity, payload, hand_status in rows:
                snapshot = json.loads(payload)
                events = db.execute(f"""SELECT payload FROM observed_events WHERE scope_id={p} AND sequence>{p}
                    ORDER BY sequence LIMIT 513""", (snapshot["scope_id"], snapshot["event_sequence"])).fetchall()
                link = resolve_action(snapshot, [json.loads(e[0]) for e in events[:512]],
                                      ended=hand_status in {"finished", "incomplete"}, truncated=len(events) > 512)
                if link is not None:
                    action = link["actual_event"]
                    db.execute(f"""INSERT INTO decision_evaluations(snapshot_id,scope_id,hand_id,action_sequence,mode,input)
                        VALUES ({p},{p},{p},{p},{p},{p}) ON CONFLICT(snapshot_id) DO NOTHING""",
                        (identity, snapshot["scope_id"], snapshot["hand_id"], action["sequence"] if action else None,
                         snapshot["mode"], json.dumps(link, sort_keys=True)))
            cursor = rows[-1][0]

    def next_evaluation(self, mode):
        with self.connection() as db:
            row = db.execute(f"""SELECT d.payload,e.input FROM decision_evaluations e
                JOIN decision_snapshots d ON d.id=e.snapshot_id
                WHERE e.result IS NULL AND e.mode={self.marker} ORDER BY e.hand_id,d.event_sequence LIMIT 1""",
                (mode,)).fetchone()
        return (json.loads(row[0]), json.loads(row[1])) if row else None

    def save_evaluation(self, identity, result):
        p = self.marker
        payload = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self.connection() as db:
            db.execute(f"UPDATE decision_evaluations SET result={p} WHERE snapshot_id={p} AND result IS NULL",
                       (payload, identity))
            row = db.execute(f"SELECT result FROM decision_evaluations WHERE snapshot_id={p}", (identity,)).fetchone()
            if row is None or row[0] != payload:
                raise ValueError("La evaluación no existe o ya se guardó con otros datos.")

    def get_evaluation(self, identity):
        with self.connection() as db:
            row = db.execute(f"SELECT input,result FROM decision_evaluations WHERE snapshot_id={self.marker}",
                             (identity,)).fetchone()
        if row is None:
            return {"status": "waiting", "result": None}
        return {"status": "complete" if row[1] else "pending", "result": json.loads(row[1]) if row[1] else None}

    def save_preflop(self, record):
        # Private archive: never joined into the public hand/event endpoints.
        p = self.marker
        with self.connection() as db:
            db.execute(f"""INSERT INTO preflop_results(id,hand_id,scope_id,payload)
                VALUES ({p},{p},{p},{p}) ON CONFLICT(id) DO NOTHING""",
                (record["id"], record["hand_id"], record["scope_id"], json.dumps(record)))

    def save_strategy(self, record):
        # Private archive, like preflop results: decisions stay out of the public hand API.
        p = self.marker
        with self.connection() as db:
            db.execute(f"""INSERT INTO strategy_results(id,hand_id,scope_id,frame_id,payload)
                VALUES ({p},{p},{p},{p},{p}) ON CONFLICT(id) DO NOTHING""",
                (record["id"], record["hand_id"], record["scope_id"], record["frame_id"], json.dumps(record)))

    def list_strategy(self, hand_id, limit=50):
        p = self.marker
        with self.connection() as db:
            rows = db.execute(f"SELECT payload FROM strategy_results WHERE hand_id={p} ORDER BY frame_id, id LIMIT {p}",
                              (hand_id, limit)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_decision(self, record, event):
        """Atomically store immutable input and its descriptive event; conflicting retries fail."""
        p = self.marker
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if (record["id"] != event.decision_id or record["scope_id"] != event.scope_id
                or record["hand_id"] != event.hand_id or record["event_sequence"] != event.sequence):
            raise ValueError("El snapshot y su evento no coinciden.")
        with self.connection() as db:
            db.execute(f"""INSERT INTO decision_snapshots(id,scope_id,hand_id,event_sequence,mode,payload)
                VALUES ({p},{p},{p},{p},{p},{p}) ON CONFLICT(id) DO NOTHING""",
                (record["id"], record["scope_id"], record["hand_id"], record["event_sequence"], record["mode"], payload))
            stored = db.execute(f"SELECT payload FROM decision_snapshots WHERE id={p}", (record["id"],)).fetchone()
            if stored[0] != payload:
                raise ValueError("Un snapshot guardado no puede reescribirse.")
            db.execute(f"""INSERT INTO observed_events(scope_id,sequence,hand_id,payload)
                VALUES ({p},{p},{p},{p}) ON CONFLICT(scope_id,sequence) DO NOTHING""",
                (event.scope_id, event.sequence, event.hand_id, event.model_dump_json()))
            saved = db.execute(f"SELECT payload FROM observed_events WHERE scope_id={p} AND sequence={p}",
                               (event.scope_id, event.sequence)).fetchone()
            if json.loads(saved[0]) != event.model_dump(mode="json"):
                raise ValueError("El evento de decisión ya existe con otros datos.")

    def get_decision(self, identity):
        with self.connection() as db:
            row = db.execute(f"SELECT payload FROM decision_snapshots WHERE id={self.marker}", (identity,)).fetchone()
        return json.loads(row[0]) if row else None

    def list_decisions(self, hand_id, mode, after=0, limit=20):
        p = self.marker
        with self.connection() as db:
            rows = db.execute(f"""SELECT payload FROM decision_snapshots
                WHERE hand_id={p} AND mode={p} AND event_sequence>{p} ORDER BY event_sequence LIMIT {p}""",
                (hand_id, mode, after, limit + 1)).fetchall()
        records = [json.loads(row[0]) for row in rows[:limit]]
        items = [{k: r[k] for k in ("id", "hand_id", "hero_seat", "frame_id", "timestamp", "event_sequence",
                                  "history_complete", "strategy_input_available")} | {
            "street": r["request"]["state"]["street"], "action_count": len(r["actions"])} for r in records]
        return {"items": items, "has_more": len(rows) > limit,
                "next_after": records[-1]["event_sequence"] if records else after}

    def list_hands(self, limit=20, offset=0, scope_id=None):
        p = self.marker
        where, values = (f" WHERE scope_id={p}", [scope_id]) if scope_id else ("", [])
        with self.connection() as db:
            total = db.execute("SELECT COUNT(*) FROM observed_hands" + where, values).fetchone()[0]
            rows = db.execute("SELECT payload FROM observed_hands" + where +
                              f" ORDER BY created_at DESC, hand_id DESC LIMIT {p} OFFSET {p}",
                              [*values, limit, offset]).fetchall()
        items = []
        for row in rows:
            value = json.loads(row[0])
            value.pop("state", None)
            items.append(value)
        return {"items": items, "total": total, "limit": limit, "offset": offset, "storage": self.kind}

    def save_opponents(self, record):
        p = self.marker
        with self.connection() as db:
            db.execute(f"""INSERT INTO opponent_snapshots(scope_id,revision,payload)
                VALUES ({p},{p},{p}) ON CONFLICT(scope_id) DO UPDATE SET
                revision=excluded.revision, payload=excluded.payload
                WHERE excluded.revision >= opponent_snapshots.revision""",
                (record["scope_id"], record["revision"], json.dumps(record)))

    def get_opponents(self, scope_id):
        with self.connection() as db:
            row = db.execute(f"SELECT payload FROM opponent_snapshots WHERE scope_id={self.marker}", (scope_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def get(self, hand_id, after=0, limit=100):
        p = self.marker
        with self.connection() as db:
            row = db.execute(f"SELECT payload FROM observed_hands WHERE hand_id={p}", (hand_id,)).fetchone()
            if row is None:
                return None
            events = db.execute(f"SELECT payload FROM observed_events WHERE hand_id={p} AND sequence>{p} ORDER BY sequence LIMIT {p}",
                                (hand_id, after, limit + 1)).fetchall()
        selected = [json.loads(row[0]) for row in events[:limit]]
        return {"hand": json.loads(row[0]), "events": selected, "has_more": len(events) > limit,
                "next_after": selected[-1]["sequence"] if selected else after}
