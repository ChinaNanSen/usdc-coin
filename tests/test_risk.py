from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import RiskConfig, TradingConfig
from src.models import Balance, BookLevel, BookSnapshot, FeeSnapshot, InstrumentMeta
from src.risk import RiskManager
from src.state import BotState
from src.utils import now_ms


def make_state() -> BotState:
    state = BotState(managed_prefix="bot6", state_path="data/test_state.json")
    state.set_instrument(
        InstrumentMeta(
            inst_id="USDC-USDT",
            inst_type="SPOT",
            base_ccy="USDC",
            quote_ccy="USDT",
            tick_size=Decimal("0.0001"),
            lot_size=Decimal("0.000001"),
            min_size=Decimal("1"),
            max_market_amount=Decimal("1000000"),
            max_limit_amount=Decimal("20000000"),
        )
    )
    state.set_book(
        BookSnapshot(
            ts_ms=now_ms(),
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0000"), size=Decimal("100000"))],
        )
    )
    state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=Decimal("50000"), available=Decimal("50000")),
            "USDT": Balance(ccy="USDT", total=Decimal("50000"), available=Decimal("50000")),
        }
    )
    state.set_stream_status("public_books5", True)
    state.set_stream_status("private_user", True)
    return state


def test_risk_blocks_stale_public_stream():
    risk = RiskManager(RiskConfig(stale_book_ms=1), TradingConfig(), mode="shadow")
    state = make_state()
    state.mark_stream_activity("public_books5", now_ms() - 10)
    status = risk.evaluate(state)
    assert status.ok is False
    assert "stale public stream" in status.reason


def test_risk_allows_quiet_book_when_public_stream_is_alive():
    risk = RiskManager(RiskConfig(stale_book_ms=1000), TradingConfig(), mode="shadow")
    state = make_state()
    state.book = BookSnapshot(
        ts_ms=0,
        received_ms=0,
        bids=state.book.bids,
        asks=state.book.asks,
    )
    state.mark_stream_activity("public_books5", now_ms())
    status = risk.evaluate(state)
    assert status.ok is True


def test_risk_falls_back_to_book_age_without_stream_activity():
    risk = RiskManager(RiskConfig(stale_book_ms=1), TradingConfig(), mode="shadow")
    state = make_state()
    state.stream_last_activity_ms["public_books5"] = 0
    state.book = BookSnapshot(ts_ms=0, received_ms=0, bids=state.book.bids, asks=state.book.asks)
    status = risk.evaluate(state)
    assert status.ok is False
    assert "stale book" in status.reason


def test_risk_blocks_after_daily_loss_limit():
    risk = RiskManager(RiskConfig(daily_loss_limit_quote=Decimal("10")), TradingConfig(), mode="shadow")
    state = make_state()
    state.initial_nav_quote = Decimal("100000")
    state.balances["USDC"] = Balance(ccy="USDC", total=Decimal("49980"), available=Decimal("49980"))
    status = risk.evaluate(state)
    assert status.ok is False
    assert "daily loss limit" in status.reason


def test_risk_blocks_when_streams_not_ready_in_live_mode():
    risk = RiskManager(RiskConfig(), TradingConfig(), mode="live")
    state = make_state()
    state.set_stream_status("private_user", False)
    status = risk.evaluate(state)
    assert status.ok is False
    assert status.runtime_state == "INIT"


def test_risk_does_not_enter_reduce_only_from_account_inventory_when_bot_is_flat():
    risk = RiskManager(RiskConfig(), TradingConfig(), mode="shadow")
    state = make_state()
    state.balances["USDC"] = Balance(ccy="USDC", total=Decimal("90000"), available=Decimal("90000"))
    state.balances["USDT"] = Balance(ccy="USDT", total=Decimal("10000"), available=Decimal("10000"))
    status = risk.evaluate(state)
    assert status.ok is True
    assert status.allow_bid is True
    assert status.allow_ask is True
    assert status.runtime_state == "READY"


def test_risk_allows_bot_short_to_keep_buy_side_even_when_account_inventory_is_high():
    risk = RiskManager(RiskConfig(), TradingConfig(), mode="shadow")
    state = make_state()
    state.balances["USDC"] = Balance(ccy="USDC", total=Decimal("90000"), available=Decimal("90000"))
    state.balances["USDT"] = Balance(ccy="USDT", total=Decimal("10000"), available=Decimal("10000"))
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "1",
            "clOrdId": "bot6ms-test",
            "px": "1.0000",
            "fillPx": "1.0000",
            "sz": "5000",
            "accFillSz": "5000",
            "state": "filled",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )

    status = risk.evaluate(state)

    assert status.ok is True
    assert status.allow_bid is True
    assert status.allow_ask is True
    assert status.runtime_state == "READY"


def test_risk_pauses_when_bot_short_cannot_rebalance_buy_side():
    risk = RiskManager(
        RiskConfig(min_free_quote_buffer=Decimal("1000"), daily_loss_limit_quote=Decimal("1000000")),
        TradingConfig(),
        mode="shadow",
    )
    state = make_state()
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "1",
            "clOrdId": "bot6ms-test",
            "px": "1.0000",
            "fillPx": "1.0000",
            "sz": "5000",
            "accFillSz": "5000",
            "state": "filled",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )
    state.balances["USDT"] = Balance(ccy="USDT", total=Decimal("500"), available=Decimal("500"))

    status = risk.evaluate(state)

    assert status.ok is False
    assert status.reason == "bot short rebalance blocked"
    assert status.runtime_state == "PAUSED"


def test_risk_pauses_when_bot_long_cannot_rebalance_sell_side():
    risk = RiskManager(
        RiskConfig(min_free_base_buffer=Decimal("1000"), daily_loss_limit_quote=Decimal("1000000")),
        TradingConfig(),
        mode="shadow",
    )
    state = make_state()
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "1",
            "clOrdId": "bot6mb-test",
            "px": "1.0000",
            "fillPx": "1.0000",
            "sz": "5000",
            "accFillSz": "5000",
            "state": "filled",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )
    state.balances["USDC"] = Balance(ccy="USDC", total=Decimal("500"), available=Decimal("500"))

    status = risk.evaluate(state)

    assert status.ok is False
    assert status.reason == "bot long rebalance blocked"
    assert status.runtime_state == "PAUSED"


def test_risk_stops_on_fee_gate():
    risk = RiskManager(RiskConfig(), TradingConfig(), mode="live")
    state = make_state()
    state.set_fee_snapshot(
        FeeSnapshot(
            inst_type="SPOT",
            inst_id="USDC-USDT",
            maker=Decimal("0.001"),
            taker=Decimal("0.001"),
            effective_maker=Decimal("0.001"),
            effective_taker=Decimal("0.001"),
            checked_at_ms=now_ms(),
        )
    )
    status = risk.evaluate(state)
    assert status.ok is False
    assert status.runtime_state == "STOPPED"


def test_risk_does_not_block_healthy_streams_after_old_reconnects():
    risk = RiskManager(RiskConfig(max_reconnects_per_5m=1), TradingConfig(), mode="live")
    state = make_state()
    state.mark_reconnect()
    state.mark_reconnect()
    status = risk.evaluate(state)
    assert status.ok is True


def test_risk_blocks_when_reconnects_high_and_stream_unhealthy():
    risk = RiskManager(RiskConfig(max_reconnects_per_5m=1), TradingConfig(), mode="live")
    state = make_state()
    state.mark_reconnect()
    state.mark_reconnect()
    state.set_stream_status("public_books5", False)
    status = risk.evaluate(state)
    assert status.ok is False
    assert status.reason == "streams not ready"


def test_risk_places_failures_enter_cooldown_then_auto_recover():
    risk = RiskManager(
        RiskConfig(max_consecutive_place_failures=1, place_failure_cooldown_seconds=5),
        TradingConfig(),
        mode="shadow",
    )
    state = make_state()
    state.record_place_result(False)

    status = risk.evaluate(state)
    assert status.ok is False
    assert "place failure cooldown" in status.reason

    state.last_place_failure_ms -= 6000
    recovered = risk.evaluate(state)
    assert recovered.ok is True
    assert state.consecutive_place_failures == 0


def test_risk_cancel_failures_enter_cooldown_then_auto_recover():
    risk = RiskManager(
        RiskConfig(max_consecutive_cancel_failures=1, cancel_failure_cooldown_seconds=5),
        TradingConfig(),
        mode="shadow",
    )
    state = make_state()
    state.record_cancel_result(False)

    status = risk.evaluate(state)
    assert status.ok is False
    assert "cancel failure cooldown" in status.reason

    state.last_cancel_failure_ms -= 6000
    recovered = risk.evaluate(state)
    assert recovered.ok is True
    assert state.consecutive_cancel_failures == 0
