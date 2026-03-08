import asyncio
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import ShadowConfig, TradingConfig
from src.models import Balance, BookLevel, BookSnapshot, InstrumentMeta, TradeTick
from src.shadow import ShadowFillSimulator
from src.state import BotState
from src.utils import build_cl_ord_id


class StubJournal:
    def __init__(self):
        self.events = []

    def append(self, event: str, payload: dict) -> None:
        self.events.append((event, payload))


def make_state(*, base_total: Decimal, quote_total: Decimal) -> BotState:
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
            bids=[BookLevel(price=Decimal("1"), size=Decimal("100"))],
            asks=[BookLevel(price=Decimal("1.0001"), size=Decimal("100"))],
        )
    )
    state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=base_total, available=base_total),
            "USDT": Balance(ccy="USDT", total=quote_total, available=quote_total),
        }
    )
    return state


def test_shadow_trade_fill_respects_queue_ahead():
    state = make_state(base_total=Decimal("0"), quote_total=Decimal("1000"))
    journal = StubJournal()
    simulator = ShadowFillSimulator(
        state=state,
        trading=TradingConfig(),
        config=ShadowConfig(min_rest_seconds=0, queue_ahead_fraction=Decimal("1")),
        journal=journal,
    )
    cl_ord_id = build_cl_ord_id("bot6", "buy")
    order = state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "",
            "clOrdId": cl_ord_id,
            "px": "1",
            "sz": "10",
            "accFillSz": "0",
            "state": "live",
            "cTime": "0",
            "uTime": "0",
        },
        source="shadow_place",
    )
    simulator.on_order_placed(order)

    assert state.free_balance("USDT") == Decimal("990")
    assert state.balances["USDT"].frozen == Decimal("10")
    assert order.queue_ahead_size == Decimal("100")

    asyncio.run(
        simulator.on_trade(
            TradeTick(ts_ms=2, received_ms=2, price=Decimal("1"), size=Decimal("60"), side="sell")
        )
    )
    assert order.queue_ahead_size == Decimal("40")
    assert cl_ord_id in state.live_orders

    asyncio.run(
        simulator.on_trade(
            TradeTick(ts_ms=3, received_ms=3, price=Decimal("1"), size=Decimal("50"), side="sell")
        )
    )

    assert cl_ord_id not in state.live_orders
    assert state.total_balance("USDT") == Decimal("990")
    assert state.free_balance("USDT") == Decimal("990")
    assert state.balances["USDT"].frozen == Decimal("0")
    assert state.total_balance("USDC") == Decimal("10")
    assert state.free_balance("USDC") == Decimal("10")
    assert state.shadow_fill_count == 1
    assert any(event == "shadow_fill" for event, _ in journal.events)


def test_shadow_cancel_releases_reserved_balance():
    state = make_state(base_total=Decimal("20"), quote_total=Decimal("1000"))
    journal = StubJournal()
    simulator = ShadowFillSimulator(
        state=state,
        trading=TradingConfig(),
        config=ShadowConfig(min_rest_seconds=0),
        journal=journal,
    )
    cl_ord_id = build_cl_ord_id("bot6", "sell")
    order = state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "",
            "clOrdId": cl_ord_id,
            "px": "1.0001",
            "sz": "5",
            "accFillSz": "0",
            "state": "live",
            "cTime": "0",
            "uTime": "0",
        },
        source="shadow_place",
    )
    simulator.on_order_placed(order)
    assert state.free_balance("USDC") == Decimal("15")
    assert state.balances["USDC"].frozen == Decimal("5")

    simulator.on_order_canceled(order, reason="test_cancel")
    state.live_orders.pop(order.cl_ord_id, None)

    assert state.free_balance("USDC") == Decimal("20")
    assert state.balances["USDC"].frozen == Decimal("0")
