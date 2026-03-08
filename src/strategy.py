from __future__ import annotations

from decimal import Decimal

from .config import StrategyConfig, TradingConfig
from .models import OrderIntent, QuoteDecision, RiskStatus
from .state import BotState


class MicroMakerStrategy:
    def __init__(self, config: StrategyConfig, trading: TradingConfig):
        self.config = config
        self.trading = trading

    def decide(self, state: BotState, risk_status: RiskStatus) -> QuoteDecision:
        if not risk_status.ok or not state.instrument or not state.book or not state.book.best_bid or not state.book.best_ask:
            return QuoteDecision(reason=risk_status.reason)

        spread_ticks = state.book.spread / state.instrument.tick_size
        if spread_ticks < Decimal(self.config.min_spread_ticks):
            return QuoteDecision(reason=f"spread too tight: {spread_ticks}")

        quote_size = min(max(self.trading.quote_size, self.trading.min_quote_size), self.trading.max_quote_size)
        inventory_ratio = state.inventory_ratio()
        rebalance_buy_base = state.rebalance_base_size("buy")
        rebalance_sell_base = state.rebalance_base_size("sell")
        rebalance_quote_ref = max(
            quote_size,
            rebalance_buy_base * state.book.best_bid.price,
            rebalance_sell_base * state.book.best_ask.price,
        )
        min_visible_depth = rebalance_quote_ref * self.config.min_visible_depth_multiplier
        bid_depth = self._visible_depth_notional(state.book.bids)
        ask_depth = self._visible_depth_notional(state.book.asks)
        if bid_depth < min_visible_depth or ask_depth < min_visible_depth:
            return QuoteDecision(reason=f"visible depth too thin: bid={bid_depth}, ask={ask_depth}")

        bid_size = quote_size
        ask_size = quote_size
        if inventory_ratio is not None:
            deviation = inventory_ratio - self.config.inventory_target_pct
            if deviation >= self.config.mild_skew_threshold_pct:
                bid_size = quote_size * (Decimal("1") - self.config.mild_skew_size_factor)
            elif deviation <= -self.config.mild_skew_threshold_pct:
                ask_size = quote_size * (Decimal("1") - self.config.mild_skew_size_factor)

        allow_bid = risk_status.allow_bid
        allow_ask = risk_status.allow_ask
        if rebalance_buy_base > 0:
            allow_ask = False
        if rebalance_sell_base > 0:
            allow_bid = False
        if inventory_ratio is not None:
            if inventory_ratio >= self.config.inventory_soft_upper_pct:
                allow_bid = False
            if inventory_ratio <= self.config.inventory_soft_lower_pct:
                allow_ask = False

        bid = None
        ask = None
        if allow_bid:
            if rebalance_buy_base > 0:
                buy_price_cap = state.max_rebalance_buy_price(
                    rebalance_buy_base,
                    tick_size=state.instrument.tick_size,
                    profit_ticks=self.config.rebalance_min_profit_ticks,
                )
                bid_price = state.book.best_bid.price
                if buy_price_cap is not None:
                    bid_price = min(bid_price, buy_price_cap)
                bid = OrderIntent(
                    side="buy",
                    price=bid_price,
                    quote_notional=rebalance_buy_base * bid_price,
                    reason="rebalance_open_short",
                    base_size=rebalance_buy_base,
                )
            else:
                bid = OrderIntent(side="buy", price=state.book.best_bid.price, quote_notional=bid_size, reason="join_best_bid")
        if allow_ask:
            if rebalance_sell_base > 0:
                sell_price_floor = state.min_rebalance_sell_price(
                    rebalance_sell_base,
                    tick_size=state.instrument.tick_size,
                    profit_ticks=self.config.rebalance_min_profit_ticks,
                )
                ask_price = state.book.best_ask.price
                if sell_price_floor is not None:
                    ask_price = max(ask_price, sell_price_floor)
                ask = OrderIntent(
                    side="sell",
                    price=ask_price,
                    quote_notional=rebalance_sell_base * ask_price,
                    reason="rebalance_open_long",
                    base_size=rebalance_sell_base,
                )
            else:
                ask = OrderIntent(side="sell", price=state.book.best_ask.price, quote_notional=ask_size, reason="join_best_ask")

        reason = "two_sided"
        if bid and not ask:
            reason = "fill_rebalance_buy_only" if rebalance_buy_base > 0 else "inventory_low_bid_only"
        elif ask and not bid:
            reason = "fill_rebalance_sell_only" if rebalance_sell_base > 0 else "inventory_high_ask_only"
        elif not bid and not ask:
            reason = risk_status.reason

        return QuoteDecision(reason=reason, bid=bid, ask=ask, inventory_ratio=inventory_ratio, spread_ticks=spread_ticks)

    def _visible_depth_notional(self, levels) -> Decimal:
        depth = Decimal("0")
        for level in levels[: self.config.visible_depth_levels]:
            depth += level.price * level.size
        return depth
