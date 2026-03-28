from decimal import Decimal
import io
import json
from pathlib import Path
import sys
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.okx_binance_usdc_arb_scan import _calc_opportunity
from scripts.okx_binance_usdc_arb_summary import main as summary_main


def test_calc_opportunity_computes_gross_net_and_depth_cap():
    opportunity = _calc_opportunity(
        maker_exchange="okx",
        taker_exchange="binance",
        maker_ask=Decimal("1.0000"),
        taker_bid=Decimal("1.0003"),
        maker_ask_depth=Decimal("5000"),
        taker_bid_depth=Decimal("3000"),
        maker_fee=Decimal("0"),
        taker_fee=Decimal("0.0005"),
    )

    assert opportunity.direction == "buy_okx_sell_binance"
    assert opportunity.gross_edge_bp == Decimal("3")
    assert opportunity.net_edge_bp == Decimal("-2")
    assert opportunity.maker_depth_quote == Decimal("5000")
    assert opportunity.taker_depth_quote == Decimal("3000.9")
    assert opportunity.max_quote_notional == Decimal("3000.9")


def test_arb_summary_reports_positive_ratio_and_streak(tmp_path, monkeypatch):
    path = tmp_path / "scan.jsonl"
    rows = [
        {"ts_ms": 1, "opportunities": [{"net_edge_bp": "0.1", "max_quote_notional": "100"}]},
        {"ts_ms": 2, "opportunities": [{"net_edge_bp": "0.2", "max_quote_notional": "200"}]},
        {"ts_ms": 3, "opportunities": [{"net_edge_bp": "-0.1", "max_quote_notional": "50"}]},
        {"ts_ms": 4, "opportunities": [{"net_edge_bp": "0.3", "max_quote_notional": "150"}]},
    ]
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    monkeypatch.setattr(sys, "argv", ["arb_summary", "--jsonl", str(path), "--positive-threshold-bp", "0"])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        summary_main()
    output = buffer.getvalue()

    assert "- samples=4" in output
    assert "- positive_samples=3" in output
    assert "- longest_positive_streak=2" in output
    assert "- max_quote_notional=200" in output
