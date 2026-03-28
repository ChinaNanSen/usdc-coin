from __future__ import annotations

from decimal import Decimal


def classify_reason_bucket(reason: str | None) -> str:
    value = str(reason or "").strip()
    if not value:
        return "unknown"
    if value.startswith("join_best") or value.startswith("join_second"):
        return "entry"
    if value.startswith("rebalance_secondary"):
        return "secondary"
    if value.startswith("rebalance_open"):
        return "rebalance"
    if value.startswith("strict_cycle"):
        return "strict_cycle"
    if value.startswith("release"):
        return "release"
    return value


def realized_per_10k_turnover(*, realized_pnl_quote: Decimal, turnover_quote: Decimal) -> Decimal | None:
    if turnover_quote <= 0:
        return None
    return (realized_pnl_quote / turnover_quote) * Decimal("10000")
