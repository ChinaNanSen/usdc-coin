import json
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.order_reason_attribution import analyze_reason_attribution


def test_analyze_reason_attribution_summarizes_turnover_and_realized_pnl(tmp_path):
    journal = tmp_path / "journal.jsonl"
    state = tmp_path / "state.json"
    records = [
        {"ts_ms": 1, "run_id": "run1", "event": "decision", "payload": {"decision": {"bid_layers": [{"reason": "join_best_bid", "price": "1", "base_size": "10"}], "ask_layers": []}}},
        {"ts_ms": 2, "run_id": "run1", "event": "place_order", "payload": {"clOrdId": "buy1", "side": "buy", "px": "1", "sz": "10"}},
        {"ts_ms": 3, "run_id": "run1", "event": "order_update", "payload": {"order": {"cl_ord_id": "buy1", "side": "buy", "price": "1", "filled_size": "10"}, "raw": {"fillPx": "1"}}},
        {"ts_ms": 4, "run_id": "run1", "event": "amend_order_submitted", "payload": {"cl_ord_id": "sell1", "reason": "rebalance_secondary_ask"}},
        {"ts_ms": 5, "run_id": "run1", "event": "order_update", "payload": {"order": {"cl_ord_id": "sell1", "side": "sell", "price": "1.0002", "filled_size": "10"}, "raw": {"fillPx": "1.0002"}}},
    ]
    with journal.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    state.write_text(
        json.dumps(
            {
                "fill_markout_summary_by_reason": {
                    "entry": {"300": {"avg_adverse_ticks": "0.1"}},
                    "secondary": {"300": {"avg_adverse_ticks": "0.2"}},
                }
            }
        ),
        encoding="utf-8",
    )

    run_id, summaries = analyze_reason_attribution(journal_path=str(journal), state_path=str(state))

    assert run_id == "run1"
    by_bucket = {item.bucket: item for item in summaries}
    assert by_bucket["entry"].turnover_quote == Decimal("10")
    assert by_bucket["secondary"].turnover_quote == Decimal("10.002")
    assert by_bucket["secondary"].realized_pnl_quote == Decimal("0.002")
    assert by_bucket["secondary"].avg_adverse_ticks_300ms == Decimal("0.2")
