from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import Balance, BookLevel, BookSnapshot, InstrumentMeta
from src.state import BotState


def test_live_order_update_tracks_observed_fills():
    state = BotState(managed_prefix="bot6", state_path="data/test_state.json")
    state.set_instrument(
        InstrumentMeta(
            inst_id="USDC-USDT",
            inst_type="SPOT",
            base_ccy="USDC",
            quote_ccy="USDT",
            tick_size=Decimal("0.0001"),
            lot_size=Decimal("1"),
            min_size=Decimal("1"),
            max_market_amount=Decimal("1000000"),
            max_limit_amount=Decimal("20000000"),
        )
    )
    state.set_book(
        BookSnapshot(
            ts_ms=1,
            received_ms=1,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("1000"))],
            asks=[BookLevel(price=Decimal("1"), size=Decimal("1000"))],
        )
    )
    state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=Decimal("10000"), available=Decimal("10000")),
            "USDT": Balance(ccy="USDT", total=Decimal("10000"), available=Decimal("10000")),
        }
    )

    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "1",
            "clOrdId": "bot6mbabc123",
            "px": "1",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1000",
            "uTime": "1000",
        },
        source="ws_order",
    )
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "1",
            "clOrdId": "bot6mbabc123",
            "px": "1",
            "sz": "10000",
            "accFillSz": "10000",
            "fillPx": "1",
            "state": "filled",
            "cTime": "1000",
            "uTime": "2000",
        },
        source="ws_order",
    )

    assert state.observed_fill_count == 1
    assert state.observed_fill_volume_quote == Decimal("10000")


def test_live_order_update_opens_short_when_selling_startup_inventory():
    state = BotState(managed_prefix="bot6", state_path="data/test_state.json")
    state.set_instrument(
        InstrumentMeta(
            inst_id="USDC-USDT",
            inst_type="SPOT",
            base_ccy="USDC",
            quote_ccy="USDT",
            tick_size=Decimal("0.0001"),
            lot_size=Decimal("1"),
            min_size=Decimal("1"),
            max_market_amount=Decimal("1000000"),
            max_limit_amount=Decimal("20000000"),
        )
    )
    state.set_book(
        BookSnapshot(
            ts_ms=1,
            received_ms=1,
            bids=[BookLevel(price=Decimal("1"), size=Decimal("1000"))],
            asks=[BookLevel(price=Decimal("1.0001"), size=Decimal("1000"))],
        )
    )
    state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=Decimal("10000"), available=Decimal("10000")),
            "USDT": Balance(ccy="USDT", total=Decimal("10000"), available=Decimal("10000")),
        }
    )

    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "1",
            "clOrdId": "bot6msabc123",
            "px": "1.0001",
            "sz": "3000",
            "accFillSz": "3000",
            "fillPx": "1.0001",
            "state": "filled",
            "cTime": "1000",
            "uTime": "2000",
        },
        source="ws_order",
    )

    assert state.strategy_position_base() == Decimal("-3000")
    assert list(state.live_position_lots) != []
    assert state.live_realized_pnl_quote == Decimal("0")


def test_live_order_update_realizes_pnl_when_startup_inventory_is_bought_back():
    state = BotState(managed_prefix="bot6", state_path="data/test_state.json")
    state.set_instrument(
        InstrumentMeta(
            inst_id="USDC-USDT",
            inst_type="SPOT",
            base_ccy="USDC",
            quote_ccy="USDT",
            tick_size=Decimal("0.0001"),
            lot_size=Decimal("1"),
            min_size=Decimal("1"),
            max_market_amount=Decimal("1000000"),
            max_limit_amount=Decimal("20000000"),
        )
    )
    state.set_book(
        BookSnapshot(
            ts_ms=1,
            received_ms=1,
            bids=[BookLevel(price=Decimal("1"), size=Decimal("1000"))],
            asks=[BookLevel(price=Decimal("1.0001"), size=Decimal("1000"))],
        )
    )
    state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=Decimal("10000"), available=Decimal("10000")),
            "USDT": Balance(ccy="USDT", total=Decimal("10000"), available=Decimal("10000")),
        }
    )

    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "1",
            "clOrdId": "bot6msabc123",
            "px": "1.0001",
            "sz": "10000",
            "accFillSz": "10000",
            "fillPx": "1.0001",
            "state": "filled",
            "cTime": "1000",
            "uTime": "2000",
        },
        source="ws_order",
    )
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "2",
            "clOrdId": "bot6mbabc123",
            "px": "1",
            "sz": "10000",
            "accFillSz": "10000",
            "fillPx": "1",
            "state": "filled",
            "cTime": "3000",
            "uTime": "4000",
        },
        source="ws_order",
    )

    assert state.strategy_position_base() == Decimal("0")
    assert list(state.live_position_lots) == []
    assert state.live_realized_pnl_quote == Decimal("1")
