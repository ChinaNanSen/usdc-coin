"""
Tests for A model's fix: preserve partially-filled orders from side_disabled cancellation.

The fix has two parts:
1. executor._should_keep_order_without_intent: keeps partial-fill orders alive
2. strategy.strict_alternating_sides: prevents strategy from flip-flopping sides

We test both independently and together.
"""
import asyncio
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import BotConfig, StrategyConfig, TradingConfig, RiskConfig
from src.executor import OrderExecutor, JournalWriter
from src.models import (
    Balance, BookLevel, BookSnapshot, InstrumentMeta,
    LiveOrder, OrderIntent, QuoteDecision, RiskStatus,
)
from src.state import BotState
from src.strategy import MicroMakerStrategy
from src.utils import build_cl_ord_id, now_ms


class StubJournal:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def append(self, event: str, payload: dict) -> None:
        self.events.append((event, payload))


class StubRest:
    """Minimal stub so OrderExecutor doesn't need a real REST client."""
    async def cancel_order(self, **kwargs):
        pass

    async def place_limit_order(self, **kwargs):
        return {"ordId": "fake_ord_123"}

    async def close(self):
        pass


def make_state() -> BotState:
    state = BotState(managed_prefix="bot6", state_path="data/test_state.json")
    state.set_instrument(
        InstrumentMeta(
            inst_id="USDC-USDT", inst_type="SPOT",
            base_ccy="USDC", quote_ccy="USDT",
            tick_size=Decimal("0.0001"), lot_size=Decimal("0.000001"),
            min_size=Decimal("1"),
            max_market_amount=Decimal("1000000"),
            max_limit_amount=Decimal("20000000"),
        )
    )
    state.set_book(BookSnapshot(
        ts_ms=now_ms(),
        bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
        asks=[BookLevel(price=Decimal("1.0001"), size=Decimal("100000"))],
    ))
    state.set_balances({
        "USDC": Balance(ccy="USDC", total=Decimal("50000"), available=Decimal("50000")),
        "USDT": Balance(ccy="USDT", total=Decimal("50000"), available=Decimal("50000")),
    })
    return state


def make_executor(state: BotState, config: BotConfig | None = None) -> tuple[OrderExecutor, StubJournal]:
    if config is None:
        config = BotConfig(mode="shadow")
    journal = StubJournal()
    executor = OrderExecutor(
        rest=StubRest(),
        state=state,
        config=config,
        journal=journal,
    )
    return executor, journal


def inject_live_order(state: BotState, *, side: str, price: str, size: str,
                      filled: str = "0", cl_ord_id: str | None = None) -> LiveOrder:
    """Inject a managed order into state.live_orders directly."""
    if cl_ord_id is None:
        cl_ord_id = build_cl_ord_id("bot6", side)
    order = LiveOrder(
        inst_id="USDC-USDT", side=side, ord_id="fake_ord",
        cl_ord_id=cl_ord_id, price=Decimal(price), size=Decimal(size),
        filled_size=Decimal(filled), state="partially_filled" if Decimal(filled) > 0 else "live",
        created_at_ms=now_ms() - 5000, updated_at_ms=now_ms(),
        source="test",
    )
    state.live_orders[cl_ord_id] = order
    return order


# ============================================================
# Part 1: _should_keep_order_without_intent tests
# ============================================================

def test_keep_partial_fill_when_risk_ok_and_side_allowed():
    """
    Core fix: a sell order with partial fill should NOT be canceled
    when risk is ok and the sell side is allowed, even though
    strategy says intent=None for that side.
    """
    state = make_state()
    executor, journal = make_executor(state)

    # Sell order partially filled (3000 of 10000)
    order = inject_live_order(state, side="sell", price="1.0001", size="10000", filled="3000")

    risk = RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True)
    result = executor._should_keep_order_without_intent(primary=order, risk_status=risk)
    assert result is True, "Partial-fill sell should be kept when risk ok and ask allowed"


def test_keep_partial_fill_buy_when_risk_ok_and_bid_allowed():
    """Same for buy side."""
    state = make_state()
    executor, journal = make_executor(state)

    order = inject_live_order(state, side="buy", price="0.9999", size="10000", filled="5000")

    risk = RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True)
    result = executor._should_keep_order_without_intent(primary=order, risk_status=risk)
    assert result is True, "Partial-fill buy should be kept when risk ok and bid allowed"


def test_do_not_keep_partial_fill_when_side_blocked_by_risk():
    """
    If risk says allow_ask=False (e.g. REDUCE_ONLY inventory_low),
    a partial-fill sell should NOT be kept — risk overrides.
    """
    state = make_state()
    executor, journal = make_executor(state)

    order = inject_live_order(state, side="sell", price="1.0001", size="10000", filled="3000")

    risk = RiskStatus(ok=True, reason="reduce_only_inventory_low",
                      allow_bid=True, allow_ask=False, runtime_state="REDUCE_ONLY")
    result = executor._should_keep_order_without_intent(primary=order, risk_status=risk)
    assert result is False, "Partial-fill sell should NOT be kept when ask is blocked by risk"


def test_do_not_keep_zero_fill_order():
    """An unfilled order should not be protected by the partial-fill logic."""
    state = make_state()
    executor, journal = make_executor(state)

    order = inject_live_order(state, side="sell", price="1.0001", size="10000", filled="0")

    risk = RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True)
    result = executor._should_keep_order_without_intent(primary=order, risk_status=risk)
    assert result is False, "Zero-fill order should not be kept by partial-fill logic"


def test_keep_order_in_paused_state_regardless_of_fill():
    """PAUSED state always keeps orders (existing behavior, not new)."""
    state = make_state()
    executor, journal = make_executor(state)

    order = inject_live_order(state, side="sell", price="1.0001", size="10000", filled="0")

    risk = RiskStatus(ok=False, reason="pause active", allow_bid=False, allow_ask=False, runtime_state="PAUSED")
    result = executor._should_keep_order_without_intent(primary=order, risk_status=risk)
    assert result is True, "PAUSED always keeps orders"


def test_do_not_keep_partial_fill_when_risk_not_ok():
    """
    If risk.ok is False (not just side-blocked, but globally not ok),
    the partial-fill check should not trigger because the condition
    requires risk_status.ok to be True.
    """
    state = make_state()
    executor, journal = make_executor(state)

    order = inject_live_order(state, side="sell", price="1.0001", size="10000", filled="5000")

    # risk.ok=False but not PAUSED/INIT — e.g. "spread too tight" or similar
    risk = RiskStatus(ok=False, reason="spread too tight", allow_bid=False, allow_ask=False, runtime_state="READY")
    result = executor._should_keep_order_without_intent(primary=order, risk_status=risk)
    assert result is False, "Partial-fill should not be kept when risk.ok is False and not PAUSED"


# ============================================================
# Part 2: _reconcile_side integration — verify cancel is skipped
# ============================================================

def test_reconcile_skips_cancel_for_partial_fill_sell_with_no_intent():
    """
    Full integration: when strategy returns intent=None for sell side,
    but there's a partially-filled sell order, reconcile should NOT cancel it.
    """
    state = make_state()
    config = BotConfig(mode="shadow")
    executor, journal = make_executor(state, config)

    order = inject_live_order(state, side="sell", price="1.0001", size="10000", filled="3000")

    risk = RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True)

    # intent=None means strategy doesn't want a sell order
    asyncio.run(executor._reconcile_side("sell", None, risk_status=risk))

    # The order should still be alive
    assert order.cl_ord_id in state.live_orders, "Partial-fill order should NOT be canceled"
    cancel_events = [e for e in journal.events if e[0] in ("cancel_order", "shadow_cancel")]
    assert len(cancel_events) == 0, f"No cancel should happen, got: {cancel_events}"


def test_reconcile_cancels_zero_fill_sell_with_no_intent():
    """
    Contrast: when there's NO partial fill, side_disabled cancel should proceed.
    """
    state = make_state()
    config = BotConfig(mode="shadow")
    executor, journal = make_executor(state, config)

    order = inject_live_order(state, side="sell", price="1.0001", size="10000", filled="0")

    risk = RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True)

    asyncio.run(executor._reconcile_side("sell", None, risk_status=risk))

    # The order should be canceled
    assert order.cl_ord_id not in state.live_orders, "Zero-fill order should be canceled"
    cancel_events = [e for e in journal.events if e[0] == "shadow_cancel"]
    assert len(cancel_events) == 1
    assert cancel_events[0][1]["reason"] == "side_disabled"


# ============================================================
# Part 3: strict_alternating_sides strategy tests
# ============================================================

def test_strict_cycle_keeps_sell_intent_while_sell_order_filling():
    """
    With strict_alternating_sides, if a sell order is partially filled,
    the strategy should keep producing sell intent (not flip to buy).
    This is the key interaction: strategy keeps intent → executor keeps order.
    """
    strategy = MicroMakerStrategy(
        StrategyConfig(strict_alternating_sides=True, normal_sell_price_floor=Decimal("1.0001")),
        TradingConfig(entry_base_size=Decimal("10000")),
    )
    state = make_state()

    # Simulate: bot bought 10000 USDC, now has position +10000, needs to sell
    cl_buy = build_cl_ord_id("bot6", "buy")
    state.apply_order_update({
        "instId": "USDC-USDT", "side": "buy", "ordId": "1",
        "clOrdId": cl_buy, "px": "1", "fillPx": "1",
        "sz": "10000", "accFillSz": "10000", "state": "filled",
        "cTime": "1", "uTime": "2",
    }, source="test")

    # Now there's a sell order partially filled
    cl_sell = build_cl_ord_id("bot6", "sell")
    state.apply_order_update({
        "instId": "USDC-USDT", "side": "sell", "ordId": "2",
        "clOrdId": cl_sell, "px": "1.0001", "fillPx": "1.0001",
        "sz": "10000", "accFillSz": "3000", "state": "partially_filled",
        "cTime": "3", "uTime": "4",
    }, source="test")

    # The sell order is still live
    state.live_orders[cl_sell] = LiveOrder(
        inst_id="USDC-USDT", side="sell", ord_id="2", cl_ord_id=cl_sell,
        price=Decimal("1.0001"), size=Decimal("10000"), filled_size=Decimal("3000"),
        state="partially_filled", created_at_ms=3, updated_at_ms=4, source="test",
    )

    risk = RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True)
    decision = strategy.decide(state, risk)

    # strict_alternating_sides should see the partially-filled sell and keep sell intent
    assert decision.ask is not None, "Strategy should still want to sell (rebalance)"
    # Position is +10000 - 3000 = +7000, so rebalance_sell_base = 7000
    assert decision.ask.base_size == Decimal("7000")


def test_strict_cycle_no_live_orders_alternates_after_last_buy():
    """After a buy fill completes, strict cycle should want to sell next."""
    strategy = MicroMakerStrategy(
        StrategyConfig(strict_alternating_sides=True, normal_sell_price_floor=Decimal("1.0001")),
        TradingConfig(entry_base_size=Decimal("10000")),
    )
    state = make_state()

    # Last trade was a buy
    cl_buy = build_cl_ord_id("bot6", "buy")
    state.apply_order_update({
        "instId": "USDC-USDT", "side": "buy", "ordId": "1",
        "clOrdId": cl_buy, "px": "1", "fillPx": "1",
        "sz": "10000", "accFillSz": "10000", "state": "filled",
        "cTime": "1", "uTime": "2",
    }, source="test")

    # No live orders
    assert len(state.bot_orders()) == 0

    risk = RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True)
    decision = strategy.decide(state, risk)

    assert decision.bid is None, "Should not buy after last trade was buy"
    assert decision.ask is not None, "Should sell after last trade was buy"


def test_strict_cycle_with_live_unfilled_order_stays_on_same_side():
    """
    If there's a live unfilled order, strict cycle should stay on that side.
    This prevents the strategy from flip-flopping.
    """
    strategy = MicroMakerStrategy(
        StrategyConfig(strict_alternating_sides=True),
        TradingConfig(entry_base_size=Decimal("10000")),
    )
    state = make_state()

    # Live buy order, not filled yet
    cl_buy = build_cl_ord_id("bot6", "buy")
    inject_live_order(state, side="buy", price="0.9999", size="10000", filled="0", cl_ord_id=cl_buy)

    risk = RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True)
    decision = strategy.decide(state, risk)

    # Should stay on buy side (the live order's side)
    assert decision.bid is not None, "Should keep buy intent for live buy order"
    assert decision.ask is None, "Should not produce sell intent"


# ============================================================
# Part 4: Edge cases and potential issues
# ============================================================

def test_partial_fill_kept_even_in_reduce_only_if_side_matches():
    """
    REDUCE_ONLY with inventory_high: allow_ask=True, allow_bid=False.
    A partially-filled sell order should be kept (sell is allowed).
    """
    state = make_state()
    executor, journal = make_executor(state)

    order = inject_live_order(state, side="sell", price="1.0001", size="10000", filled="5000")

    risk = RiskStatus(ok=True, reason="reduce_only_inventory_high",
                      allow_bid=False, allow_ask=True, runtime_state="REDUCE_ONLY")
    result = executor._should_keep_order_without_intent(primary=order, risk_status=risk)
    assert result is True, "Partial-fill sell should be kept in REDUCE_ONLY when ask is allowed"


def test_partial_fill_buy_not_kept_in_reduce_only_inventory_high():
    """
    REDUCE_ONLY with inventory_high: allow_bid=False.
    A partially-filled BUY order should NOT be kept — buying more
    would make inventory worse.
    """
    state = make_state()
    executor, journal = make_executor(state)

    order = inject_live_order(state, side="buy", price="0.9999", size="10000", filled="5000")

    risk = RiskStatus(ok=True, reason="reduce_only_inventory_high",
                      allow_bid=False, allow_ask=True, runtime_state="REDUCE_ONLY")
    result = executor._should_keep_order_without_intent(primary=order, risk_status=risk)
    assert result is False, "Partial-fill buy should NOT be kept when bid is blocked"


def test_stale_book_keeps_order_regardless_of_fill():
    """Stale book with cancel_orders_on_stale_book=False keeps all orders."""
    state = make_state()
    config = BotConfig(mode="shadow")
    config.risk.cancel_orders_on_stale_book = False
    executor, journal = make_executor(state, config)

    order = inject_live_order(state, side="sell", price="1.0001", size="10000", filled="0")

    risk = RiskStatus(ok=False, reason="stale book: 20000ms",
                      allow_bid=False, allow_ask=False, runtime_state="PAUSED")
    result = executor._should_keep_order_without_intent(primary=order, risk_status=risk)
    assert result is True, "Stale book should keep orders when cancel_orders_on_stale_book=False"
