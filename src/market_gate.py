from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketGateStatus:
    inst_id: str
    role: str
    live_allowed: bool
    reason: str
    live_allowed_instruments: tuple[str, ...]
    observe_only_instruments: tuple[str, ...]


def normalize_instruments(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not values:
        return ()
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        normalized.append(item)
        seen.add(item)
    return tuple(normalized)


def evaluate_market_gate(
    *,
    inst_id: str,
    live_allowed_instruments: list[str] | tuple[str, ...] | None,
    observe_only_instruments: list[str] | tuple[str, ...] | None,
) -> MarketGateStatus:
    live_allowed = normalize_instruments(live_allowed_instruments)
    observe_only = normalize_instruments(observe_only_instruments)
    if inst_id in observe_only:
        return MarketGateStatus(
            inst_id=inst_id,
            role="observe_only",
            live_allowed=False,
            reason=f"observe-only instrument blocked in live mode: {inst_id}",
            live_allowed_instruments=live_allowed,
            observe_only_instruments=observe_only,
        )
    if live_allowed and inst_id not in live_allowed:
        return MarketGateStatus(
            inst_id=inst_id,
            role="unapproved",
            live_allowed=False,
            reason=f"instrument not approved for live mode: {inst_id}",
            live_allowed_instruments=live_allowed,
            observe_only_instruments=observe_only,
        )
    role = "core" if inst_id in live_allowed else "open"
    return MarketGateStatus(
        inst_id=inst_id,
        role=role,
        live_allowed=True,
        reason="ok",
        live_allowed_instruments=live_allowed,
        observe_only_instruments=observe_only,
    )
