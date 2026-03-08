import asyncio
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import BotConfig, ExchangeConfig
from src.executor import OrderExecutor
from src.models import Balance, InstrumentMeta, OrderIntent, QuoteDecision
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

    async def list_pending_orders(self, **kwargs):
        return []


class TrackingRest:
    def __init__(self):
        self.cancel_calls = []

    async def place_limit_order(self, **kwargs):
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

    async def cancel_order(self, **kwargs):
        return {}

    async def list_pending_orders(self, **kwargs):
        return []


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


def test_executor_cancels_same_order_after_ttl_when_enabled():
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

    assert len(rest.cancel_calls) == 1
    assert cl_ord_id not in state.live_orders


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


def test_executor_cancels_order_when_stale_book_cancel_enabled():
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

    assert len(rest.cancel_calls) == 1
    assert cl_ord_id not in state.live_orders


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

    assert state.consecutive_cancel_failures == 0
    assert cl_ord_id not in state.live_orders
    assert journal.events[-1][0] == "cancel_order_terminal"
    assert journal.events[-1][1]["okx"]["data"][0]["sCode"] == "51400"
    assert journal.events[-1][1]["reason_zh"] == "公共行情重连清理"
    assert "撤单时订单已终态" in journal.events[-1][1]["okx_zh"]


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
