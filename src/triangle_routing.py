from __future__ import annotations

from decimal import Decimal
from typing import Any


SUPPORTED_TRIANGLE_PAIRS = ("USDC-USDT", "USD1-USDT", "USD1-USDC")


def build_triangle_quote_snapshot(quotes: dict[str, dict[str, Decimal]], *, checked_at_ms: int) -> dict[str, Any]:
    snapshot_quotes: dict[str, dict[str, Decimal]] = {}
    for inst_id in SUPPORTED_TRIANGLE_PAIRS:
        item = quotes.get(inst_id) or {}
        bid = Decimal(str(item.get("bid") or "0"))
        ask = Decimal(str(item.get("ask") or "0"))
        snapshot_quotes[inst_id] = {"bid": bid, "ask": ask}
    return {
        "checked_at_ms": int(checked_at_ms),
        "quotes": snapshot_quotes,
    }


def compute_dual_exit_metrics(
    *,
    inst_id: str,
    entry_buy_price: Decimal,
    snapshot: dict[str, Any] | None,
    indirect_leg_penalty_bp: Decimal,
) -> dict[str, Decimal] | None:
    if inst_id not in {"USDC-USDT", "USD1-USDT"}:
        return None
    if not snapshot or entry_buy_price <= 0:
        return None

    quotes = snapshot.get("quotes") or {}
    usdc_usdt = quotes.get("USDC-USDT") or {}
    usd1_usdt = quotes.get("USD1-USDT") or {}
    usd1_usdc = quotes.get("USD1-USDC") or {}

    if inst_id == "USD1-USDT":
        direct_exit_price = Decimal(str(usd1_usdt.get("ask") or "0"))
        indirect_exit_price = Decimal(str(usd1_usdc.get("bid") or "0")) * Decimal(str(usdc_usdt.get("bid") or "0"))
    else:
        direct_exit_price = Decimal(str(usdc_usdt.get("ask") or "0"))
        indirect_leg_1 = Decimal(str(usd1_usdt.get("bid") or "0"))
        indirect_leg_2 = Decimal(str(usd1_usdc.get("ask") or "0"))
        indirect_exit_price = (indirect_leg_1 / indirect_leg_2) if indirect_leg_2 > 0 else Decimal("0")

    if direct_exit_price <= 0 or indirect_exit_price <= 0:
        return None

    direct_exit_edge_bp = (direct_exit_price / entry_buy_price - Decimal("1")) * Decimal("10000")
    indirect_exit_edge_bp = (indirect_exit_price / entry_buy_price - Decimal("1")) * Decimal("10000")
    indirect_exit_edge_after_penalty_bp = indirect_exit_edge_bp - max(indirect_leg_penalty_bp, Decimal("0"))
    strict_dual_exit_edge_bp = min(direct_exit_edge_bp, indirect_exit_edge_after_penalty_bp)
    best_exit_edge_bp = max(direct_exit_edge_bp, indirect_exit_edge_after_penalty_bp)

    return {
        "direct_exit_price": direct_exit_price,
        "indirect_exit_price": indirect_exit_price,
        "direct_exit_edge_bp": direct_exit_edge_bp,
        "indirect_exit_edge_bp": indirect_exit_edge_bp,
        "indirect_exit_edge_after_penalty_bp": indirect_exit_edge_after_penalty_bp,
        "strict_dual_exit_edge_bp": strict_dual_exit_edge_bp,
        "best_exit_edge_bp": best_exit_edge_bp,
    }


def compute_inventory_route_choice(
    *,
    inst_id: str,
    position_base: Decimal,
    current_bid: Decimal,
    current_ask: Decimal,
    snapshot: dict[str, Any] | None,
    indirect_leg_penalty_bp: Decimal,
    prefer_indirect_min_improvement_bp: Decimal = Decimal("0"),
) -> dict[str, Decimal | str] | None:
    if inst_id not in {"USDC-USDT", "USD1-USDT"}:
        return None
    if position_base == 0 or not snapshot:
        return None

    quotes = snapshot.get("quotes") or {}
    usdc_usdt = quotes.get("USDC-USDT") or {}
    usd1_usdt = quotes.get("USD1-USDT") or {}
    usd1_usdc = quotes.get("USD1-USDC") or {}
    penalty_bp = max(indirect_leg_penalty_bp, Decimal("0"))
    prefer_bp = max(prefer_indirect_min_improvement_bp, Decimal("0"))

    if position_base > 0:
        direction = "sell"
        direct_reference_price = current_ask
        if inst_id == "USD1-USDT":
            indirect_reference_price = Decimal(str(usd1_usdc.get("bid") or "0")) * Decimal(str(usdc_usdt.get("bid") or "0"))
            direct_route = "direct_sell_usd1usdt"
            indirect_route = "sell_usd1usdc_then_sell_usdcusdt"
        else:
            leg1 = Decimal(str(usd1_usdt.get("bid") or "0"))
            leg2 = Decimal(str(usd1_usdc.get("ask") or "0"))
            indirect_reference_price = (leg1 / leg2) if leg2 > 0 else Decimal("0")
            direct_route = "direct_sell_usdcusdt"
            indirect_route = "buy_usd1usdc_then_sell_usd1usdt"

        if direct_reference_price <= 0 or indirect_reference_price <= 0:
            return None

        direct_effective = direct_reference_price
        indirect_effective = indirect_reference_price * (Decimal("1") - penalty_bp / Decimal("10000"))
        direct_advantage_bp = (direct_effective / indirect_effective - Decimal("1")) * Decimal("10000")
        indirect_advantage_bp = (indirect_effective / direct_effective - Decimal("1")) * Decimal("10000")
        if indirect_advantage_bp > prefer_bp:
            primary_route, backup_route = indirect_route, direct_route
            primary_price, backup_price = indirect_reference_price, direct_reference_price
            improvement_bp = indirect_advantage_bp
        else:
            primary_route, backup_route = direct_route, indirect_route
            primary_price, backup_price = direct_reference_price, indirect_reference_price
            improvement_bp = max(direct_advantage_bp, Decimal("0"))
    else:
        direction = "buy"
        direct_reference_price = current_bid
        if inst_id == "USD1-USDT":
            indirect_reference_price = Decimal(str(usd1_usdc.get("ask") or "0")) * Decimal(str(usdc_usdt.get("ask") or "0"))
            direct_route = "direct_buy_usd1usdt"
            indirect_route = "buy_usdcusdt_then_buy_usd1usdc"
        else:
            leg1 = Decimal(str(usd1_usdt.get("ask") or "0"))
            leg2 = Decimal(str(usd1_usdc.get("bid") or "0"))
            indirect_reference_price = (leg1 / leg2) if leg2 > 0 else Decimal("0")
            direct_route = "direct_buy_usdcusdt"
            indirect_route = "buy_usd1usdt_then_sell_usd1usdc"

        if direct_reference_price <= 0 or indirect_reference_price <= 0:
            return None

        direct_effective = direct_reference_price
        indirect_effective = indirect_reference_price * (Decimal("1") + penalty_bp / Decimal("10000"))
        direct_advantage_bp = (indirect_effective / direct_effective - Decimal("1")) * Decimal("10000")
        indirect_advantage_bp = (direct_effective / indirect_effective - Decimal("1")) * Decimal("10000")
        if indirect_advantage_bp > prefer_bp:
            primary_route, backup_route = indirect_route, direct_route
            primary_price, backup_price = indirect_reference_price, direct_reference_price
            improvement_bp = indirect_advantage_bp
        else:
            primary_route, backup_route = direct_route, indirect_route
            primary_price, backup_price = direct_reference_price, indirect_reference_price
            improvement_bp = max(direct_advantage_bp, Decimal("0"))

    return {
        "direction": direction,
        "primary_route": primary_route,
        "backup_route": backup_route,
        "primary_reference_price": primary_price,
        "backup_reference_price": backup_price,
        "improvement_bp": improvement_bp,
    }
