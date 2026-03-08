from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.audit_store import SQLiteAuditStore
from src.audit_summary import render_audit_summary
from src.config import BotConfig


def test_render_audit_summary_outputs_chinese_sections(tmp_path):
    db_path = tmp_path / "audit.db"
    snapshot_path = tmp_path / "state_snapshot.json"

    store = SQLiteAuditStore(str(db_path))
    store.open()
    store.append_event(
        ts_ms=1000,
        event="bootstrap_book",
        payload={
            "book": {
                "bids": [{"price": "1", "size": "1000"}],
                "asks": [{"price": "1.0001", "size": "1000"}],
            }
        },
        run_id="run-fill",
    )
    store.append_event(
        ts_ms=1100,
        event="decision",
        payload={"decision": {"reason": "inventory_low_bid_only"}},
        run_id="run-fill",
    )
    store.append_event(ts_ms=1200, event="place_order", payload={"clOrdId": "buy1"}, run_id="run-fill")
    store.append_event(
        ts_ms=1300,
        event="order_update",
        payload={"order": {"cl_ord_id": "buy1", "side": "buy", "price": "1", "filled_size": "10000", "state": "filled"}},
        run_id="run-fill",
    )
    store.append_event(ts_ms=1400, event="place_order", payload={"clOrdId": "sell1"}, run_id="run-fill")
    store.append_event(
        ts_ms=1500,
        event="order_update",
        payload={"order": {"cl_ord_id": "sell1", "side": "sell", "price": "1", "filled_size": "10000", "state": "filled"}},
        run_id="run-fill",
    )
    store.append_event(ts_ms=1600, event="cancel_order", payload={"reason": "reprice_or_ttl", "reason_zh": "改价或超时重挂"}, run_id="run-fill")
    store.append_event(
        ts_ms=2000,
        event="decision",
        payload={"decision": {"reason": "inventory_low_bid_only"}},
        run_id="run-latest",
    )
    store.append_event(ts_ms=2100, event="place_order", payload={"clOrdId": "latest-buy"}, run_id="run-latest")
    store.append_event(ts_ms=2200, event="cancel_order", payload={"reason": "shutdown", "reason_zh": "程序关闭"}, run_id="run-latest")
    store.close()

    snapshot_path.write_text(
        json.dumps(
            {
                "instrument": {"base_ccy": "USDC", "quote_ccy": "USDT"},
                "book": {
                    "bids": [{"price": "1", "size": "1000"}],
                    "asks": [{"price": "1.0001", "size": "1000"}],
                },
                "balances": {
                    "USDC": {"total": "11110.100850395593"},
                    "USDT": {"total": "17562.853776016487"},
                },
                "runtime_state": "STOPPED",
                "runtime_reason": "shutdown",
                "initial_nav_quote": "28673.51013145459977965",
                "observed_fill_count": 2,
                "observed_fill_volume_quote": "20000",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = BotConfig(mode="live")
    config.exchange.simulated = True
    config.telemetry.sqlite_path = str(db_path)
    config.telemetry.state_path = str(snapshot_path)

    text = render_audit_summary(config)

    assert "当前快照" in text
    assert "模式=OKX模拟盘" in text
    assert "最新运行" in text
    assert "最近一次有成交的运行" in text
    assert "往返价差毛收益估算(U)=0" in text
    assert "撤单主因: 改价或超时重挂 1" in text
