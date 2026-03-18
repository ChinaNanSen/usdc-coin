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


def test_strategy_can_emit_two_layers_per_side_when_enabled():
    strategy = MicroMakerStrategy(StrategyConfig(), TradingConfig(), max_orders_per_side=2)
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9998"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0000"), size=Decimal("100000"))],
        )
    )
    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.bid is not None
    assert decision.ask is not None
    assert len(decision.bid_layers) == 2
    assert len(decision.ask_layers) == 2
    assert decision.bid_layers[0].price == Decimal("0.9998")
    assert decision.bid_layers[1].price == Decimal("0.9997")
    assert decision.ask_layers[0].price == Decimal("1.0000")
    assert decision.ask_layers[1].price == Decimal("1.0001")
    assert decision.bid_layers[1].reason == "join_second_bid"
    assert decision.ask_layers[1].reason == "join_second_ask"


def test_strategy_scales_entry_size_only_when_spread_is_favorable():
    strategy = MicroMakerStrategy(
        StrategyConfig(
            favorable_size_spread_ticks=2,
            favorable_size_multiplier=Decimal("1.5"),
        ),
        TradingConfig(entry_base_size=Decimal("5000"), quote_size=Decimal("5000")),
        max_orders_per_side=2,
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9998"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0000"), size=Decimal("100000"))],
        )
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.reason == "two_sided"
    assert decision.bid is not None
    assert decision.ask is not None
    assert decision.bid.base_size == Decimal("7500")
    assert decision.ask.base_size == Decimal("7500")
    assert decision.bid_layers[1].base_size == Decimal("7500")
    assert decision.ask_layers[1].base_size == Decimal("7500")


def test_strategy_does_not_scale_entry_size_when_spread_is_one_tick():
    strategy = MicroMakerStrategy(
        StrategyConfig(
            favorable_size_spread_ticks=2,
            favorable_size_multiplier=Decimal("1.5"),
        ),
        TradingConfig(entry_base_size=Decimal("5000"), quote_size=Decimal("5000")),
    )

    decision = strategy.decide(
        build_state("50000", "50000"),
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.reason == "two_sided"
    assert decision.bid is not None
    assert decision.ask is not None
    assert decision.bid.base_size == Decimal("5000")
    assert decision.ask.base_size == Decimal("5000")


def test_strategy_does_not_emit_second_entry_layer_when_spread_is_one_tick():
    strategy = MicroMakerStrategy(StrategyConfig(), TradingConfig(), max_orders_per_side=2)
    decision = strategy.decide(
        build_state("50000", "50000"),
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.bid is not None
    assert decision.ask is not None
    assert len(decision.bid_layers) == 1
    assert len(decision.ask_layers) == 1
    assert decision.bid_layers[0].reason == "join_best_bid"
    assert decision.ask_layers[0].reason == "join_best_ask"


def test_strategy_does_not_scale_overlay_size_while_rebalancing_even_if_spread_is_favorable():
    strategy = MicroMakerStrategy(
        StrategyConfig(
            favorable_size_spread_ticks=2,
            favorable_size_multiplier=Decimal("1.5"),
        ),
        TradingConfig(entry_base_size=Decimal("10000"), quote_size=Decimal("10000")),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9998"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0000"), size=Decimal("100000"))],
        )
    )
    cl_ord_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "1",
            "clOrdId": cl_ord_id,
            "px": "0.9999",
            "fillPx": "0.9999",
            "sz": "10000",
            "accFillSz": "10000",
            "state": "filled",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.reason == "fill_rebalance_sell_biased"
    assert decision.ask is not None
    assert decision.ask.base_size == Decimal("10000")
    assert decision.bid is not None
    assert decision.bid.reason == "rebalance_secondary_bid"
    assert decision.bid.base_size == Decimal("500.0000")


def test_strategy_uses_bot_position_to_bias_secondary_side_even_when_account_inventory_disagrees():
    strategy = MicroMakerStrategy(StrategyConfig(), TradingConfig(entry_base_size=Decimal("5000"), quote_size=Decimal("5000")))
    state = build_state("70000", "30000")
    cl_ord_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "1",
            "clOrdId": cl_ord_id,
            "px": "0.9999",
            "fillPx": "0.9999",
            "sz": "2500",
            "accFillSz": "2500",
            "state": "filled",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.reason == "fill_rebalance_buy_biased"
    assert decision.ask is not None
    assert decision.ask.reason == "rebalance_secondary_ask"
    assert decision.ask.base_size == Decimal("375.00000")


def test_strategy_strict_cycle_starts_with_buy_only():
    strategy = MicroMakerStrategy(StrategyConfig(strict_alternating_sides=True), TradingConfig(entry_base_size=Decimal("10000")))
    decision = strategy.decide(
        build_state("50000", "50000"),
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )
    assert decision.bid is not None
    assert decision.ask is None
    assert decision.bid.base_size == Decimal("10000")
    assert decision.reason == "strict_cycle_buy_only"


def test_strategy_can_use_fixed_entry_base_size_for_two_sided_quotes():
    strategy = MicroMakerStrategy(StrategyConfig(), TradingConfig(entry_base_size=Decimal("10000")))
    decision = strategy.decide(
        build_state("50000", "50000"),
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.bid is not None
    assert decision.ask is not None
    assert decision.bid.base_size == Decimal("10000")
    assert decision.bid.quote_notional == Decimal("9999")
    assert decision.ask.base_size == Decimal("10000")
    assert decision.ask.quote_notional == Decimal("10000")
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


def test_strategy_rebalances_buy_after_selling_startup_inventory():
    strategy = MicroMakerStrategy(StrategyConfig(), TradingConfig())
    state = build_state("10000", "10000")
    cl_ord_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
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

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="reduce_only_inventory_low", allow_bid=True, allow_ask=False, runtime_state="REDUCE_ONLY"),
    )

    assert state.strategy_position_base() == Decimal("-10000")
    assert decision.bid is not None
    assert decision.ask is None
    assert decision.bid.base_size == Decimal("10000")
    assert decision.reason == "fill_rebalance_buy_only"


def test_strategy_strict_cycle_sells_only_after_buy_fill():
    strategy = MicroMakerStrategy(StrategyConfig(strict_alternating_sides=True), TradingConfig(entry_base_size=Decimal("10000")))
    state = build_state("50000", "50000")
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

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.bid is None
    assert decision.ask is not None
    assert decision.ask.base_size == Decimal("10000")
    assert decision.reason == "fill_rebalance_sell_only"


def test_strategy_strict_cycle_returns_to_sell_only_after_short_is_closed():
    strategy = MicroMakerStrategy(StrategyConfig(strict_alternating_sides=True), TradingConfig(entry_base_size=Decimal("10000")))
    state = build_state("50000", "50000")
    sell_id = build_cl_ord_id("bot6", "sell")
    buy_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "1",
            "clOrdId": sell_id,
            "px": "1.0001",
            "fillPx": "1.0001",
            "sz": "10000",
            "accFillSz": "10000",
            "state": "filled",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "2",
            "clOrdId": buy_id,
            "px": "1",
            "fillPx": "1",
            "sz": "10000",
            "accFillSz": "10000",
            "state": "filled",
            "cTime": "3",
            "uTime": "4",
        },
        source="test",
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.bid is None
    assert decision.ask is not None
    assert decision.ask.base_size == Decimal("10000")
    assert decision.reason == "strict_cycle_sell_only"


def test_strategy_inventory_high_normal_sell_respects_price_floor():
    strategy = MicroMakerStrategy(
        StrategyConfig(normal_sell_price_floor=Decimal("1")),
        TradingConfig(entry_base_size=Decimal("10000")),
    )
    state = build_state("80000", "20000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9998"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
        )
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="reduce_only_inventory_high", allow_bid=False, allow_ask=True, runtime_state="REDUCE_ONLY"),
    )

    assert decision.bid is None
    assert decision.ask is not None
    assert decision.ask.price == Decimal("1")
    assert decision.ask.base_size == Decimal("10000")
    assert decision.ask.quote_notional == Decimal("10000")
    assert decision.reason == "inventory_high_ask_only"


def test_strategy_two_sided_quote_does_not_apply_sell_price_floor_while_bid_is_live():
    strategy = MicroMakerStrategy(
        StrategyConfig(normal_sell_price_floor=Decimal("1.0001")),
        TradingConfig(),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9998"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
        )
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.bid is not None
    assert decision.ask is not None
    assert decision.ask.price == Decimal("0.9999")


def test_strategy_two_sided_quote_applies_buy_price_cap():
    strategy = MicroMakerStrategy(
        StrategyConfig(normal_buy_price_cap=Decimal("1")),
        TradingConfig(entry_base_size=Decimal("10000")),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("1.0002"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0003"), size=Decimal("100000"))],
        )
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.bid is not None
    assert decision.ask is not None
    assert decision.bid.price == Decimal("1")
    assert decision.bid.base_size == Decimal("10000")


def test_strategy_blocks_when_visible_depth_is_too_thin():
    strategy = MicroMakerStrategy(StrategyConfig(min_visible_depth_multiplier=Decimal("3")), TradingConfig(quote_size=Decimal("10000")))
    decision = strategy.decide(
        build_state("50000", "50000", depth_size="1000"),
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )
    assert decision.bid is None
    assert decision.ask is None
    assert "visible depth too thin" in decision.reason


def test_strategy_uses_soft_band_to_reduce_bid_and_keep_two_sided_quotes():
    strategy = MicroMakerStrategy(StrategyConfig(account_inventory_skew_enabled=True), TradingConfig())
    decision = strategy.decide(
        build_state("70000", "30000"),
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )
    assert decision.bid is not None
    assert decision.ask is not None
    assert decision.bid.price == Decimal("0.9999")
    assert decision.bid.quote_notional == Decimal("5000")
    assert decision.reason == "two_sided"


def test_strategy_keeps_full_two_sided_quotes_inside_configured_soft_band():
    strategy = MicroMakerStrategy(
        StrategyConfig(
            account_inventory_skew_enabled=True,
            inventory_soft_lower_pct=Decimal("0.40"),
            inventory_soft_upper_pct=Decimal("0.60"),
            mild_skew_threshold_pct=Decimal("0.03"),
            mild_skew_size_factor=Decimal("0.50"),
        ),
        TradingConfig(),
    )

    decision = strategy.decide(
        build_state("58000", "42000"),
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.bid is not None
    assert decision.ask is not None
    assert decision.bid.price == Decimal("0.9999")
    assert decision.bid.quote_notional == Decimal("10000")
    assert decision.ask.price == Decimal("1.0000")
    assert decision.ask.quote_notional == Decimal("10000")
    assert decision.reason == "two_sided"


def test_strategy_starts_reducing_bid_after_crossing_soft_upper_band():
    strategy = MicroMakerStrategy(
        StrategyConfig(
            account_inventory_skew_enabled=True,
            inventory_soft_lower_pct=Decimal("0.40"),
            inventory_soft_upper_pct=Decimal("0.60"),
            mild_skew_threshold_pct=Decimal("0.03"),
            mild_skew_size_factor=Decimal("0.50"),
        ),
        TradingConfig(),
    )

    decision = strategy.decide(
        build_state("63000", "37000"),
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.bid is not None
    assert decision.ask is not None
    assert decision.bid.price == Decimal("0.9999")
    assert Decimal("5000") < decision.bid.quote_notional < Decimal("5100")
    assert decision.ask.price == Decimal("1.0000")
    assert decision.ask.quote_notional == Decimal("10000")
    assert decision.reason == "two_sided"


def test_strategy_starts_reducing_ask_after_crossing_soft_lower_band():
    strategy = MicroMakerStrategy(
        StrategyConfig(
            account_inventory_skew_enabled=True,
            inventory_soft_lower_pct=Decimal("0.40"),
            inventory_soft_upper_pct=Decimal("0.60"),
            mild_skew_threshold_pct=Decimal("0.03"),
            mild_skew_size_factor=Decimal("0.50"),
        ),
        TradingConfig(),
    )

    decision = strategy.decide(
        build_state("37000", "63000"),
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.bid is not None
    assert decision.ask is not None
    assert decision.bid.price == Decimal("0.9999")
    assert decision.bid.quote_notional == Decimal("10000")
    assert decision.ask.price == Decimal("1.0000")
    assert decision.ask.quote_notional == Decimal("5000")
    assert decision.reason == "two_sided"


def test_strategy_still_uses_price_skew_when_spread_exceeds_one_tick():
    strategy = MicroMakerStrategy(StrategyConfig(account_inventory_skew_enabled=True), TradingConfig())
    state = build_state("70000", "30000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9998"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0000"), size=Decimal("100000"))],
        )
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.bid is not None
    assert decision.ask is not None
    assert decision.bid.price == Decimal("0.9997")
    assert decision.ask.price == Decimal("0.9999")
    assert decision.reason == "two_sided"


def test_strategy_ignores_account_inventory_skew_by_default_when_bot_is_flat():
    strategy = MicroMakerStrategy(StrategyConfig(), TradingConfig())

    decision = strategy.decide(
        build_state("70000", "30000"),
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.bid is not None
    assert decision.ask is not None
    assert decision.bid.quote_notional == Decimal("10000")
    assert decision.ask.quote_notional == Decimal("10000")
    assert decision.bid.price == Decimal("0.9999")
    assert decision.ask.price == Decimal("1.0000")
    assert decision.reason == "two_sided"


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

    assert decision.bid is not None
    assert decision.bid.reason == "rebalance_secondary_bid"
    assert decision.bid.price == Decimal("0.9999")
    assert decision.bid.quote_notional == Decimal("500.0000")
    assert decision.ask is not None
    assert decision.ask.base_size == Decimal("10000")
    assert decision.ask.quote_notional == Decimal("10001")
    assert decision.reason == "fill_rebalance_sell_biased"


def test_strategy_rebalance_sell_respects_min_profit_ticks():
    strategy = MicroMakerStrategy(StrategyConfig(rebalance_min_profit_ticks=1), TradingConfig())
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1"), size=Decimal("100000"))],
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

    decision = strategy.decide(state, RiskStatus(ok=True, reason="ok", allow_bid=False, allow_ask=True, runtime_state="REDUCE_ONLY"))

    assert decision.ask is not None
    assert decision.ask.price == Decimal("1.0001")
    assert decision.ask.quote_notional == Decimal("10001")


def test_strategy_rebalance_sell_ignores_normal_sell_floor_when_trade_already_has_one_tick_profit():
    strategy = MicroMakerStrategy(
        StrategyConfig(rebalance_min_profit_ticks=1, normal_sell_price_floor=Decimal("1.0001")),
        TradingConfig(),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1"), size=Decimal("100000"))],
        )
    )
    cl_ord_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "1",
            "clOrdId": cl_ord_id,
            "px": "0.9999",
            "fillPx": "0.9999",
            "sz": "10000",
            "accFillSz": "10000",
            "state": "filled",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )

    decision = strategy.decide(state, RiskStatus(ok=True, reason="ok", allow_bid=False, allow_ask=True, runtime_state="REDUCE_ONLY"))

    assert decision.ask is not None
    assert decision.ask.price == Decimal("1")
    assert decision.ask.quote_notional == Decimal("10000")


def test_strategy_rebalance_sell_can_allow_flat_exit_when_profit_ticks_zero():
    strategy = MicroMakerStrategy(StrategyConfig(rebalance_min_profit_ticks=0), TradingConfig())
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1"), size=Decimal("100000"))],
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

    decision = strategy.decide(state, RiskStatus(ok=True, reason="ok", allow_bid=False, allow_ask=True, runtime_state="REDUCE_ONLY"))

    assert decision.ask is not None
    assert decision.ask.price == Decimal("1")


def test_strategy_rebalance_buy_downgrades_to_flat_reload_after_timeout(monkeypatch):
    monkeypatch.setattr("src.strategy.now_ms", lambda: 1_700_000_300_000)
    strategy = MicroMakerStrategy(
        StrategyConfig(rebalance_min_profit_ticks=1, rebalance_reload_timeout_seconds=120),
        TradingConfig(),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("1"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0001"), size=Decimal("100000"))],
        )
    )
    cl_ord_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "1",
            "clOrdId": cl_ord_id,
            "px": "1",
            "fillPx": "1",
            "sz": "10000",
            "accFillSz": "10000",
            "state": "filled",
            "cTime": "1700000000000",
            "uTime": "1700000000000",
        },
        source="test",
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="reduce_only_inventory_low", allow_bid=True, allow_ask=False, runtime_state="REDUCE_ONLY"),
    )

    assert decision.bid is not None
    assert decision.bid.price == Decimal("0.9999")
    assert decision.ask is None
    assert decision.reason == "fill_rebalance_buy_only"


def test_strategy_rebalance_buy_downgrades_only_after_timeout_and_top_change(monkeypatch):
    monkeypatch.setattr("src.strategy.now_ms", lambda: 1_700_000_300_000)
    strategy = MicroMakerStrategy(
        StrategyConfig(rebalance_min_profit_ticks=1, rebalance_reload_timeout_seconds=120),
        TradingConfig(),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=1,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1"), size=Decimal("100000"))],
        )
    )
    cl_ord_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "1",
            "clOrdId": cl_ord_id,
            "px": "1",
            "fillPx": "1",
            "sz": "10000",
            "accFillSz": "10000",
            "state": "filled",
            "cTime": "1700000000000",
            "uTime": "1700000000000",
        },
        source="test",
    )
    state.set_book(
        BookSnapshot(
            ts_ms=2,
            bids=[BookLevel(price=Decimal("1"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0001"), size=Decimal("100000"))],
        )
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="reduce_only_inventory_low", allow_bid=True, allow_ask=False, runtime_state="REDUCE_ONLY"),
    )

    assert decision.bid is not None
    assert decision.bid.price == Decimal("1")
    assert decision.ask is None
    assert decision.reason == "fill_rebalance_buy_only"


def test_strategy_rebalance_sell_downgrades_to_flat_reload_after_timeout(monkeypatch):
    monkeypatch.setattr("src.strategy.now_ms", lambda: 1_700_000_300_000)
    strategy = MicroMakerStrategy(
        StrategyConfig(rebalance_min_profit_ticks=1, rebalance_reload_timeout_seconds=120),
        TradingConfig(),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1"), size=Decimal("100000"))],
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
            "cTime": "1700000000000",
            "uTime": "1700000000000",
        },
        source="test",
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="reduce_only_inventory_high", allow_bid=False, allow_ask=True, runtime_state="REDUCE_ONLY"),
    )

    assert decision.bid is None
    assert decision.ask is not None
    assert decision.ask.price == Decimal("1.0001")
    assert decision.reason == "fill_rebalance_sell_only"


def test_strategy_rebalance_sell_downgrades_only_after_timeout_and_top_change(monkeypatch):
    monkeypatch.setattr("src.strategy.now_ms", lambda: 1_700_000_300_000)
    strategy = MicroMakerStrategy(
        StrategyConfig(rebalance_min_profit_ticks=1, rebalance_reload_timeout_seconds=120),
        TradingConfig(),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=1,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1"), size=Decimal("100000"))],
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
            "cTime": "1700000000000",
            "uTime": "1700000000000",
        },
        source="test",
    )
    state.set_book(
        BookSnapshot(
            ts_ms=2,
            bids=[BookLevel(price=Decimal("0.9998"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
        )
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="reduce_only_inventory_high", allow_bid=False, allow_ask=True, runtime_state="REDUCE_ONLY"),
    )

    assert decision.bid is None
    assert decision.ask is not None
    assert decision.ask.base_size == Decimal("10000")
    assert decision.ask.price == Decimal("0.9999")
    assert decision.reason == "fill_rebalance_sell_only"


def test_strategy_rebalance_timeout_uses_lot_age_not_last_fill(monkeypatch):
    monkeypatch.setattr("src.strategy.now_ms", lambda: 1_700_000_300_000)
    strategy = MicroMakerStrategy(
        StrategyConfig(rebalance_min_profit_ticks=1, rebalance_reload_timeout_seconds=120),
        TradingConfig(),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1"), size=Decimal("100000"))],
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
            "cTime": "1700000000000",
            "uTime": "1700000000000",
        },
        source="test",
    )
    state.last_fill_ms = 1_700_000_300_000

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="reduce_only_inventory_high", allow_bid=False, allow_ask=True, runtime_state="REDUCE_ONLY"),
    )

    assert decision.ask is not None
    assert decision.ask.price == Decimal("1.0001")


def test_strategy_rebalance_sell_does_not_move_inside_spread_after_timeout(monkeypatch):
    monkeypatch.setattr("src.strategy.now_ms", lambda: 1_700_000_300_000)
    strategy = MicroMakerStrategy(
        StrategyConfig(rebalance_min_profit_ticks=1, rebalance_reload_timeout_seconds=120),
        TradingConfig(),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9998"), size=Decimal("100000"))],
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
            "cTime": "1700000000000",
            "uTime": "1700000000000",
        },
        source="test",
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="reduce_only_inventory_high", allow_bid=False, allow_ask=True, runtime_state="REDUCE_ONLY"),
    )

    assert decision.ask is not None
    assert decision.ask.price == Decimal("1.0001")


def test_strategy_rebalance_buy_does_not_move_inside_spread_after_timeout(monkeypatch):
    monkeypatch.setattr("src.strategy.now_ms", lambda: 1_700_000_300_000)
    strategy = MicroMakerStrategy(
        StrategyConfig(rebalance_min_profit_ticks=1, rebalance_reload_timeout_seconds=120),
        TradingConfig(),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0002"), size=Decimal("100000"))],
        )
    )
    cl_ord_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "1",
            "clOrdId": cl_ord_id,
            "px": "1.0001",
            "fillPx": "1.0001",
            "sz": "10000",
            "accFillSz": "10000",
            "state": "filled",
            "cTime": "1700000000000",
            "uTime": "1700000000000",
        },
        source="test",
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="reduce_only_inventory_low", allow_bid=True, allow_ask=False, runtime_state="REDUCE_ONLY"),
    )

    assert decision.bid is not None
    assert decision.bid.price == Decimal("0.9999")


def test_strategy_rebalance_sell_moves_passively_inside_spread_after_timeout_and_book_change(monkeypatch):
    monkeypatch.setattr("src.strategy.now_ms", lambda: 1_700_000_013_000)
    strategy = MicroMakerStrategy(
        StrategyConfig(rebalance_min_profit_ticks=1, rebalance_reload_timeout_seconds=5),
        TradingConfig(order_ttl_seconds=6),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=1,
            bids=[BookLevel(price=Decimal("0.9995"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("0.9996"), size=Decimal("100000"))],
        )
    )
    cl_ord_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "1",
            "clOrdId": cl_ord_id,
            "px": "0.9996",
            "fillPx": "0.9996",
            "sz": "10000",
            "accFillSz": "10000",
            "state": "filled",
            "cTime": "1700000000000",
            "uTime": "1700000000000",
        },
        source="test",
    )
    state.set_book(
        BookSnapshot(
            ts_ms=2,
            bids=[BookLevel(price=Decimal("0.9997"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0000"), size=Decimal("100000"))],
        )
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="reduce_only_inventory_high", allow_bid=False, allow_ask=True, runtime_state="REDUCE_ONLY"),
    )

    assert decision.ask is not None
    assert decision.ask.price == Decimal("0.9998")


def test_strategy_rebalance_buy_moves_passively_inside_spread_after_timeout_and_book_change(monkeypatch):
    monkeypatch.setattr("src.strategy.now_ms", lambda: 1_700_000_013_000)
    strategy = MicroMakerStrategy(
        StrategyConfig(rebalance_min_profit_ticks=1, rebalance_reload_timeout_seconds=5),
        TradingConfig(order_ttl_seconds=6),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=1,
            bids=[BookLevel(price=Decimal("1.0002"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0003"), size=Decimal("100000"))],
        )
    )
    cl_ord_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "1",
            "clOrdId": cl_ord_id,
            "px": "1.0002",
            "fillPx": "1.0002",
            "sz": "10000",
            "accFillSz": "10000",
            "state": "filled",
            "cTime": "1700000000000",
            "uTime": "1700000000000",
        },
        source="test",
    )
    state.set_book(
        BookSnapshot(
            ts_ms=2,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0002"), size=Decimal("100000"))],
        )
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="reduce_only_inventory_low", allow_bid=True, allow_ask=False, runtime_state="REDUCE_ONLY"),
    )

    assert decision.bid is not None
    assert decision.bid.price == Decimal("1.0001")


def test_strategy_rebalance_buy_can_keep_small_passive_ask_when_inventory_stays_above_target():
    strategy = MicroMakerStrategy(StrategyConfig(), TradingConfig(entry_base_size=Decimal("10000")))
    state = build_state("28000", "5000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1"), size=Decimal("100000"))],
        )
    )
    cl_ord_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
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

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.bid is not None
    assert decision.bid.base_size == Decimal("10000")
    assert decision.bid.price == Decimal("0.9999")
    assert decision.ask is not None
    assert decision.ask.base_size == Decimal("500.0000")
    assert decision.ask.price == Decimal("1.0001")
    assert decision.reason == "fill_rebalance_buy_biased"


def test_strategy_rebalance_sell_uses_profitable_fifo_tranche_before_full_position():
    strategy = MicroMakerStrategy(StrategyConfig(rebalance_min_profit_ticks=1), TradingConfig(entry_base_size=Decimal("5000")))
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9996"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("0.9997"), size=Decimal("100000"))],
        )
    )
    first_buy = build_cl_ord_id("bot6", "buy")
    second_buy = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "1",
            "clOrdId": first_buy,
            "px": "0.9995",
            "fillPx": "0.9995",
            "sz": "5000",
            "accFillSz": "5000",
            "state": "filled",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "2",
            "clOrdId": second_buy,
            "px": "0.9998",
            "fillPx": "0.9998",
            "sz": "5000",
            "accFillSz": "5000",
            "state": "filled",
            "cTime": "3",
            "uTime": "4",
        },
        source="test",
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="reduce_only_inventory_high", allow_bid=False, allow_ask=True, runtime_state="REDUCE_ONLY"),
    )

    assert decision.bid is None
    assert decision.ask is not None
    assert decision.ask.base_size == Decimal("5000")
    assert decision.ask.price == Decimal("0.9997")
    assert decision.reason == "fill_rebalance_sell_only"


def test_strategy_rebalance_sell_uses_competitive_chunk_when_zero_profitable_prefix_after_reload(monkeypatch):
    monkeypatch.setattr("src.strategy.now_ms", lambda: 1_700_000_013_000)
    strategy = MicroMakerStrategy(
        StrategyConfig(rebalance_min_profit_ticks=1, rebalance_reload_timeout_seconds=5),
        TradingConfig(entry_base_size=Decimal("5000"), order_ttl_seconds=6),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=1,
            bids=[BookLevel(price=Decimal("1.0000"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0001"), size=Decimal("100000"))],
        )
    )
    first_buy = build_cl_ord_id("bot6", "buy")
    second_buy = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "1",
            "clOrdId": first_buy,
            "px": "1.0001",
            "fillPx": "1.0001",
            "sz": "5000",
            "accFillSz": "5000",
            "state": "filled",
            "cTime": "1700000000000",
            "uTime": "1700000000000",
        },
        source="test",
    )
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "2",
            "clOrdId": second_buy,
            "px": "0.9998",
            "fillPx": "0.9998",
            "sz": "5000",
            "accFillSz": "5000",
            "state": "filled",
            "cTime": "1700000001000",
            "uTime": "1700000001000",
        },
        source="test",
    )
    state.set_book(
        BookSnapshot(
            ts_ms=2,
            bids=[BookLevel(price=Decimal("0.9997"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("0.9998"), size=Decimal("100000"))],
        )
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="reduce_only_inventory_high", allow_bid=False, allow_ask=True, runtime_state="REDUCE_ONLY"),
    )

    assert decision.ask is not None
    assert decision.ask.base_size == Decimal("3750.00")
    assert decision.ask.price == Decimal("0.9998")
    assert decision.reason == "fill_rebalance_sell_only"


def test_strategy_rebalance_sell_uses_smaller_aged_chunk_before_release(monkeypatch):
    monkeypatch.setattr("src.strategy.now_ms", lambda: 1_700_000_013_000)
    strategy = MicroMakerStrategy(
        StrategyConfig(
            rebalance_min_profit_ticks=1,
            rebalance_reload_timeout_seconds=5,
            rebalance_drift_ticks=5,
            rebalance_max_order_age_seconds=60,
            rebalance_release_size_factor=Decimal("0.50"),
        ),
        TradingConfig(entry_base_size=Decimal("5000"), order_ttl_seconds=6),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=1,
            bids=[BookLevel(price=Decimal("1.0000"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0001"), size=Decimal("100000"))],
        )
    )
    first_buy = build_cl_ord_id("bot6", "buy")
    second_buy = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "1",
            "clOrdId": first_buy,
            "px": "1.0001",
            "fillPx": "1.0001",
            "sz": "5000",
            "accFillSz": "5000",
            "state": "filled",
            "cTime": "1700000000000",
            "uTime": "1700000000000",
        },
        source="test",
    )
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "2",
            "clOrdId": second_buy,
            "px": "0.9998",
            "fillPx": "0.9998",
            "sz": "5000",
            "accFillSz": "5000",
            "state": "filled",
            "cTime": "1700000001000",
            "uTime": "1700000001000",
        },
        source="test",
    )
    state.set_book(
        BookSnapshot(
            ts_ms=2,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0000"), size=Decimal("100000"))],
        )
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="reduce_only_inventory_high", allow_bid=False, allow_ask=True, runtime_state="REDUCE_ONLY"),
    )

    assert decision.ask is not None
    assert decision.ask.base_size == Decimal("2500.00")
    assert decision.ask.price == Decimal("1.0000")
    assert decision.reason == "fill_rebalance_sell_only"


def test_strategy_rebalance_buy_uses_profitable_fifo_tranche_before_full_position():
    strategy = MicroMakerStrategy(StrategyConfig(rebalance_min_profit_ticks=1), TradingConfig(entry_base_size=Decimal("5000")))
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("1.0002"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0003"), size=Decimal("100000"))],
        )
    )
    first_sell = build_cl_ord_id("bot6", "sell")
    second_sell = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "1",
            "clOrdId": first_sell,
            "px": "1.0003",
            "fillPx": "1.0003",
            "sz": "5000",
            "accFillSz": "5000",
            "state": "filled",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "2",
            "clOrdId": second_sell,
            "px": "1.0000",
            "fillPx": "1.0000",
            "sz": "5000",
            "accFillSz": "5000",
            "state": "filled",
            "cTime": "3",
            "uTime": "4",
        },
        source="test",
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="reduce_only_inventory_low", allow_bid=True, allow_ask=False, runtime_state="REDUCE_ONLY"),
    )

    assert decision.ask is None
    assert decision.bid is not None
    assert decision.bid.base_size == Decimal("5000")
    assert decision.bid.price == Decimal("1.0002")
    assert decision.reason == "fill_rebalance_buy_only"


def test_strategy_rebalance_buy_uses_competitive_chunk_when_zero_profitable_prefix_after_reload(monkeypatch):
    monkeypatch.setattr("src.strategy.now_ms", lambda: 1_700_000_013_000)
    strategy = MicroMakerStrategy(
        StrategyConfig(rebalance_min_profit_ticks=1, rebalance_reload_timeout_seconds=5),
        TradingConfig(entry_base_size=Decimal("5000"), order_ttl_seconds=6),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=1,
            bids=[BookLevel(price=Decimal("0.9995"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("0.9996"), size=Decimal("100000"))],
        )
    )
    first_sell = build_cl_ord_id("bot6", "sell")
    second_sell = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "1",
            "clOrdId": first_sell,
            "px": "0.9995",
            "fillPx": "0.9995",
            "sz": "5000",
            "accFillSz": "5000",
            "state": "filled",
            "cTime": "1700000000000",
            "uTime": "1700000000000",
        },
        source="test",
    )
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "2",
            "clOrdId": second_sell,
            "px": "1.0002",
            "fillPx": "1.0002",
            "sz": "5000",
            "accFillSz": "5000",
            "state": "filled",
            "cTime": "1700000001000",
            "uTime": "1700000001000",
        },
        source="test",
    )
    state.set_book(
        BookSnapshot(
            ts_ms=2,
            bids=[BookLevel(price=Decimal("1.0002"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0003"), size=Decimal("100000"))],
        )
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="reduce_only_inventory_low", allow_bid=True, allow_ask=False, runtime_state="REDUCE_ONLY"),
    )

    assert decision.bid is not None
    assert decision.bid.base_size == Decimal("3750.00")
    assert decision.bid.price == Decimal("1.0002")
    assert decision.reason == "fill_rebalance_buy_only"


def test_strategy_rebalance_sell_can_keep_small_passive_bid_when_inventory_stays_below_target():
    strategy = MicroMakerStrategy(StrategyConfig(), TradingConfig(entry_base_size=Decimal("10000")))
    state = build_state("5000", "28000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1"), size=Decimal("100000"))],
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

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.ask is not None
    assert decision.ask.base_size == Decimal("10000")
    assert decision.ask.price == Decimal("1.0001")
    assert decision.bid is not None
    assert decision.bid.base_size == Decimal("500.0000")
    assert decision.bid.price == Decimal("0.9998")
    assert decision.reason == "fill_rebalance_sell_biased"


def test_strategy_rebalance_sell_keeps_overlay_when_account_inventory_is_near_target():
    strategy = MicroMakerStrategy(StrategyConfig(), TradingConfig(entry_base_size=Decimal("10000")))
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1"), size=Decimal("100000"))],
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

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.ask is not None
    assert decision.ask.base_size == Decimal("10000")
    assert decision.ask.price == Decimal("1.0001")
    assert decision.bid is not None
    assert decision.bid.reason == "rebalance_secondary_bid"
    assert decision.bid.base_size == Decimal("500.0000")
    assert decision.bid.price == Decimal("0.9998")
    assert decision.reason == "fill_rebalance_sell_biased"


def test_strategy_release_mode_keeps_small_overlay_when_move_is_not_adverse(monkeypatch):
    monkeypatch.setattr("src.strategy.now_ms", lambda: 1_700_000_013_000)
    strategy = MicroMakerStrategy(
        StrategyConfig(
            rebalance_min_profit_ticks=1,
            rebalance_reload_timeout_seconds=5,
            rebalance_max_order_age_seconds=6,
            rebalance_secondary_size_factor=Decimal("0.25"),
            rebalance_overlay_floor_factor=Decimal("0.10"),
        ),
        TradingConfig(entry_base_size=Decimal("10000"), order_ttl_seconds=6),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=1,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0000"), size=Decimal("100000"))],
        )
    )
    cl_ord_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "1",
            "clOrdId": cl_ord_id,
            "px": "1.0000",
            "fillPx": "1.0000",
            "sz": "10000",
            "accFillSz": "10000",
            "state": "filled",
            "cTime": "1700000000000",
            "uTime": "1700000000000",
        },
        source="test",
    )
    state.set_book(
        BookSnapshot(
            ts_ms=2,
            bids=[BookLevel(price=Decimal("1.0000"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0001"), size=Decimal("100000"))],
        )
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.ask is not None
    assert decision.bid is not None
    assert decision.bid.reason == "rebalance_secondary_bid"
    assert decision.bid.base_size == Decimal("500.0000")
    assert decision.reason == "fill_rebalance_sell_biased"


def test_strategy_release_mode_keeps_floor_overlay_when_market_moves_against_position(monkeypatch):
    monkeypatch.setattr("src.strategy.now_ms", lambda: 1_700_000_013_000)
    strategy = MicroMakerStrategy(
        StrategyConfig(
            rebalance_min_profit_ticks=1,
            rebalance_reload_timeout_seconds=5,
            rebalance_max_order_age_seconds=6,
            rebalance_secondary_size_factor=Decimal("0.25"),
            rebalance_overlay_floor_factor=Decimal("0.10"),
        ),
        TradingConfig(entry_base_size=Decimal("10000"), order_ttl_seconds=6),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=1,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1.0000"), size=Decimal("100000"))],
        )
    )
    cl_ord_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "1",
            "clOrdId": cl_ord_id,
            "px": "1.0000",
            "fillPx": "1.0000",
            "sz": "10000",
            "accFillSz": "10000",
            "state": "filled",
            "cTime": "1700000000000",
            "uTime": "1700000000000",
        },
        source="test",
    )
    state.set_book(
        BookSnapshot(
            ts_ms=2,
            bids=[BookLevel(price=Decimal("0.9997"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("0.9998"), size=Decimal("100000"))],
        )
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.ask is not None
    assert decision.bid is not None
    assert decision.bid.reason == "rebalance_secondary_bid"
    assert decision.bid.base_size == Decimal("200.00000")
    assert decision.reason == "fill_rebalance_sell_biased"


def test_strategy_inventory_review_does_not_push_secondary_ask_farther_away(monkeypatch):
    monkeypatch.setattr("src.strategy.now_ms", lambda: 1_700_000_012_000)
    strategy = MicroMakerStrategy(
        StrategyConfig(),
        TradingConfig(entry_base_size=Decimal("10000"), order_ttl_seconds=6),
    )
    state = build_state("28000", "5000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1"), size=Decimal("100000"))],
        )
    )
    cl_ord_id = build_cl_ord_id("bot6", "sell")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "1",
            "clOrdId": cl_ord_id,
            "px": "1",
            "fillPx": "1",
            "sz": "10000",
            "accFillSz": "10000",
            "state": "filled",
            "cTime": "1700000000000",
            "uTime": "1700000000000",
        },
        source="test",
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.bid is not None
    assert decision.bid.base_size == Decimal("10000")
    assert decision.bid.price == Decimal("0.9999")
    assert decision.ask is not None
    assert decision.ask.base_size == Decimal("500.0000")
    assert decision.ask.price == Decimal("1.0001")


def test_strategy_inventory_review_does_not_push_secondary_bid_farther_away(monkeypatch):
    monkeypatch.setattr("src.strategy.now_ms", lambda: 1_700_000_012_000)
    strategy = MicroMakerStrategy(
        StrategyConfig(),
        TradingConfig(entry_base_size=Decimal("10000"), order_ttl_seconds=6),
    )
    state = build_state("5000", "28000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1"), size=Decimal("100000"))],
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
            "cTime": "1700000000000",
            "uTime": "1700000000000",
        },
        source="test",
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.ask is not None
    assert decision.ask.base_size == Decimal("10000")
    assert decision.ask.price == Decimal("1.0001")
    assert decision.bid is not None
    assert decision.bid.base_size == Decimal("500.0000")
    assert decision.bid.price == Decimal("0.9998")


def test_strategy_strict_cycle_sell_leg_ignores_normal_sell_floor_when_buy_fill_already_has_one_tick_profit():
    strategy = MicroMakerStrategy(
        StrategyConfig(
            strict_alternating_sides=True,
            rebalance_min_profit_ticks=1,
            normal_sell_price_floor=Decimal("1.0001"),
        ),
        TradingConfig(entry_base_size=Decimal("10000")),
    )
    state = build_state("50000", "50000")
    state.set_book(
        BookSnapshot(
            ts_ms=9999999999999,
            bids=[BookLevel(price=Decimal("0.9999"), size=Decimal("100000"))],
            asks=[BookLevel(price=Decimal("1"), size=Decimal("100000"))],
        )
    )
    cl_ord_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "1",
            "clOrdId": cl_ord_id,
            "px": "0.9999",
            "fillPx": "0.9999",
            "sz": "10000",
            "accFillSz": "10000",
            "state": "filled",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="ok", allow_bid=True, allow_ask=True),
    )

    assert decision.bid is None
    assert decision.ask is not None
    assert decision.ask.price == Decimal("1")
    assert decision.ask.base_size == Decimal("10000")
    assert decision.reason == "fill_rebalance_sell_only"


def test_strategy_ignores_sub_min_rebalance_dust_and_keeps_normal_ask():
    strategy = MicroMakerStrategy(
        StrategyConfig(normal_sell_price_floor=Decimal("1")),
        TradingConfig(entry_base_size=Decimal("10000")),
    )
    state = build_state("20230.742424", "4785.963127427094")
    sell_cl_ord_id = build_cl_ord_id("bot6", "sell")
    buy_cl_ord_id = build_cl_ord_id("bot6", "buy")
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "1",
            "clOrdId": sell_cl_ord_id,
            "px": "1.0001",
            "fillPx": "1.0001",
            "sz": "9999.000099",
            "accFillSz": "9999.000099",
            "state": "filled",
            "cTime": "1",
            "uTime": "2",
        },
        source="test",
    )
    state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "2",
            "clOrdId": buy_cl_ord_id,
            "px": "1",
            "fillPx": "1",
            "sz": "10000",
            "accFillSz": "10000",
            "state": "filled",
            "cTime": "3",
            "uTime": "4",
        },
        source="test",
    )

    assert state.strategy_position_base() == Decimal("0.999901")

    decision = strategy.decide(
        state,
        RiskStatus(ok=True, reason="reduce_only_inventory_high", allow_bid=False, allow_ask=True, runtime_state="REDUCE_ONLY"),
    )

    assert decision.bid is None
    assert decision.ask is not None
    assert decision.ask.reason == "join_best_ask"
    assert decision.ask.price == Decimal("1")
    assert decision.ask.base_size == Decimal("10000")
    assert decision.reason == "inventory_high_ask_only"
