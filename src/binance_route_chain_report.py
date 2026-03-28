from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from .order_reason_attribution import analyze_reason_attribution
from .utils import decimal_to_str


def _optional_decimal(value: Any) -> Decimal | None:
    if value in (None, "", "null"):
        return None
    return Decimal(str(value))


def _latest_run_with_fills_from_journal(path: str) -> str | None:
    journal_path = Path(path)
    if not journal_path.exists():
        return None
    latest_run: str | None = None
    latest_ts = -1
    with journal_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except Exception:
                continue
            if record.get("event") != "order_update":
                continue
            payload = record.get("payload") or {}
            order = payload.get("order") or {}
            filled = _optional_decimal(order.get("filled_size")) or Decimal("0")
            if filled <= 0:
                continue
            ts = int(record.get("ts_ms") or 0)
            run_id = record.get("run_id")
            if run_id and ts >= latest_ts:
                latest_run = str(run_id)
                latest_ts = ts
    return latest_run


def _render_bucket_lines(prefix: str, summaries: list) -> list[str]:
    if not summaries:
        return [f"- {prefix}=no_data"]
    lines: list[str] = []
    for item in summaries:
        per10k = decimal_to_str(item.realized_per_10k_turnover) if item.realized_per_10k_turnover is not None else "na"
        lines.append(
            f"- {prefix}:{item.bucket} fills={item.fill_count} turnover={decimal_to_str(item.turnover_quote)} realized={decimal_to_str(item.realized_pnl_quote)} per10k={per10k}"
        )
    return lines


def _load_state(path: str) -> dict[str, Any]:
    state_path = Path(path)
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _latest_triangle_diagnostics_from_journal(path: str) -> dict[str, Any]:
    journal_path = Path(path)
    if not journal_path.exists():
        return {}
    latest: dict[str, Any] = {}
    latest_ts = -1
    with journal_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except Exception:
                continue
            if record.get("event") != "triangle_route_diagnostics":
                continue
            ts_ms = int(record.get("ts_ms") or 0)
            payload = record.get("payload") or {}
            diagnostics = payload.get("diagnostics") or {}
            if not isinstance(diagnostics, dict):
                continue
            if ts_ms >= latest_ts:
                latest = diagnostics
                latest_ts = ts_ms
    return latest


def _summarize_route_ledger(path: str) -> dict[str, Decimal | int]:
    ledger_path = Path(path)
    if not ledger_path.exists():
        return {"events": 0, "released_base": Decimal("0"), "released_quote": Decimal("0")}
    event_count = 0
    released_base = Decimal("0")
    released_quote = Decimal("0")
    with ledger_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except Exception:
                continue
            payload = record.get("payload") or {}
            fill_size = _optional_decimal(payload.get("fill_size")) or Decimal("0")
            fill_price = _optional_decimal(payload.get("fill_price")) or Decimal("0")
            if fill_size <= 0 or fill_price <= 0:
                continue
            event_count += 1
            released_base += fill_size
            released_quote += fill_size * fill_price
    return {
        "events": event_count,
        "released_base": released_base,
        "released_quote": released_quote,
    }


def render_binance_route_chain_report(
    *,
    main_state_path: str,
    main_journal_path: str,
    release_state_path: str,
    release_journal_path: str,
    route_ledger_path: str,
) -> str:
    main_state = _load_state(main_state_path)
    release_state = _load_state(release_state_path)
    main_run = _latest_run_with_fills_from_journal(main_journal_path)
    release_run = _latest_run_with_fills_from_journal(release_journal_path)
    _, main_attr = analyze_reason_attribution(journal_path=main_journal_path, state_path=main_state_path, run_id=main_run)
    _, release_attr = analyze_reason_attribution(journal_path=release_journal_path, state_path=release_state_path, run_id=release_run)
    ledger = _summarize_route_ledger(route_ledger_path)

    route_choice = main_state.get("triangle_exit_route_choice") or {}
    diagnostics = main_state.get("triangle_route_diagnostics") or _latest_triangle_diagnostics_from_journal(main_journal_path)
    lines = [
        "USD1 Route Chain Report",
        "Main Leg",
        f"- state={main_state.get('runtime_state') or '-'} reason={main_state.get('runtime_reason') or '-'}",
        f"- position_base={main_state.get('strategy_position_base') or '0'}",
        f"- primary_route={route_choice.get('primary_route') or '-'} backup_route={route_choice.get('backup_route') or '-'} direction={route_choice.get('direction') or '-'} improvement_bp={route_choice.get('improvement_bp') or '-'}",
        (
            f"- diagnostics snapshot={diagnostics.get('snapshot_status') or '-'} "
            f"route_status={diagnostics.get('route_status') or '-'} "
            f"entry_buy_gate={diagnostics.get('entry_buy_gate_status') or '-'} "
            f"entry_reason={diagnostics.get('entry_buy_gate_reason') or '-'} "
            f"strict_edge_bp={diagnostics.get('strict_dual_exit_edge_bp') or '-'} "
            f"best_edge_bp={diagnostics.get('best_exit_edge_bp') or '-'}"
        ),
        "Release Leg",
        f"- state={release_state.get('runtime_state') or '-'} reason={release_state.get('runtime_reason') or '-'}",
        f"- external_remaining={release_state.get('external_base_inventory_remaining') or '0'} shared_release_base={release_state.get('shared_release_inventory_base') or '0'}",
        "Route Ledger",
        f"- events={ledger['events']} released_base={decimal_to_str(ledger['released_base'])} released_quote={decimal_to_str(ledger['released_quote'])}",
        "Attribution",
    ]
    lines.extend(_render_bucket_lines("main_attribution", main_attr))
    lines.extend(_render_bucket_lines("release_attribution", release_attr))
    return "\n".join(lines)
