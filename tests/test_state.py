from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import Balance, BookLevel, BookSnapshot, InstrumentMeta
from src.state import BotState
from src.utils import build_cl_ord_id


def test_initial_nav_waits_for_balances():
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

    assert state.initial_nav_quote is None
    assert state.shadow_base_cost_quote is None

    state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=Decimal("50000"), available=Decimal("50000")),
            "USDT": Balance(ccy="USDT", total=Decimal("50000"), available=Decimal("50000")),
        }
    )

    assert state.initial_nav_quote == Decimal("99997.5")
    assert state.shadow_base_cost_quote == Decimal("49997.5")


def test_live_pnl_tracks_realized_and_unrealized_from_managed_fills():
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
            ts_ms=1,
            received_ms=1,
            bids=[BookLevel(price=Decimal("1"), size=Decimal("1000"))],
            asks=[BookLevel(price=Decimal("1.0001"), size=Decimal("1000"))],
        )
    )
    state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=Decimal("50000"), available=Decimal("50000")),
            "USDT": Balance(ccy="USDT", total=Decimal("50000"), available=Decimal("50000")),
        }
    )

    buy_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "1",
            "clOrdId": buy_id,
            "px": "1",
            "fillPx": "1",
            "sz": "10000",
            "accFillSz": "10000",
            "state": "filled",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )

    assert state.strategy_position_base() == Decimal("10000")
    assert state.live_realized_pnl_quote == Decimal("0")
    assert state.live_unrealized_pnl_quote() == Decimal("0.5")
    assert state.last_trade is not None
    assert state.last_trade.order_price == Decimal("1")
    assert state.last_trade.price == Decimal("1")

    sell_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "2",
            "clOrdId": sell_id,
            "px": "1.0001",
            "fillPx": "1.0001",
            "sz": "10000",
            "accFillSz": "10000",
            "state": "filled",
            "cTime": "3",
            "uTime": "4",
        },
        source="test",
    )

    assert state.strategy_position_base() == Decimal("0")
    assert state.live_realized_pnl_quote == Decimal("1")
    assert state.live_unrealized_pnl_quote() == Decimal("0")
    assert state.last_trade is not None
    assert state.last_trade.order_price == Decimal("1.0001")
    assert state.last_trade.price == Decimal("1.0001")
