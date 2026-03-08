from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import StrategyConfig, TradingConfig
from src.models import Balance, BookLevel, BookSnapshot, InstrumentMeta, RiskStatus
from src.state import BotState
from src.strategy import MicroMakerStrategy
from src.utils import build_cl_ord_id


def build_state(base_balance: str, quote_balance: str, depth_size: str = "100000") -> BotState:
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
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal(depth_size))],
            asks=[BookLevel(price=Decimal("1.0000"), size=Decimal(depth_size))],
        )
    )
    state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=Decimal(base_balance), available=Decimal(base_balance)),
            "USDT": Balance(ccy="USDT", total=Decimal(quote_balance), available=Decimal(quote_balance)),
        }
    )
    return state


def test_strategy_quotes_both_sides_near_target_inventory():
    strategy = MicroMakerStrategy(StrategyConfig(), TradingConfig())
    decision = strategy.decide(
        build_state("50000", "50000"),
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )
    assert decision.bid is not None
    assert decision.ask is not None
    assert decision.reason == "two_sided"


def test_strategy_turns_into_ask_only_when_inventory_high():
    strategy = MicroMakerStrategy(StrategyConfig(), TradingConfig())
    decision = strategy.decide(
        build_state("80000", "20000"),
        RiskStatus(ok=True, reason="ok", allow_bid=False, allow_ask=True, runtime_state="REDUCE_ONLY"),
    )
    assert decision.bid is None
    assert decision.ask is not None
    assert decision.reason == "inventory_high_ask_only"


def test_strategy_blocks_when_visible_depth_is_too_thin():
    strategy = MicroMakerStrategy(StrategyConfig(min_visible_depth_multiplier=Decimal("3")), TradingConfig(quote_size=Decimal("10000")))
    decision = strategy.decide(
        build_state("50000", "50000", depth_size="1000"),
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )
    assert decision.bid is None
    assert decision.ask is None
    assert "visible depth too thin" in decision.reason


def test_strategy_uses_soft_band_to_disable_bid():
    strategy = MicroMakerStrategy(StrategyConfig(), TradingConfig())
    decision = strategy.decide(
        build_state("70000", "30000"),
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )
    assert decision.bid is None
    assert decision.ask is not None


def test_strategy_uses_exact_fill_size_to_rebalance_open_long():
    strategy = MicroMakerStrategy(StrategyConfig(), TradingConfig())
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("1"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0001"), size=Decimal("100000"))],
        )
    )
    cl_ord_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "1",
            "clOrdId": cl_ord_id,
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

    decision = strategy.decide(state, RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True))

    assert decision.bid is None
    assert decision.ask is not None
    assert decision.ask.base_size == Decimal("10000")
    assert decision.ask.quote_notional == Decimal("10001")
    assert decision.reason == "fill_rebalance_sell_only"
