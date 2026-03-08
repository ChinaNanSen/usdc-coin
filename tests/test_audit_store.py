import json
import sqlite3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.audit_store import SQLiteAuditStore
from src.executor import JournalWriter


def test_journal_writer_writes_jsonl_and_sqlite(tmp_path):
    jsonl_path = tmp_path / "audit.jsonl"
    sqlite_path = tmp_path / "audit.db"

    runtime_state = "QUOTING"
    store = SQLiteAuditStore(str(sqlite_path), enabled=True)
    store.open()
    journal = JournalWriter(
        str(jsonl_path),
        sqlite_store=store,
        runtime_state_getter=lambda: runtime_state,
        run_id="test-run",
    )

    journal.append("test_event", {"foo": "bar", "count": 1})
    store.close()

    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "test_event"
    assert payload["runtime_state"] == "QUOTING"
    assert payload["run_id"] == "test-run"
    assert payload["payload"]["foo"] == "bar"

    conn = sqlite3.connect(str(sqlite_path))
    row = conn.execute(
        "SELECT event, runtime_state, run_id, payload_json FROM audit_events"
    ).fetchone()
    meta = conn.execute(
        "SELECT value FROM audit_meta WHERE key='schema_version'"
    ).fetchone()
    conn.close()

    assert row[0] == "test_event"
    assert row[1] == "QUOTING"
    assert row[2] == "test-run"
    assert json.loads(row[3])["foo"] == "bar"
    assert meta[0] == "1"
