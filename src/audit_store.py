from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .utils import to_jsonable


class SQLiteAuditStore:
    SCHEMA_VERSION = "1"

    def __init__(self, path: str, *, enabled: bool = True):
        self.path = Path(path)
        self.enabled = enabled
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def open(self) -> None:
        if not self.enabled or self._conn is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA temp_store=MEMORY;")
        self._conn.execute("PRAGMA busy_timeout=3000;")
        self._create_schema()

    def close(self) -> None:
        if self._conn is None:
            return
        with self._lock:
            self._conn.commit()
            self._conn.close()
            self._conn = None

    def append_event(
        self,
        *,
        ts_ms: int,
        event: str,
        payload: dict[str, Any],
        runtime_state: str | None = None,
        run_id: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        self.open()
        payload_json = json.dumps(to_jsonable(payload), ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO audit_events (
                    ts_ms,
                    event,
                    payload_json,
                    runtime_state,
                    run_id
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (ts_ms, event, payload_json, runtime_state, run_id),
            )
            self._conn.commit()

    def _create_schema(self) -> None:
        assert self._conn is not None
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_ms INTEGER NOT NULL,
                event TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                runtime_state TEXT,
                run_id TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_audit_events_ts_ms
                ON audit_events (ts_ms);

            CREATE INDEX IF NOT EXISTS idx_audit_events_event
                ON audit_events (event);

            CREATE INDEX IF NOT EXISTS idx_audit_events_run_id
                ON audit_events (run_id);

            CREATE TABLE IF NOT EXISTS audit_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self._conn.execute(
            """
            INSERT INTO audit_meta (key, value)
            VALUES ('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (self.SCHEMA_VERSION,),
        )
        self._conn.commit()
