from __future__ import annotations

from decimal import Decimal

from .config import StrategyConfig, TradingConfig
from .models import OrderIntent, QuoteDecision, RiskStatus
from .state import BotState
from .utils import quantize_up


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

        fixed_entry_base_size = self._entry_base_size(state=state)
        quote_size = min(max(self.trading.quote_size, self.trading.min_quote_size), self.trading.max_quote_size)
        entry_quote_ref = fixed_entry_base_size * state.book.mid if fixed_entry_base_size is not None else quote_size
        inventory_ratio = state.inventory_ratio()
        rebalance_buy_base = state.rebalance_base_size("buy")
        rebalance_sell_base = state.rebalance_base_size("sell")
        rebalance_quote_ref = max(
            entry_quote_ref,
            rebalance_buy_base * state.book.best_bid.price,
            rebalance_sell_base * state.book.best_ask.price,
        )
        min_visible_depth = rebalance_quote_ref * self.config.min_visible_depth_multiplier
        bid_depth = self._visible_depth_notional(state.book.bids)
        ask_depth = self._visible_depth_notional(state.book.asks)
        if bid_depth < min_visible_depth or ask_depth < min_visible_depth:
            return QuoteDecision(reason=f"visible depth too thin: bid={bid_depth}, ask={ask_depth}")

        bid_quote_size = quote_size
        ask_quote_size = quote_size
        bid_base_size = fixed_entry_base_size
        ask_base_size = fixed_entry_base_size
        if inventory_ratio is not None:
            deviation = inventory_ratio - self.config.inventory_target_pct
            if deviation >= self.config.mild_skew_threshold_pct:
                bid_quote_size = quote_size * (Decimal("1") - self.config.mild_skew_size_factor)
                if bid_base_size is not None:
                    bid_base_size *= Decimal("1") - self.config.mild_skew_size_factor
            elif deviation <= -self.config.mild_skew_threshold_pct:
                ask_quote_size = quote_size * (Decimal("1") - self.config.mild_skew_size_factor)
                if ask_base_size is not None:
                    ask_base_size *= Decimal("1") - self.config.mild_skew_size_factor

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
                bid = self._entry_intent(
                    side="buy",
                    price=state.book.best_bid.price,
                    base_size=bid_base_size,
                    quote_notional=bid_quote_size,
                    reason="join_best_bid",
                )
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
                ask_price = state.book.best_ask.price
                normal_sell_floor = self._normal_sell_price_floor(state=state, allow_bid=allow_bid)
                if normal_sell_floor is not None:
                    ask_price = max(ask_price, normal_sell_floor)
                ask = self._entry_intent(
                    side="sell",
                    price=ask_price,
                    base_size=ask_base_size,
                    quote_notional=ask_quote_size,
                    reason="join_best_ask",
                )

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

    def _normal_sell_price_floor(self, *, state: BotState, allow_bid: bool) -> Decimal | None:
        if allow_bid:
            return None
        if self.config.normal_sell_price_floor <= 0:
            return None
        if not state.instrument:
            return None
        return quantize_up(self.config.normal_sell_price_floor, state.instrument.tick_size)

    def _entry_base_size(self, *, state: BotState) -> Decimal | None:
        if self.trading.entry_base_size <= 0:
            return None
        if not state.instrument:
            return None
        return quantize_up(self.trading.entry_base_size, state.instrument.lot_size)

    @staticmethod
    def _entry_intent(*, side: str, price: Decimal, base_size: Decimal | None, quote_notional: Decimal, reason: str) -> OrderIntent:
        if base_size is not None:
            return OrderIntent(
                side=side,
                price=price,
                quote_notional=base_size * price,
                reason=reason,
                base_size=base_size,
            )
        return OrderIntent(side=side, price=price, quote_notional=quote_notional, reason=reason)
