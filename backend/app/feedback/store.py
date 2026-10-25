import json
from datetime import datetime, timezone

from app.config import FeedbackRelease, Mode


class FeedbackStore:
    """Mixin for HandStore: session boundaries and immutable capture policy."""
    def initialize_feedback(self, db):
        db.execute("""CREATE TABLE IF NOT EXISTS review_sessions (
            scope_id TEXT PRIMARY KEY, capture_id TEXT, mode TEXT NOT NULL, release_policy TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT)""")
        db.execute("""CREATE TABLE IF NOT EXISTS review_session_events (
            scope_id TEXT PRIMARY KEY, payload TEXT NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS review_session_mode_index ON review_sessions(mode,created_at,scope_id)")
        db.execute("UPDATE review_sessions SET status='interrupted' WHERE status='capturing'")
        # Existing archives have no release policy: migrate conservatively, never auto-unlock.
        p, cursor = self.marker, ""
        while True:
            scopes = db.execute(f"""SELECT DISTINCT h.scope_id FROM observed_hands h
                WHERE h.scope_id>{p} AND NOT EXISTS (SELECT 1 FROM review_sessions s WHERE s.scope_id=h.scope_id)
                ORDER BY h.scope_id LIMIT 100""", (cursor,)).fetchall()
            if not scopes:
                break
            for (scope,) in scopes:
                hand_cursor, first, mixed = "", None, False
                while True:
                    rows = db.execute(f"SELECT hand_id,payload FROM observed_hands WHERE scope_id={p} AND hand_id>{p} ORDER BY hand_id LIMIT 100",
                                      (scope, hand_cursor)).fetchall()
                    if not rows:
                        break
                    for _, payload in rows:
                        context = json.loads(payload).get("context", {})
                        if first is None:
                            first = context
                        elif context.get("mode") != first.get("mode"):
                            mixed = True
                    hand_cursor = rows[-1][0]
                if first is not None and not mixed and first.get("mode") in set(Mode):
                    db.execute(f"""INSERT INTO review_sessions(scope_id,capture_id,mode,release_policy,status,created_at)
                        VALUES ({p},{p},{p},{p},'interrupted',{p}) ON CONFLICT(scope_id) DO NOTHING""",
                        (scope, first.get("capture_id"), first["mode"], FeedbackRelease.SESSION_FINISHED,
                         datetime.now(timezone.utc).isoformat()))
            cursor = scopes[-1][0]

    def start_review_session(self, scope, capture_id, mode, release):
        p = self.marker
        with self.connection() as db:
            db.execute(f"""INSERT INTO review_sessions(scope_id,capture_id,mode,release_policy,status,created_at)
                VALUES ({p},{p},{p},{p},'capturing',{p})""",
                (scope, capture_id, mode, release, datetime.now(timezone.utc).isoformat()))

    def stop_review_capture(self, scope):
        with self.connection() as db:
            db.execute(f"UPDATE review_sessions SET status='stopped' WHERE scope_id={self.marker} AND status='capturing'", (scope,))

    def review_session(self, scope):
        with self.connection() as db:
            row = db.execute(f"""SELECT scope_id,capture_id,mode,release_policy,status,finished_at
                FROM review_sessions WHERE scope_id={self.marker}""", (scope,)).fetchone()
        return dict(zip(("scope_id", "capture_id", "mode", "release_policy", "status", "finished_at"), row)) if row else None

    def finish_review_session(self, scope, mode):
        p = self.marker
        with self.connection() as db:
            row = db.execute(f"SELECT mode,status FROM review_sessions WHERE scope_id={p}", (scope,)).fetchone()
            if row is None or row[0] != mode:
                raise ValueError("La sesión no pertenece al modo actual.")
            if row[1] == "finished":
                return
            if row[1] not in {"stopped", "interrupted"}:
                raise ValueError("Detén la captura antes de declarar finalizada la sesión.")
            if db.execute(f"SELECT 1 FROM observed_hands WHERE scope_id={p} AND status='active' LIMIT 1", (scope,)).fetchone():
                raise ValueError("Quedan manos activas o datos pendientes de guardar.")
            now = datetime.now(timezone.utc).isoformat()
            event = {"type": "SESSION_FINISHED", "scope_id": scope, "timestamp": now, "source": "user_confirmation"}
            db.execute(f"UPDATE review_sessions SET status='finished',finished_at={p} WHERE scope_id={p}", (now, scope))
            db.execute(f"INSERT INTO review_session_events(scope_id,payload) VALUES ({p},{p})", (scope, json.dumps(event)))

    def review_hand(self, hand_id):
        with self.connection() as db:
            row = db.execute(f"SELECT scope_id,status,payload FROM observed_hands WHERE hand_id={self.marker}", (hand_id,)).fetchone()
            if row is None:
                return None
            confirmed, cursor = False, 0
            while not confirmed:
                events = db.execute(f"SELECT sequence,payload FROM observed_events WHERE hand_id={self.marker} AND sequence>{self.marker} ORDER BY sequence LIMIT 100",
                                    (hand_id, cursor)).fetchall()
                if not events:
                    break
                confirmed = any(json.loads(e[1])["type"] == "HAND_FINISHED" for e in events)
                cursor = events[-1][0]
        return {"scope_id": row[0], "status": row[1], "mode": json.loads(row[2]).get("context", {}).get("mode"),
                "finished_confirmed": confirmed, "session": self.review_session(row[0])}
