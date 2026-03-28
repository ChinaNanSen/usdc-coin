from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .utils import now_ms, to_jsonable


def append_route_ledger_event(path: str | Path, payload: dict[str, Any]) -> None:
    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts_ms": now_ms(),
        "payload": to_jsonable(payload),
    }
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_route_ledger_events(path: str | Path, *, offset: int) -> tuple[int, list[dict[str, Any]]]:
    ledger_path = Path(path)
    if not ledger_path.exists():
        return max(offset, 0), []
    events: list[dict[str, Any]] = []
    with ledger_path.open("r", encoding="utf-8") as handle:
        handle.seek(max(offset, 0))
        while True:
            line = handle.readline()
            if not line:
                break
            try:
                events.append(json.loads(line))
            except Exception:
                continue
        new_offset = handle.tell()
    return new_offset, events
