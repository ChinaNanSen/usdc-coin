import asyncio
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import BotConfig, ExchangeConfig
from src.executor import OrderExecutor
from src.models import Balance, BookLevel, BookSnapshot, InstrumentMeta, OrderIntent, QuoteDecision
from src.models import RiskStatus
from src.okx_rest import OKXAPIError, OKXRestClient
from src.state import BotState
from src.utils import build_cl_ord_id


class StubJournal:
    def __init__(self):
        self.events = []

    def append(self, event: str, payload: dict) -> None:
        self.events.append((event, payload))


class FailingRest:
    async def place_limit_order(self, **kwargs):
        raise OKXAPIError(
            path="/api/v5/trade/order",
            code="51008",
            msg="Insufficient balance",
            data=[
                {
                    "sCode": "51008",
                    "sMsg": "Insufficient USDT balance",
                    "clOrdId": kwargs["cl_ord_id"],
                }
            ],
        )

    async def cancel_order(self, **kwargs):
        return {}

    async def amend_order(self, **kwargs):
        raise OKXAPIError(
            path="/api/v5/trade/amend-order",
            code="51008",
            msg="Insufficient balance",
            data=[
                {
                    "sCode": "51008",
                    "sMsg": "Insufficient USDT balance",
                    "clOrdId": kwargs.get("cl_ord_id", ""),
                }
            ],
        )

    async def list_pending_orders(self, **kwargs):
        return []


class TrackingRest:
    def __init__(self):
        self.cancel_calls = []
        self.amend_calls = []

    async def place_limit_order(self, **kwargs):
        return {}

    async def amend_order(self, **kwargs):
        self.amend_calls.append(kwargs)
        return {}

    async def cancel_order(self, **kwargs):
        self.cancel_calls.append(kwargs)
        return {}

    async def list_pending_orders(self, **kwargs):
        return []


class CapturingPlaceRest:
    def __init__(self):
        self.place_calls = []

    async def place_limit_order(self, **kwargs):
        self.place_calls.append(kwargs)
        return {}

    async def amend_order(self, **kwargs):
        return {}

    async def cancel_order(self, **kwargs):
        return {}

    async def list_pending_orders(self, **kwargs):
        return []


class FailingAmendRest(TrackingRest):
    async def amend_order(self, **kwargs):
        self.amend_calls.append(kwargs)
        raise OKXAPIError(
            path="/api/v5/trade/amend-order",
            code="51008",
            msg="Amend rejected",
            data=[
                {
                    "sCode": "51008",
                    "sMsg": "Order amend failed",
                    "clOrdId": kwargs.get("cl_ord_id", ""),
                }
            ],
        )


class AlreadyTerminalCancelRest:
    async def place_limit_order(self, **kwargs):
        return {}

    async def cancel_order(self, **kwargs):
        raise OKXAPIError(
            path="/api/v5/trade/cancel-order",
            code="1",
            msg="All operations failed",
            data=[
                {
                    "ordId": kwargs.get("ord_id") or "",
                    "sCode": "51400",
                    "sMsg": "Order cancellation failed as the order has been filled, canceled or does not exist.",
                }
            ],
            status_code=200,
        )

    async def list_pending_orders(self, **kwargs):
        return []


class DummyTradeOrderClient(OKXRestClient):
    async def _request(self, method, path, *, params=None, json_body=None, private=False):
        return [
            {
                "sCode": "51008",
                "sMsg": "Insufficient USDT balance",
                "clOrdId": json_body["clOrdId"],
            }
        ]


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
            ts_ms=1,
            received_ms=1,
            bids=[BookLevel(price=Decimal("1"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0001"), size=Decimal("100000"))],
        )
    )
    state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=Decimal("10000"), available=Decimal("10000")),
            "USDT": Balance(ccy="USDT", total=Decimal("10000"), available=Decimal("10000")),
        }
    )
    return state


def test_okx_api_error_formats_subcodes():
    exc = OKXAPIError.from_payload(
        path="/api/v5/trade/order",
        payload={
            "code": "1",
            "msg": "All operations failed",
            "data": [
                {
                    "sCode": "51008",
                    "sMsg": "Insufficient USDT balance",
                    "clOrdId": "bot6-buy-1",
                }
            ],
        },
        status_code=200,
    )

    rendered = str(exc)
    assert "code=1" in rendered
    assert "All operations failed" in rendered
    assert "sCode=51008" in rendered
    assert "Insufficient USDT balance" in rendered
    assert exc.to_dict()["data"][0]["clOrdId"] == "bot6-buy-1"


def test_place_limit_order_raises_on_inner_scode():
    client = DummyTradeOrderClient(ExchangeConfig(api_key="k", secret_key="s", passphrase="p"))

    async def run():
        try:
            await client.place_limit_order(
                inst_id="USDC-USDT",
                side="buy",
                price=Decimal("0.9999"),
                size=Decimal("10000"),
                cl_ord_id="bot6-buy-1",
            )
        finally:
            await client.close()

    try:
        asyncio.run(run())
        raised = False
    except OKXAPIError as exc:
        raised = True
        assert exc.code == "51008"
        assert "Insufficient USDT balance" in str(exc)
    assert raised is True


def test_amend_order_raises_on_inner_scode():
    client = DummyTradeOrderClient(ExchangeConfig(api_key="k", secret_key="s", passphrase="p"))

    async def run():
        try:
            await client.amend_order(
                inst_id="USDC-USDT",
                ord_id="123",
                cl_ord_id="bot6-buy-1",
                new_price=Decimal("1.0000"),
                new_size=Decimal("10000"),
            )
        finally:
            await client.close()

    try:
        asyncio.run(run())
        raised = False
    except OKXAPIError as exc:
        raised = True
        assert exc.code == "51008"
        assert "Insufficient USDT balance" in str(exc)
    assert raised is True


def test_executor_logs_structured_okx_error_payload():
    state = make_state()
    config = BotConfig(mode="live")
    journal = StubJournal()
    executor = OrderExecutor(rest=FailingRest(), state=state, config=config, journal=journal)

    async def run():
        await executor._reconcile_side(
            "buy",
            OrderIntent(side="buy", price=Decimal("0.9999"), quote_notional=Decimal("1000"), reason="test"),
        )

    asyncio.run(run())

    event, payload = journal.events[-1]
    assert event == "place_order_error"
    assert payload["okx"]["code"] == "51008"
    assert payload["okx"]["data"][0]["sMsg"] == "Insufficient USDT balance"


def test_executor_keeps_same_order_after_ttl_when_disabled():
    state = make_state()
    config = BotConfig(mode="live")
    config.trading.order_ttl_seconds = 1
    config.trading.cancel_on_ttl_expiry = False
    config.risk.min_free_quote_buffer = Decimal("0")
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    cl_ord_id = build_cl_ord_id("bot6", "buy")
    order = state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "123",
            "clOrdId": cl_ord_id,
            "px": "1",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )
    order.created_at_ms = 1

    async def run():
        await executor._reconcile_side(
            "buy",
            OrderIntent(side="buy", price=Decimal("1"), quote_notional=Decimal("10000"), reason="test"),
        )

    asyncio.run(run())

    assert rest.cancel_calls == []
    assert cl_ord_id in state.live_orders


def test_executor_keeps_same_order_after_ttl_even_when_enabled():
    state = make_state()
    config = BotConfig(mode="live")
    config.trading.order_ttl_seconds = 1
    config.trading.cancel_on_ttl_expiry = True
    config.risk.min_free_quote_buffer = Decimal("0")
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    cl_ord_id = build_cl_ord_id("bot6", "buy")
    order = state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "123",
            "clOrdId": cl_ord_id,
            "px": "1",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )
    order.created_at_ms = 1

    async def run():
        await executor._reconcile_side(
            "buy",
            OrderIntent(side="buy", price=Decimal("1"), quote_notional=Decimal("10000"), reason="test"),
        )

    asyncio.run(run())

    assert rest.cancel_calls == []
    assert cl_ord_id in state.live_orders
    assert state.live_orders[cl_ord_id].cancel_requested is False


def test_executor_keeps_order_when_book_is_stale_by_default():
    state = make_state()
    config = BotConfig(mode="live")
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    cl_ord_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "123",
            "clOrdId": cl_ord_id,
            "px": "1.0001",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )

    async def run():
        await executor.reconcile(
            QuoteDecision(reason="stale book: 16000ms", bid=None, ask=None),
            risk_status=RiskStatus(ok=False, reason="stale book: 16000ms", allow_bid=False, allow_ask=False, runtime_state="PAUSED"),
        )

    asyncio.run(run())

    assert rest.cancel_calls == []
    assert cl_ord_id in state.live_orders


def test_executor_keeps_order_when_stale_book_cancel_is_enabled_but_runtime_is_paused():
    state = make_state()
    config = BotConfig(mode="live")
    config.risk.cancel_orders_on_stale_book = True
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    cl_ord_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "123",
            "clOrdId": cl_ord_id,
            "px": "1.0001",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )

    async def run():
        await executor.reconcile(
            QuoteDecision(reason="stale book: 16000ms", bid=None, ask=None),
            risk_status=RiskStatus(ok=False, reason="stale book: 16000ms", allow_bid=False, allow_ask=False, runtime_state="PAUSED"),
        )

    asyncio.run(run())

    assert rest.cancel_calls == []
    assert cl_ord_id in state.live_orders
    assert state.live_orders[cl_ord_id].cancel_requested is False


def test_executor_treats_okx_51400_cancel_as_benign_terminal():
    state = make_state()
    config = BotConfig(mode="live")
    journal = StubJournal()
    rest = AlreadyTerminalCancelRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    cl_ord_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "123",
            "clOrdId": cl_ord_id,
            "px": "1",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )

    async def run():
        await executor._cancel_order(state.live_orders[cl_ord_id], reason="public_reconnect")

    asyncio.run(run())


def test_executor_preserves_rebalance_sell_queue_when_existing_order_price_is_better():
    state = make_state()
    config = BotConfig(mode="live")
    config.risk.min_free_base_buffer = Decimal("0")
    config.strategy.preserve_rebalance_queue = True
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)

    buy_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "b1",
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
    sell_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "s1",
            "clOrdId": sell_id,
            "px": "1.0001",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "3",
            "uTime": "3",
        },
        source="test",
    )

    async def run():
        await executor._reconcile_side(
            "sell",
            OrderIntent(side="sell", price=Decimal("1.0002"), quote_notional=Decimal("10002"), reason="rebalance_open_long", base_size=Decimal("10000")),
        )

    asyncio.run(run())

    assert rest.cancel_calls == []
    assert sell_id in state.live_orders


def test_executor_preserves_entry_buy_queue_when_old_price_still_has_min_spread():
    state = make_state()
    config = BotConfig(mode="live")
    config.risk.min_free_quote_buffer = Decimal("0")
    config.strategy.preserve_entry_queue = True
    state.set_book(
        state.book.__class__(
            ts_ms=1,
            received_ms=1,
            bids=state.book.bids,
            asks=[
                state.book.asks[0].__class__(price=Decimal("1.0001"), size=Decimal("100000"), order_count=0),
            ],
        )
    )
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    buy_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "b1",
            "clOrdId": buy_id,
            "px": "1",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )

    async def run():
        await executor._reconcile_side(
            "buy",
            OrderIntent(side="buy", price=Decimal("0.9999"), quote_notional=Decimal("10000"), reason="join_best_bid"),
        )

    asyncio.run(run())

    assert rest.cancel_calls == []
    assert buy_id in state.live_orders


def test_executor_does_not_preserve_entry_buy_queue_when_inventory_high():
    state = make_state()
    state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=Decimal("70000"), available=Decimal("70000")),
            "USDT": Balance(ccy="USDT", total=Decimal("30000"), available=Decimal("30000")),
        }
    )
    config = BotConfig(mode="live")
    config.risk.min_free_quote_buffer = Decimal("0")
    config.strategy.preserve_entry_queue = True
    state.set_book(
        state.book.__class__(
            ts_ms=1,
            received_ms=1,
            bids=state.book.bids,
            asks=[
                state.book.asks[0].__class__(price=Decimal("1.0001"), size=Decimal("100000"), order_count=0),
            ],
        )
    )
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    buy_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "b1",
            "clOrdId": buy_id,
            "px": "1",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )

    async def run():
        await executor._reconcile_side(
            "buy",
            OrderIntent(side="buy", price=Decimal("0.9999"), quote_notional=Decimal("10000"), reason="join_best_bid"),
        )

    asyncio.run(run())

    assert len(rest.amend_calls) == 1
    assert rest.cancel_calls == []
    assert buy_id in state.live_orders
    assert state.live_orders[buy_id].price == Decimal("0.9999")


def test_executor_preserves_entry_sell_queue_when_inventory_high():
    state = make_state()
    state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=Decimal("70000"), available=Decimal("70000")),
            "USDT": Balance(ccy="USDT", total=Decimal("30000"), available=Decimal("30000")),
        }
    )
    config = BotConfig(mode="live")
    config.risk.min_free_base_buffer = Decimal("0")
    config.strategy.preserve_entry_queue = True
    state.set_book(
        state.book.__class__(
            ts_ms=1,
            received_ms=1,
            bids=[
                state.book.bids[0].__class__(price=Decimal("0.9999"), size=Decimal("100000"), order_count=0),
            ],
            asks=[
                state.book.asks[0].__class__(price=Decimal("1.0001"), size=Decimal("100000"), order_count=0),
            ],
        )
    )
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    sell_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "s1",
            "clOrdId": sell_id,
            "px": "1.0000",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )

    async def run():
        await executor._reconcile_side(
            "sell",
            OrderIntent(side="sell", price=Decimal("1.0001"), quote_notional=Decimal("10000"), reason="join_best_ask"),
        )

    asyncio.run(run())

    assert rest.amend_calls == []
    assert rest.cancel_calls == []
    assert sell_id in state.live_orders
    assert state.live_orders[sell_id].price == Decimal("1.0000")


def test_executor_does_not_preserve_entry_sell_queue_when_inventory_low():
    state = make_state()
    state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=Decimal("30000"), available=Decimal("30000")),
            "USDT": Balance(ccy="USDT", total=Decimal("70000"), available=Decimal("70000")),
        }
    )
    config = BotConfig(mode="live")
    config.risk.min_free_base_buffer = Decimal("0")
    config.strategy.preserve_entry_queue = True
    state.set_book(
        state.book.__class__(
            ts_ms=1,
            received_ms=1,
            bids=[
                state.book.bids[0].__class__(price=Decimal("0.9999"), size=Decimal("100000"), order_count=0),
            ],
            asks=[
                state.book.asks[0].__class__(price=Decimal("1.0001"), size=Decimal("100000"), order_count=0),
            ],
        )
    )
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    sell_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "s1",
            "clOrdId": sell_id,
            "px": "1.0000",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )

    async def run():
        await executor._reconcile_side(
            "sell",
            OrderIntent(side="sell", price=Decimal("1.0001"), quote_notional=Decimal("10000"), reason="join_best_ask"),
        )

    asyncio.run(run())

    assert len(rest.amend_calls) == 1
    assert rest.cancel_calls == []
    assert sell_id in state.live_orders
    assert state.live_orders[sell_id].price == Decimal("1.0001")


def test_executor_amends_entry_buy_when_old_price_no_longer_matches_new_target():
    state = make_state()
    config = BotConfig(mode="live")
    config.risk.min_free_quote_buffer = Decimal("0")
    config.strategy.preserve_entry_queue = True
    state.set_book(
        state.book.__class__(
            ts_ms=1,
            received_ms=1,
            bids=[
                state.book.bids[0].__class__(price=Decimal("0.9999"), size=Decimal("100000"), order_count=0),
            ],
            asks=[
                state.book.asks[0].__class__(price=Decimal("1"), size=Decimal("100000"), order_count=0),
            ],
        )
    )
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    buy_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "b1",
            "clOrdId": buy_id,
            "px": "1",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )

    async def run():
        await executor._reconcile_side(
            "buy",
            OrderIntent(side="buy", price=Decimal("0.9999"), quote_notional=Decimal("10000"), reason="join_best_bid"),
        )

    asyncio.run(run())

    assert len(rest.amend_calls) == 1
    assert rest.cancel_calls == []
    assert buy_id in state.live_orders
    assert state.live_orders[buy_id].cancel_requested is False
    assert state.live_orders[buy_id].price == Decimal("0.9999")


def test_executor_reprices_existing_rebalance_sell_when_target_price_moves_higher():
    state = make_state()
    config = BotConfig(mode="live")
    config.risk.min_free_base_buffer = Decimal("0")
    config.strategy.preserve_rebalance_queue = True
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)

    buy_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "b1",
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
    sell_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "s1",
            "clOrdId": sell_id,
            "px": "1",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "3",
            "uTime": "3",
        },
        source="test",
    )

    async def run():
        await executor._reconcile_side(
            "sell",
            OrderIntent(side="sell", price=Decimal("1.0001"), quote_notional=Decimal("10001"), reason="rebalance_open_long", base_size=Decimal("10000")),
        )

    asyncio.run(run())

    assert len(rest.amend_calls) == 1
    assert rest.cancel_calls == []
    assert sell_id in state.live_orders
    assert state.live_orders[sell_id].cancel_requested is False
    assert state.live_orders[sell_id].price == Decimal("1.0001")


def test_executor_reprices_existing_buy_when_target_moves_higher_for_dynamic_quote():
    state = make_state()
    config = BotConfig(mode="live")
    config.risk.min_free_quote_buffer = Decimal("0")
    config.strategy.preserve_entry_queue = True
    state.set_book(
        state.book.__class__(
            ts_ms=1,
            received_ms=1,
            bids=[
                state.book.bids[0].__class__(price=Decimal("0.9999"), size=Decimal("100000"), order_count=0),
            ],
            asks=[
                state.book.asks[0].__class__(price=Decimal("1.0001"), size=Decimal("100000"), order_count=0),
            ],
        )
    )
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    buy_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "b1",
            "clOrdId": buy_id,
            "px": "0.9998",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )

    async def run():
        await executor._reconcile_side(
            "buy",
            OrderIntent(side="buy", price=Decimal("0.9999"), quote_notional=Decimal("9999"), reason="join_best_bid"),
        )

    asyncio.run(run())

    assert len(rest.amend_calls) == 1
    assert rest.cancel_calls == []
    assert buy_id in state.live_orders
    assert state.live_orders[buy_id].cancel_requested is False
    assert state.live_orders[buy_id].price == Decimal("0.9999")


def test_executor_amends_partially_filled_sell_using_total_order_size():
    state = make_state()
    config = BotConfig(mode="live")
    config.risk.min_free_base_buffer = Decimal("0")
    config.strategy.preserve_rebalance_queue = False
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    sell_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "s1",
            "clOrdId": sell_id,
            "px": "1.0000",
            "sz": "10000",
            "accFillSz": "3600",
            "state": "partially_filled",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )

    async def run():
        await executor._reconcile_side(
            "sell",
            OrderIntent(
                side="sell",
                price=Decimal("1.0001"),
                quote_notional=Decimal("5000.5"),
                base_size=Decimal("5000"),
                reason="rebalance_open_long",
            ),
        )

    asyncio.run(run())

    assert len(rest.amend_calls) == 1
    assert rest.amend_calls[0]["new_size"] == Decimal("8600")
    assert rest.cancel_calls == []
    assert sell_id in state.live_orders
    assert state.live_orders[sell_id].price == Decimal("1.0001")
    assert state.live_orders[sell_id].size == Decimal("8600")
    assert state.live_orders[sell_id].remaining_size == Decimal("5000")


def test_executor_falls_back_to_cancel_when_amend_fails():
    state = make_state()
    config = BotConfig(mode="live")
    config.risk.min_free_quote_buffer = Decimal("0")
    config.strategy.preserve_entry_queue = False
    journal = StubJournal()
    rest = FailingAmendRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    buy_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "b1",
            "clOrdId": buy_id,
            "px": "0.9998",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )

    async def run():
        await executor._reconcile_side(
            "buy",
            OrderIntent(side="buy", price=Decimal("0.9999"), quote_notional=Decimal("9999"), reason="join_best_bid"),
        )

    asyncio.run(run())

    assert len(rest.amend_calls) == 1
    assert len(rest.cancel_calls) == 1
    assert buy_id in state.live_orders
    assert state.live_orders[buy_id].cancel_requested is True


def test_executor_caps_buy_size_by_available_quote_balance():
    state = make_state()
    state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=Decimal("10000"), available=Decimal("10000")),
            "USDT": Balance(ccy="USDT", total=Decimal("6000"), available=Decimal("6000")),
        }
    )
    config = BotConfig(mode="live")
    journal = StubJournal()
    rest = CapturingPlaceRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)

    async def run():
        await executor._reconcile_side(
            "buy",
            OrderIntent(side="buy", price=Decimal("1"), quote_notional=Decimal("10000"), reason="test"),
        )

    asyncio.run(run())

    assert len(rest.place_calls) == 1
    assert rest.place_calls[0]["size"] == Decimal("5000")
    assert rest.place_calls[0]["post_only"] is False


def test_executor_keeps_live_order_when_streams_are_not_ready():
    state = make_state()
    config = BotConfig(mode="live")
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    cl_ord_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "123",
            "clOrdId": cl_ord_id,
            "px": "1.0001",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )

    async def run():
        await executor.reconcile(
            QuoteDecision(reason="streams not ready", bid=None, ask=None),
            risk_status=RiskStatus(ok=False, reason="streams not ready", allow_bid=False, allow_ask=False, runtime_state="INIT"),
        )

    asyncio.run(run())

    assert rest.cancel_calls == []
    assert cl_ord_id in state.live_orders


def test_executor_keeps_partially_filled_order_when_remaining_matches_target():
    state = make_state()
    config = BotConfig(mode="live")
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    cl_ord_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "123",
            "clOrdId": cl_ord_id,
            "px": "1",
            "sz": "10000",
            "accFillSz": "3600",
            "state": "partially_filled",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )

    async def run():
        await executor._reconcile_side(
            "sell",
            OrderIntent(
                side="sell",
                price=Decimal("1"),
                quote_notional=Decimal("6400"),
                base_size=Decimal("6400"),
                reason="rebalance_open_long",
            ),
        )

    asyncio.run(run())

    assert rest.cancel_calls == []
    assert cl_ord_id in state.live_orders


def test_executor_keeps_partially_filled_order_when_remaining_is_smaller_but_price_same():
    state = make_state()
    config = BotConfig(mode="live")
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    cl_ord_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "123",
            "clOrdId": cl_ord_id,
            "px": "1.0001",
            "sz": "10000",
            "accFillSz": "3600",
            "state": "partially_filled",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )

    async def run():
        await executor._reconcile_side(
            "sell",
            OrderIntent(
                side="sell",
                price=Decimal("1.0001"),
                quote_notional=Decimal("10001"),
                base_size=Decimal("10000"),
                reason="join_best_ask",
            ),
        )

    asyncio.run(run())

    assert rest.cancel_calls == []
    assert cl_ord_id in state.live_orders


def test_executor_keeps_partially_filled_sell_without_intent_when_risk_still_allows_ask():
    state = make_state()
    config = BotConfig(mode="live")
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    cl_ord_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "123",
            "clOrdId": cl_ord_id,
            "px": "1.0001",
            "sz": "10000",
            "accFillSz": "1200",
            "state": "partially_filled",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )

    async def run():
        await executor.reconcile(
            QuoteDecision(reason="reduce_only_inventory_high", bid=None, ask=None),
            risk_status=RiskStatus(
                ok=True,
                reason="reduce_only_inventory_high",
                allow_bid=False,
                allow_ask=True,
                runtime_state="REDUCE_ONLY",
            ),
        )

    asyncio.run(run())

    assert rest.cancel_calls == []
    assert cl_ord_id in state.live_orders
    assert state.live_orders[cl_ord_id].cancel_requested is False


def test_cancel_request_keeps_order_for_late_fill_delta_accounting():
    state = make_state()
    config = BotConfig(mode="live")
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    cl_ord_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "123",
            "clOrdId": cl_ord_id,
            "px": "1",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "123",
            "clOrdId": cl_ord_id,
            "px": "1",
            "sz": "10000",
            "accFillSz": "2000",
            "fillPx": "1",
            "state": "partially_filled",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )

    async def run():
        await executor._cancel_order(state.live_orders[cl_ord_id], reason="side_disabled")

    asyncio.run(run())

    assert len(rest.cancel_calls) == 1
    assert cl_ord_id in state.live_orders
    assert state.live_orders[cl_ord_id].cancel_requested is True

    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "123",
            "clOrdId": cl_ord_id,
            "px": "1",
            "sz": "10000",
            "accFillSz": "5000",
            "fillPx": "1",
            "state": "partially_filled",
            "cTime": "1",
            "uTime": "3",
        },
        source="test",
    )

    assert state.strategy_position_base() == Decimal("5000")
    assert state.observed_fill_count == 2
    assert state.observed_fill_volume_quote == Decimal("5000")


def test_executor_keeps_buy_order_when_only_own_frozen_quote_makes_available_look_low():
    state = make_state()
    state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=Decimal("13008.69913"), available=Decimal("13008.69913")),
            "USDT": Balance(ccy="USDT", total=Decimal("12004.728825776494"), available=Decimal("2004.728825776494"), frozen=Decimal("10000")),
        }
    )
    config = BotConfig(mode="live")
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    cl_ord_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "buy-1",
            "clOrdId": cl_ord_id,
            "px": "1",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )

    async def run():
        await executor._reconcile_side(
            "buy",
            OrderIntent(side="buy", price=Decimal("1"), quote_notional=Decimal("10000"), reason="join_best_bid"),
        )

    asyncio.run(run())

    assert rest.cancel_calls == []
    assert cl_ord_id in state.live_orders


def test_executor_keeps_sell_order_when_only_own_frozen_base_makes_available_look_low():
    state = make_state()
    state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=Decimal("13008.69913"), available=Decimal("3009.699031"), frozen=Decimal("9999.000099")),
            "USDT": Balance(ccy="USDT", total=Decimal("12004.728825776494"), available=Decimal("12004.728825776494")),
        }
    )
    config = BotConfig(mode="live")
    journal = StubJournal()
    rest = TrackingRest()
    executor = OrderExecutor(rest=rest, state=state, config=config, journal=journal)
    cl_ord_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "sell-1",
            "clOrdId": cl_ord_id,
            "px": "1.0001",
            "sz": "9999.000099",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )

    async def run():
        await executor._reconcile_side(
            "sell",
            OrderIntent(side="sell", price=Decimal("1.0001"), quote_notional=Decimal("10000"), reason="join_best_ask"),
        )

    asyncio.run(run())

    assert rest.cancel_calls == []
    assert cl_ord_id in state.live_orders
