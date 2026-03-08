from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import RiskConfig, TradingConfig
from src.consistency import StateConsistencyChecker
from src.models import Balance, BookLevel, BookSnapshot, InstrumentMeta
from src.state import BotState
from src.utils import build_cl_ord_id


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
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0000"), size=Decimal("100000"))],
        )
    )
    state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=Decimal("50000"), available=Decimal("45000")),
            "USDT": Balance(ccy="USDT", total=Decimal("50000"), available=Decimal("45000")),
        }
    )
    return state


def test_consistency_passes_for_clean_state():
    checker = StateConsistencyChecker(risk=RiskConfig(), trading=TradingConfig(), managed_prefix="bot6")
    state = make_state()
    report = checker.check(state)
    assert report.ok is True
    assert report.reason == "state consistent"


def test_consistency_fails_on_foreign_pending_order():
    checker = StateConsistencyChecker(risk=RiskConfig(fail_on_foreign_pending_orders=True), trading=TradingConfig(), managed_prefix="bot6")
    state = make_state()
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "123",
            "clOrdId": "manual-order-1",
            "px": "0.9999",
            "sz": "1000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )
    report = checker.check(state)
    assert report.ok is False
    assert "foreign pending orders" in report.reason


def test_consistency_fails_when_managed_order_crosses_book():
    checker = StateConsistencyChecker(risk=RiskConfig(), trading=TradingConfig(), managed_prefix="bot6")
    state = make_state()
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "123",
            "clOrdId": build_cl_ord_id("bot6", "buy"),
            "px": "1.0000",
            "sz": "1000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )
    report = checker.check(state)
    assert report.ok is False
    assert "crosses ask" in report.reason


def test_consistency_fails_when_pending_buy_exceeds_balance():
    checker = StateConsistencyChecker(risk=RiskConfig(balance_consistency_tolerance_quote=Decimal("0")), trading=TradingConfig(), managed_prefix="bot6")
    state = make_state()
    state.balances["USDT"] = Balance(ccy="USDT", total=Decimal("1000"), available=Decimal("0"))
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "123",
            "clOrdId": build_cl_ord_id("bot6", "buy"),
            "px": "0.9999",
            "sz": "5000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )
    report = checker.check(state)
    assert report.ok is False
    assert "buy pending exceeds quote balance" in report.reason
