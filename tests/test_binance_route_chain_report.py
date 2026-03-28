import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.binance_route_chain_report import render_binance_route_chain_report


def test_render_binance_route_chain_report_summarizes_main_release_and_ledger(tmp_path):
    main_state = tmp_path / "main_state.json"
    release_state = tmp_path / "release_state.json"
    main_journal = tmp_path / "main_journal.jsonl"
    release_journal = tmp_path / "release_journal.jsonl"
    route_ledger = tmp_path / "route_ledger.jsonl"

    main_state.write_text(
        json.dumps(
            {
                "runtime_state": "QUOTING",
                "runtime_reason": "fill_rebalance_sell_only",
                "strategy_position_base": "935",
                "triangle_exit_route_choice": {
                    "primary_route": "sell_usd1usdc_then_sell_usdcusdt",
                    "backup_route": "direct_sell_usd1usdt",
                    "direction": "sell",
                    "improvement_bp": "0.30",
                },
                "triangle_route_diagnostics": {
                    "snapshot_status": "ready",
                    "route_status": "indirect_preferred",
                    "entry_buy_gate_status": "allowed",
                    "entry_buy_gate_reason": "strict_edge_ok",
                    "strict_dual_exit_edge_bp": "0.18",
                    "best_exit_edge_bp": "0.30",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    release_state.write_text(
        json.dumps(
            {
                "runtime_state": "QUOTING",
                "runtime_reason": "release_external_sell_only",
                "external_base_inventory_remaining": "150",
                "shared_release_inventory_base": "935",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    main_journal.write_text(
        "\n".join(
            [
                json.dumps({"ts_ms": 1, "run_id": "run-main", "event": "decision", "payload": {"decision": {"bid_layers": [], "ask_layers": [{"reason": "rebalance_open_long", "price": "0.9998", "base_size": "935"}]}}}),
                json.dumps({"ts_ms": 2, "run_id": "run-main", "event": "order_update", "payload": {"order": {"cl_ord_id": "m1", "side": "sell", "price": "0.9998", "filled_size": "935"}, "raw": {"fillPx": "0.9998"}, "reason": "rebalance_open_long", "reason_bucket": "rebalance"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    release_journal.write_text(
        "\n".join(
            [
                json.dumps({"ts_ms": 1, "run_id": "run-release", "event": "decision", "payload": {"decision": {"bid_layers": [], "ask_layers": [{"reason": "release_external_long", "price": "0.9996", "base_size": "250"}]}}}),
                json.dumps({"ts_ms": 2, "run_id": "run-release", "event": "order_update", "payload": {"order": {"cl_ord_id": "r1", "side": "sell", "price": "0.9996", "filled_size": "250"}, "raw": {"fillPx": "0.9996"}, "reason": "release_external_long", "reason_bucket": "release"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    route_ledger.write_text(
        "\n".join(
            [
                json.dumps({"ts_ms": 10, "payload": {"asset": "USD1", "source_inst_id": "USD1-USDC", "fill_size": "250", "fill_price": "0.9996", "reason": "release_external_long"}}),
                json.dumps({"ts_ms": 20, "payload": {"asset": "USD1", "source_inst_id": "USD1-USDC", "fill_size": "150", "fill_price": "0.9997", "reason": "release_external_long"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    text = render_binance_route_chain_report(
        main_state_path=str(main_state),
        main_journal_path=str(main_journal),
        release_state_path=str(release_state),
        release_journal_path=str(release_journal),
        route_ledger_path=str(route_ledger),
    )

    assert "USD1 Route Chain Report" in text
    assert "Main Leg" in text
    assert "state=QUOTING" in text
    assert "position_base=935" in text
    assert "primary_route=sell_usd1usdc_then_sell_usdcusdt" in text
    assert "diagnostics snapshot=ready" in text
    assert "route_status=indirect_preferred" in text
    assert "entry_buy_gate=allowed" in text
    assert "Release Leg" in text
    assert "external_remaining=150" in text
    assert "shared_release_base=935" in text
    assert "Route Ledger" in text
    assert "events=2" in text
    assert "released_base=400" in text
    assert "released_quote=399.855" in text
    assert "main_attribution" in text
    assert "release_attribution" in text


def test_render_binance_route_chain_report_falls_back_to_journal_diagnostics(tmp_path):
    main_state = tmp_path / "main_state.json"
    release_state = tmp_path / "release_state.json"
    main_journal = tmp_path / "main_journal.jsonl"
    release_journal = tmp_path / "release_journal.jsonl"
    route_ledger = tmp_path / "route_ledger.jsonl"

    main_state.write_text(json.dumps({"runtime_state": "QUOTING", "strategy_position_base": "0"}, ensure_ascii=False), encoding="utf-8")
    release_state.write_text(json.dumps({"runtime_state": "QUOTING"}, ensure_ascii=False), encoding="utf-8")
    main_journal.write_text(
        "\n".join(
            [
                json.dumps({"ts_ms": 10, "run_id": "run-main", "event": "triangle_route_diagnostics", "payload": {"diagnostics": {"snapshot_status": "ready", "route_status": "flat_position", "entry_buy_gate_status": "blocked", "entry_buy_gate_reason": "best_exit_edge_too_low"}}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    release_journal.write_text("", encoding="utf-8")
    route_ledger.write_text("", encoding="utf-8")

    text = render_binance_route_chain_report(
        main_state_path=str(main_state),
        main_journal_path=str(main_journal),
        release_state_path=str(release_state),
        release_journal_path=str(release_journal),
        route_ledger_path=str(route_ledger),
    )

    assert "diagnostics snapshot=ready" in text
    assert "route_status=flat_position" in text
    assert "entry_buy_gate=blocked" in text
