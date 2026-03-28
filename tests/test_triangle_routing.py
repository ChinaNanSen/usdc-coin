from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.triangle_routing import build_triangle_quote_snapshot, compute_dual_exit_metrics, compute_inventory_route_choice


def test_compute_dual_exit_metrics_for_usd1_usdt():
    snapshot = build_triangle_quote_snapshot(
        {
            "USDC-USDT": {"bid": Decimal("1.0002"), "ask": Decimal("1.0003")},
            "USD1-USDT": {"bid": Decimal("0.9995"), "ask": Decimal("0.9996")},
            "USD1-USDC": {"bid": Decimal("0.9993"), "ask": Decimal("0.9994")},
        },
        checked_at_ms=1,
    )

    metrics = compute_dual_exit_metrics(
        inst_id="USD1-USDT",
        entry_buy_price=Decimal("0.9994"),
        snapshot=snapshot,
        indirect_leg_penalty_bp=Decimal("0.2"),
    )

    assert metrics is not None
    assert metrics["direct_exit_price"] == Decimal("0.9996")
    assert metrics["indirect_exit_price"] == Decimal("0.99949986")
    assert metrics["best_exit_edge_bp"] > Decimal("1")
    assert metrics["strict_dual_exit_edge_bp"] > Decimal("0")


def test_compute_dual_exit_metrics_for_usdc_usdt():
    snapshot = build_triangle_quote_snapshot(
        {
            "USDC-USDT": {"bid": Decimal("1.0002"), "ask": Decimal("1.0003")},
            "USD1-USDT": {"bid": Decimal("0.9995"), "ask": Decimal("0.9996")},
            "USD1-USDC": {"bid": Decimal("0.9993"), "ask": Decimal("0.9994")},
        },
        checked_at_ms=1,
    )

    metrics = compute_dual_exit_metrics(
        inst_id="USDC-USDT",
        entry_buy_price=Decimal("1.0001"),
        snapshot=snapshot,
        indirect_leg_penalty_bp=Decimal("0.2"),
    )

    assert metrics is not None
    assert metrics["direct_exit_price"] == Decimal("1.0003")
    assert metrics["indirect_exit_price"] == Decimal("1.000100060036021612967780668")
    assert metrics["best_exit_edge_bp"] > Decimal("1")
    assert metrics["strict_dual_exit_edge_bp"] >= Decimal("-0.2")


def test_compute_dual_exit_metrics_returns_none_for_unsupported_market():
    snapshot = build_triangle_quote_snapshot(
        {
            "USDC-USDT": {"bid": Decimal("1.0002"), "ask": Decimal("1.0003")},
            "USD1-USDT": {"bid": Decimal("0.9995"), "ask": Decimal("0.9996")},
            "USD1-USDC": {"bid": Decimal("0.9993"), "ask": Decimal("0.9994")},
        },
        checked_at_ms=1,
    )

    assert compute_dual_exit_metrics(
        inst_id="BTC-USDT",
        entry_buy_price=Decimal("100000"),
        snapshot=snapshot,
        indirect_leg_penalty_bp=Decimal("0.2"),
    ) is None


def test_compute_inventory_route_choice_prefers_direct_sell_when_direct_is_better():
    snapshot = build_triangle_quote_snapshot(
        {
            "USDC-USDT": {"bid": Decimal("1.0002"), "ask": Decimal("1.0003")},
            "USD1-USDT": {"bid": Decimal("0.9995"), "ask": Decimal("0.9996")},
            "USD1-USDC": {"bid": Decimal("0.9993"), "ask": Decimal("0.9994")},
        },
        checked_at_ms=1,
    )

    choice = compute_inventory_route_choice(
        inst_id="USD1-USDT",
        position_base=Decimal("800"),
        current_bid=Decimal("0.9995"),
        current_ask=Decimal("0.9996"),
        snapshot=snapshot,
        indirect_leg_penalty_bp=Decimal("0.2"),
        prefer_indirect_min_improvement_bp=Decimal("0.1"),
    )

    assert choice is not None
    assert choice["primary_route"] == "direct_sell_usd1usdt"
    assert choice["backup_route"] == "sell_usd1usdc_then_sell_usdcusdt"
    assert choice["direction"] == "sell"


def test_compute_inventory_route_choice_can_prefer_indirect_sell_when_indirect_is_better():
    snapshot = build_triangle_quote_snapshot(
        {
            "USDC-USDT": {"bid": Decimal("1.0006"), "ask": Decimal("1.0007")},
            "USD1-USDT": {"bid": Decimal("0.9995"), "ask": Decimal("0.9996")},
            "USD1-USDC": {"bid": Decimal("0.9998"), "ask": Decimal("0.9999")},
        },
        checked_at_ms=1,
    )

    choice = compute_inventory_route_choice(
        inst_id="USD1-USDT",
        position_base=Decimal("800"),
        current_bid=Decimal("0.9995"),
        current_ask=Decimal("0.9996"),
        snapshot=snapshot,
        indirect_leg_penalty_bp=Decimal("0.2"),
        prefer_indirect_min_improvement_bp=Decimal("0.1"),
    )

    assert choice is not None
    assert choice["primary_route"] == "sell_usd1usdc_then_sell_usdcusdt"
    assert choice["backup_route"] == "direct_sell_usd1usdt"
