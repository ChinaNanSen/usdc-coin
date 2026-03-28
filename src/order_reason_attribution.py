from __future__ import annotations

import json
from collections import Counter, deque
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .reason_attribution import classify_reason_bucket, realized_per_10k_turnover


@dataclass(frozen=True)
class ReasonBucketSummary:
    bucket: str
    fill_count: int
    turnover_quote: Decimal
    realized_pnl_quote: Decimal
    realized_per_10k_turnover: Decimal | None
    avg_adverse_ticks_300ms: Decimal | None = None
    avg_adverse_ticks_1000ms: Decimal | None = None
    avg_adverse_ticks_2000ms: Decimal | None = None


def _parse_decimal(value: Any) -> Decimal:
    if value in (None, "", "null"):
        return Decimal("0")
    return Decimal(str(value))


def _latest_run_id(records: list[dict[str, Any]]) -> str | None:
    latest_run = None
    latest_ts = -1
    for rec in records:
        run_id = rec.get("run_id")
        ts = int(rec.get("ts_ms") or 0)
        if run_id and ts >= latest_ts:
            latest_run = str(run_id)
            latest_ts = ts
    return latest_run


def _extract_decision_intents(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    decision = (payload or {}).get("decision") or {}
    result: dict[str, list[dict[str, Any]]] = {"buy": [], "sell": []}
    for side_key, normalized_side in (("bid_layers", "buy"), ("ask_layers", "sell")):
        for layer in decision.get(side_key) or []:
            if not isinstance(layer, dict):
                continue
            result[normalized_side].append(
                {
                    "reason": str(layer.get("reason") or ""),
                    "price": _parse_decimal(layer.get("price") or "0"),
                    "base_size": _parse_decimal(layer.get("base_size") or "0"),
                    "quote_notional": _parse_decimal(layer.get("quote_notional") or "0"),
                }
            )
    return result


def _infer_reason_from_decision(*, side: str, price: Decimal, size: Decimal, intents: list[dict[str, Any]]) -> str:
    for intent in intents:
        if intent["price"] == price and intent["base_size"] == size:
            return str(intent["reason"] or "")
    for intent in intents:
        if intent["price"] == price:
            return str(intent["reason"] or "")
    return ""


def _load_state_markout_by_reason(state_path: str | None) -> dict[str, dict[str, dict[str, Any]]]:
    if not state_path:
        return {}
    path = Path(state_path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    data = payload.get("fill_markout_summary_by_reason")
    return data if isinstance(data, dict) else {}


def analyze_reason_attribution(*, journal_path: str, state_path: str | None = None, run_id: str | None = None) -> tuple[str | None, list[ReasonBucketSummary]]:
    path = Path(journal_path)
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                records.append(json.loads(line))
            except Exception:
                continue

    target_run_id = run_id or _latest_run_id(records)
    if not target_run_id:
        return None, []

    records = [record for record in records if record.get("run_id") == target_run_id]
    records.sort(key=lambda item: int(item.get("ts_ms") or 0))

    latest_intents_by_side: dict[str, list[dict[str, Any]]] = {"buy": [], "sell": []}
    reason_by_order: dict[str, str] = {}
    prev_filled_by_order: dict[str, Decimal] = {}
    lots: deque[dict[str, Any]] = deque()
    fill_count_by_bucket: Counter[str] = Counter()
    turnover_by_bucket: dict[str, Decimal] = Counter()  # type: ignore[assignment]
    pnl_by_bucket: dict[str, Decimal] = Counter()  # type: ignore[assignment]

    for record in records:
        event = str(record.get("event") or "")
        payload = record.get("payload") or {}

        if event == "decision":
            latest_intents_by_side = _extract_decision_intents(payload)
            continue

        if event in {"place_order", "shadow_quote"}:
            cl_ord_id = str(payload.get("clOrdId") or payload.get("cl_ord_id") or "")
            if not cl_ord_id:
                continue
            reason = str(payload.get("reason") or "")
            if not reason:
                side = str(payload.get("side") or "")
                price = _parse_decimal(payload.get("px") or payload.get("price") or "0")
                size = _parse_decimal(payload.get("sz") or payload.get("base_size") or "0")
                reason = _infer_reason_from_decision(
                    side=side,
                    price=price,
                    size=size,
                    intents=latest_intents_by_side.get(side, []),
                )
            if reason:
                reason_by_order[cl_ord_id] = reason
            continue

        if event in {"amend_order_submitted", "shadow_amend_order"}:
            cl_ord_id = str(payload.get("cl_ord_id") or payload.get("clOrdId") or "")
            reason = str(payload.get("reason") or "")
            if cl_ord_id and reason:
                reason_by_order[cl_ord_id] = reason
            continue

        if event != "order_update":
            continue

        order = payload.get("order") or {}
        cl_ord_id = str(order.get("cl_ord_id") or order.get("clOrdId") or "")
        if not cl_ord_id:
            continue
        reason = str(payload.get("reason") or reason_by_order.get(cl_ord_id) or "")
        if reason:
            reason_by_order[cl_ord_id] = reason
        bucket = classify_reason_bucket(reason)

        filled_size = _parse_decimal(order.get("filled_size") or "0")
        prev_filled = prev_filled_by_order.get(cl_ord_id, Decimal("0"))
        fill_delta = filled_size - prev_filled
        prev_filled_by_order[cl_ord_id] = filled_size
        if fill_delta <= 0:
            continue

        raw = payload.get("raw") or {}
        fill_price = _parse_decimal(raw.get("fillPx") or order.get("price") or "0")
        side = str(order.get("side") or "")
        fill_count_by_bucket[bucket] += 1
        turnover_by_bucket[bucket] += fill_delta * fill_price

        remaining = fill_delta
        if side == "buy":
            while remaining > 0 and lots and lots[0]["qty"] < 0:
                lot = lots[0]
                matched = min(remaining, -lot["qty"])
                pnl_by_bucket[bucket] += matched * (lot["price"] - fill_price)
                lot["qty"] += matched
                remaining -= matched
                if lot["qty"] == 0:
                    lots.popleft()
            if remaining > 0:
                lots.append({"qty": remaining, "price": fill_price, "reason": reason})
        elif side == "sell":
            while remaining > 0 and lots and lots[0]["qty"] > 0:
                lot = lots[0]
                matched = min(remaining, lot["qty"])
                pnl_by_bucket[bucket] += matched * (fill_price - lot["price"])
                lot["qty"] -= matched
                remaining -= matched
                if lot["qty"] == 0:
                    lots.popleft()
            if remaining > 0:
                lots.append({"qty": -remaining, "price": fill_price, "reason": reason})

    markout_by_reason = _load_state_markout_by_reason(state_path)
    buckets = sorted(set(fill_count_by_bucket) | set(turnover_by_bucket) | set(pnl_by_bucket) | set(markout_by_reason))
    summaries: list[ReasonBucketSummary] = []
    for bucket in buckets:
        markout = markout_by_reason.get(bucket) or {}
        summaries.append(
            ReasonBucketSummary(
                bucket=bucket,
                fill_count=int(fill_count_by_bucket.get(bucket, 0)),
                turnover_quote=Decimal(turnover_by_bucket.get(bucket, Decimal("0"))),
                realized_pnl_quote=Decimal(pnl_by_bucket.get(bucket, Decimal("0"))),
                realized_per_10k_turnover=realized_per_10k_turnover(
                    realized_pnl_quote=Decimal(pnl_by_bucket.get(bucket, Decimal("0"))),
                    turnover_quote=Decimal(turnover_by_bucket.get(bucket, Decimal("0"))),
                ),
                avg_adverse_ticks_300ms=_parse_decimal((markout.get("300") or {}).get("avg_adverse_ticks")) if markout.get("300") else None,
                avg_adverse_ticks_1000ms=_parse_decimal((markout.get("1000") or {}).get("avg_adverse_ticks")) if markout.get("1000") else None,
                avg_adverse_ticks_2000ms=_parse_decimal((markout.get("2000") or {}).get("avg_adverse_ticks")) if markout.get("2000") else None,
            )
        )
    summaries.sort(key=lambda item: item.turnover_quote, reverse=True)
    return target_run_id, summaries
