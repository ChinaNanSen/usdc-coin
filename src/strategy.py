from __future__ import annotations

from decimal import Decimal

from .config import StrategyConfig, TradingConfig
from .models import OrderIntent, QuoteDecision, RiskStatus
from .state import BotState
from .utils import now_ms, passive_edge_ticks, quantize_down, quantize_up


class MicroMakerStrategy:
    def __init__(self, config: StrategyConfig, trading: TradingConfig, max_orders_per_side: int = 1):
        self.config = config
        self.trading = trading
        self.max_orders_per_side = max(int(max_orders_per_side), 1)

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
        rebalance_buy_base = self._tradable_rebalance_size(state=state, side="buy")
        rebalance_sell_base = self._tradable_rebalance_size(state=state, side="sell")
        rebalance_quote_ref = max(
            entry_quote_ref,
            rebalance_buy_base * state.book.best_bid.price,
            rebalance_sell_base * state.book.best_ask.price,
        )
        rebalance_profit_ticks = self._effective_rebalance_profit_ticks(
            state=state,
            rebalance_buy_base=rebalance_buy_base,
            rebalance_sell_base=rebalance_sell_base,
        )
        rebalance_mode = self._rebalance_mode(
            state=state,
            rebalance_buy_base=rebalance_buy_base,
            rebalance_sell_base=rebalance_sell_base,
            profit_ticks=rebalance_profit_ticks,
        )
        inventory_repair_steps = self._inventory_repair_step_count(
            state=state,
            rebalance_buy_base=rebalance_buy_base,
            rebalance_sell_base=rebalance_sell_base,
        )
        min_visible_depth = rebalance_quote_ref * self.config.min_visible_depth_multiplier
        bid_depth = self._visible_depth_notional(state.book.bids)
        ask_depth = self._visible_depth_notional(state.book.asks)
        if bid_depth < min_visible_depth or ask_depth < min_visible_depth:
            return QuoteDecision(reason=f"visible depth too thin: bid={bid_depth}, ask={ask_depth}")

        if self.config.strict_alternating_sides:
            return self._decide_strict_cycle(
                state=state,
                risk_status=risk_status,
                spread_ticks=spread_ticks,
                inventory_ratio=inventory_ratio,
                fixed_entry_base_size=fixed_entry_base_size,
                quote_size=quote_size,
                rebalance_buy_base=rebalance_buy_base,
                rebalance_sell_base=rebalance_sell_base,
                rebalance_profit_ticks=rebalance_profit_ticks,
                rebalance_mode=rebalance_mode,
                inventory_repair_steps=inventory_repair_steps,
            )

        bid_quote_size = quote_size
        ask_quote_size = quote_size
        bid_base_size = fixed_entry_base_size
        ask_base_size = fixed_entry_base_size
        favorable_size_multiplier = self._favorable_size_multiplier(
            spread_ticks=spread_ticks,
            rebalance_buy_base=rebalance_buy_base,
            rebalance_sell_base=rebalance_sell_base,
        )
        if favorable_size_multiplier > Decimal("1"):
            bid_quote_size *= favorable_size_multiplier
            ask_quote_size *= favorable_size_multiplier
            bid_base_size = self._scale_entry_base_size(
                state=state,
                base_size=bid_base_size,
                multiplier=favorable_size_multiplier,
            )
            ask_base_size = self._scale_entry_base_size(
                state=state,
                base_size=ask_base_size,
                multiplier=favorable_size_multiplier,
            )
        skew_high = False
        skew_low = False
        skew_profile = self._bot_position_skew_profile(
            state=state,
            entry_base_size=fixed_entry_base_size,
            quote_size=quote_size,
        )
        if skew_profile is None and self.config.account_inventory_skew_enabled and inventory_ratio is not None:
            skew_profile = self._inventory_skew_profile(inventory_ratio=inventory_ratio)
        if skew_profile is not None:
            skew_low, skew_high, size_multiplier = skew_profile
            if skew_high:
                bid_quote_size = quote_size * size_multiplier
                if bid_base_size is not None:
                    bid_base_size *= size_multiplier
            elif skew_low:
                ask_quote_size = quote_size * size_multiplier
                if ask_base_size is not None:
                    ask_base_size *= size_multiplier

        bid = None
        ask = None
        bid_toxic_cooldown = state.is_toxic_flow_side_cooling_down("buy")
        ask_toxic_cooldown = state.is_toxic_flow_side_cooling_down("sell")
        if risk_status.allow_bid:
            if rebalance_buy_base > 0:
                bid_base_size, bid_price = self._rebalance_buy_target(
                    state=state,
                    rebalance_buy_base=rebalance_buy_base,
                    profit_ticks=rebalance_profit_ticks,
                    rebalance_mode=rebalance_mode,
                    inventory_repair_steps=inventory_repair_steps,
                )
                bid = OrderIntent(
                    side="buy",
                    price=bid_price,
                    quote_notional=bid_base_size * bid_price,
                    reason="rebalance_open_short",
                    base_size=bid_base_size,
                )
            elif rebalance_sell_base > 0 and not bid_toxic_cooldown:
                bid = self._secondary_rebalance_bid_intent(
                    state=state,
                    base_size=bid_base_size,
                    quote_notional=bid_quote_size,
                    rebalance_mode=rebalance_mode,
                    inventory_repair_steps=inventory_repair_steps,
                )
            elif not bid_toxic_cooldown:
                bid_price = self._entry_bid_price(
                    state=state,
                    spread_ticks=spread_ticks,
                    skew_low=skew_low,
                    skew_high=skew_high,
                )
                hard_buy_cap = self._buy_price_cap(state=state)
                if hard_buy_cap is not None:
                    bid_price = min(bid_price, hard_buy_cap)
                bid = self._entry_intent(
                    side="buy",
                    price=bid_price,
                    base_size=bid_base_size,
                    quote_notional=bid_quote_size,
                    reason="join_best_bid",
                )
        if risk_status.allow_ask:
            if rebalance_sell_base > 0:
                ask_base_size, ask_price = self._rebalance_sell_target(
                    state=state,
                    rebalance_sell_base=rebalance_sell_base,
                    profit_ticks=rebalance_profit_ticks,
                    rebalance_mode=rebalance_mode,
                    inventory_repair_steps=inventory_repair_steps,
                )
                ask = OrderIntent(
                    side="sell",
                    price=ask_price,
                    quote_notional=ask_base_size * ask_price,
                    reason="rebalance_open_long",
                    base_size=ask_base_size,
                )
            elif rebalance_buy_base > 0 and not ask_toxic_cooldown:
                ask = self._secondary_rebalance_ask_intent(
                    state=state,
                    base_size=ask_base_size,
                    quote_notional=ask_quote_size,
                    rebalance_mode=rebalance_mode,
                    inventory_repair_steps=inventory_repair_steps,
                )
            elif not ask_toxic_cooldown:
                ask_price = self._entry_ask_price(
                    state=state,
                    spread_ticks=spread_ticks,
                    skew_low=skew_low,
                    skew_high=skew_high,
                )
                normal_sell_floor = self._normal_sell_price_floor(state=state, allow_bid=risk_status.allow_bid)
                if normal_sell_floor is not None:
                    ask_price = max(ask_price, normal_sell_floor)
                ask = self._entry_intent(
                    side="sell",
                    price=ask_price,
                    base_size=ask_base_size,
                    quote_notional=ask_quote_size,
                    reason="join_best_ask",
                )

        bid_layers = self._build_side_layers(primary=bid, state=state)
        ask_layers = self._build_side_layers(primary=ask, state=state)

        reason = "two_sided"
        if bid and ask:
            if rebalance_buy_base > 0:
                reason = "fill_rebalance_buy_biased"
            elif rebalance_sell_base > 0:
                reason = "fill_rebalance_sell_biased"
        elif bid and not ask:
            reason = "fill_rebalance_buy_only" if rebalance_buy_base > 0 else "inventory_low_bid_only"
        elif ask and not bid:
            reason = "fill_rebalance_sell_only" if rebalance_sell_base > 0 else "inventory_high_ask_only"
        elif not bid and not ask:
            reason = risk_status.reason

        return QuoteDecision(
            reason=reason,
            bid_layers=bid_layers,
            ask_layers=ask_layers,
            inventory_ratio=inventory_ratio,
            spread_ticks=spread_ticks,
        )

    def _inventory_skew_profile(self, *, inventory_ratio: Decimal) -> tuple[bool, bool, Decimal]:
        soft_lower = min(self.config.inventory_soft_lower_pct, self.config.inventory_target_pct)
        soft_upper = max(self.config.inventory_soft_upper_pct, self.config.inventory_target_pct)
        if soft_lower >= soft_upper:
            deviation = inventory_ratio - self.config.inventory_target_pct
            if deviation >= self.config.mild_skew_threshold_pct:
                return False, True, Decimal("1") - self.config.mild_skew_size_factor
            if deviation <= -self.config.mild_skew_threshold_pct:
                return True, False, Decimal("1") - self.config.mild_skew_size_factor
            return False, False, Decimal("1")

        ramp_width = max(self.config.mild_skew_threshold_pct, Decimal("0"))
        if inventory_ratio > soft_upper:
            overflow = inventory_ratio - soft_upper
            skew_progress = Decimal("1") if ramp_width <= 0 else min(overflow / ramp_width, Decimal("1"))
            reduction = self.config.mild_skew_size_factor * skew_progress
            return False, True, Decimal("1") - reduction
        if inventory_ratio < soft_lower:
            underflow = soft_lower - inventory_ratio
            skew_progress = Decimal("1") if ramp_width <= 0 else min(underflow / ramp_width, Decimal("1"))
            reduction = self.config.mild_skew_size_factor * skew_progress
            return True, False, Decimal("1") - reduction
        return False, False, Decimal("1")

    def _favorable_size_multiplier(
        self,
        *,
        spread_ticks: Decimal,
        rebalance_buy_base: Decimal,
        rebalance_sell_base: Decimal,
    ) -> Decimal:
        min_spread_ticks = max(int(self.config.favorable_size_spread_ticks), 0)
        multiplier = max(self.config.favorable_size_multiplier, Decimal("1"))
        if min_spread_ticks <= 0 or multiplier <= Decimal("1"):
            return Decimal("1")
        if spread_ticks < Decimal(min_spread_ticks):
            return Decimal("1")
        if rebalance_buy_base > 0 or rebalance_sell_base > 0:
            return Decimal("1")
        return multiplier

    @staticmethod
    def _scale_entry_base_size(
        *,
        state: BotState,
        base_size: Decimal | None,
        multiplier: Decimal,
    ) -> Decimal | None:
        if base_size is None or not state.instrument or multiplier <= Decimal("1"):
            return base_size
        scaled = quantize_down(base_size * multiplier, state.instrument.lot_size)
        if scaled < state.instrument.min_size:
            return base_size
        return scaled

    def _bot_position_skew_profile(
        self,
        *,
        state: BotState,
        entry_base_size: Decimal | None,
        quote_size: Decimal,
    ) -> tuple[bool, bool, Decimal] | None:
        if not state.instrument or not state.book or not state.book.mid:
            return None
        strategy_position = state.strategy_position_base()
        if strategy_position == 0:
            return None

        reference_base_size = entry_base_size
        if reference_base_size is None and quote_size > 0:
            reference_base_size = quantize_down(quote_size / state.book.mid, state.instrument.lot_size)
        if reference_base_size is None or reference_base_size <= 0:
            return None

        skew_progress = min(abs(strategy_position) / reference_base_size, Decimal("1"))
        reduction = self.config.mild_skew_size_factor * skew_progress
        size_multiplier = max(Decimal("0"), Decimal("1") - reduction)
        if strategy_position > 0:
            return False, True, size_multiplier
        return True, False, size_multiplier

    def _decide_strict_cycle(
        self,
        *,
        state: BotState,
        risk_status: RiskStatus,
        spread_ticks: Decimal,
        inventory_ratio: Decimal | None,
        fixed_entry_base_size: Decimal | None,
        quote_size: Decimal,
        rebalance_buy_base: Decimal,
        rebalance_sell_base: Decimal,
        rebalance_profit_ticks: int,
        rebalance_mode: str,
        inventory_repair_steps: int,
    ) -> QuoteDecision:
        target_side = self._strict_target_side(
            state=state,
            rebalance_buy_base=rebalance_buy_base,
            rebalance_sell_base=rebalance_sell_base,
        )
        if target_side is None:
            return QuoteDecision(reason=risk_status.reason, inventory_ratio=inventory_ratio, spread_ticks=spread_ticks)

        bid = None
        ask = None

        if target_side == "buy" and risk_status.allow_bid:
            if rebalance_buy_base > 0:
                bid_base_size, bid_price = self._rebalance_buy_target(
                    state=state,
                    rebalance_buy_base=rebalance_buy_base,
                    profit_ticks=rebalance_profit_ticks,
                    rebalance_mode=rebalance_mode,
                    inventory_repair_steps=inventory_repair_steps,
                )
                bid = OrderIntent(
                    side="buy",
                    price=bid_price,
                    quote_notional=bid_base_size * bid_price,
                    reason="rebalance_open_short",
                    base_size=bid_base_size,
                )
            else:
                bid_price = state.book.best_bid.price
                hard_buy_cap = self._buy_price_cap(state=state)
                if hard_buy_cap is not None:
                    bid_price = min(bid_price, hard_buy_cap)
                bid = self._entry_intent(
                    side="buy",
                    price=bid_price,
                    base_size=fixed_entry_base_size,
                    quote_notional=quote_size,
                    reason="join_best_bid",
                )

        if target_side == "sell" and risk_status.allow_ask:
            if rebalance_sell_base > 0:
                ask_base_size, ask_price = self._rebalance_sell_target(
                    state=state,
                    rebalance_sell_base=rebalance_sell_base,
                    profit_ticks=rebalance_profit_ticks,
                    rebalance_mode=rebalance_mode,
                    inventory_repair_steps=inventory_repair_steps,
                )
                ask = OrderIntent(
                    side="sell",
                    price=ask_price,
                    quote_notional=ask_base_size * ask_price,
                    reason="rebalance_open_long",
                    base_size=ask_base_size,
                )
            else:
                ask_price = state.book.best_ask.price
                sell_price_floor = self._sell_price_floor(state=state)
                if sell_price_floor is not None:
                    ask_price = max(ask_price, sell_price_floor)
                ask = self._entry_intent(
                    side="sell",
                    price=ask_price,
                    base_size=fixed_entry_base_size,
                    quote_notional=quote_size,
                    reason="join_best_ask",
                )

        if bid:
            reason = "fill_rebalance_buy_only" if rebalance_buy_base > 0 else "strict_cycle_buy_only"
        elif ask:
            reason = "fill_rebalance_sell_only" if rebalance_sell_base > 0 else "strict_cycle_sell_only"
        else:
            reason = risk_status.reason
        return QuoteDecision(reason=reason, bid=bid, ask=ask, inventory_ratio=inventory_ratio, spread_ticks=spread_ticks)

    def _strict_target_side(
        self,
        *,
        state: BotState,
        rebalance_buy_base: Decimal,
        rebalance_sell_base: Decimal,
    ) -> str | None:
        live_orders = state.bot_orders()
        if live_orders:
            filled_order = next((order for order in live_orders if order.filled_size > 0), None)
            if filled_order is not None:
                return filled_order.side
            if rebalance_buy_base > 0:
                return "buy"
            if rebalance_sell_base > 0:
                return "sell"
            return live_orders[0].side

        if rebalance_buy_base > 0:
            return "buy"
        if rebalance_sell_base > 0:
            return "sell"
        if state.last_trade is None:
            return "buy"
        if state.last_trade.side == "sell":
            return "buy"
        if state.last_trade.side == "buy":
            return "sell"
        return None

    def _visible_depth_notional(self, levels) -> Decimal:
        depth = Decimal("0")
        for level in levels[: self.config.visible_depth_levels]:
            depth += level.price * level.size
        return depth

    def _buy_price_cap(self, *, state: BotState) -> Decimal | None:
        if self.config.normal_buy_price_cap <= 0:
            return None
        if not state.instrument:
            return None
        return quantize_down(self.config.normal_buy_price_cap, state.instrument.tick_size)

    def _normal_sell_price_floor(self, *, state: BotState, allow_bid: bool) -> Decimal | None:
        if allow_bid:
            return None
        return self._sell_price_floor(state=state)

    def _rebalance_bid_price(
        self,
        *,
        state: BotState,
        base_size: Decimal,
        profit_ticks: int,
        inventory_repair_steps: int = 0,
    ) -> Decimal:
        bid_price = self._rebalance_bid_market_price(
            state=state,
            profit_ticks=profit_ticks,
            inventory_repair_steps=inventory_repair_steps,
        )
        buy_price_cap = state.max_rebalance_buy_price(
            base_size,
            tick_size=state.instrument.tick_size,
            profit_ticks=profit_ticks,
        )
        if buy_price_cap is not None:
            bid_price = min(bid_price, buy_price_cap)
        return quantize_down(bid_price, state.instrument.tick_size)

    def _rebalance_ask_price(
        self,
        *,
        state: BotState,
        base_size: Decimal,
        profit_ticks: int,
        inventory_repair_steps: int = 0,
    ) -> Decimal:
        ask_price = self._rebalance_ask_market_price(
            state=state,
            profit_ticks=profit_ticks,
            inventory_repair_steps=inventory_repair_steps,
        )
        sell_price_floor = state.min_rebalance_sell_price(
            base_size,
            tick_size=state.instrument.tick_size,
            profit_ticks=profit_ticks,
        )
        if sell_price_floor is not None:
            ask_price = max(ask_price, sell_price_floor)
        return quantize_up(ask_price, state.instrument.tick_size)

    def _rebalance_buy_target(
        self,
        *,
        state: BotState,
        rebalance_buy_base: Decimal,
        profit_ticks: int,
        rebalance_mode: str,
        inventory_repair_steps: int = 0,
    ) -> tuple[Decimal, Decimal]:
        bid_market_price = self._rebalance_bid_market_price(
            state=state,
            profit_ticks=profit_ticks,
            inventory_repair_steps=inventory_repair_steps,
        )
        bid_base_size = state.profitable_rebalance_buy_size(
            bid_market_price,
            tick_size=state.instrument.tick_size,
            profit_ticks=profit_ticks,
        )
        if bid_base_size >= state.instrument.min_size:
            bid_price = self._rebalance_bid_price(
                state=state,
                base_size=bid_base_size,
                profit_ticks=profit_ticks,
                inventory_repair_steps=inventory_repair_steps,
            )
            return bid_base_size, bid_price
        if profit_ticks <= 0:
            bid_base_size = self._competitive_rebalance_base_size(
                state=state,
                rebalance_base=rebalance_buy_base,
                rebalance_mode=rebalance_mode,
                inventory_repair_steps=inventory_repair_steps,
            )
            if bid_base_size >= state.instrument.min_size:
                bid_price = bid_market_price
                if rebalance_mode == "release":
                    buy_price_cap = state.max_rebalance_buy_price(
                        bid_base_size,
                        tick_size=state.instrument.tick_size,
                        profit_ticks=-max(self.config.rebalance_release_max_negative_ticks, 0),
                    )
                else:
                    buy_price_cap = state.max_rebalance_buy_price(
                        bid_base_size,
                        tick_size=state.instrument.tick_size,
                        profit_ticks=0,
                    )
                if buy_price_cap is not None:
                    bid_price = min(bid_price, buy_price_cap)
                return bid_base_size, quantize_down(bid_price, state.instrument.tick_size)
        bid_price = self._rebalance_bid_price(
            state=state,
            base_size=rebalance_buy_base,
            profit_ticks=profit_ticks,
            inventory_repair_steps=inventory_repair_steps,
        )
        return rebalance_buy_base, bid_price

    def _rebalance_sell_target(
        self,
        *,
        state: BotState,
        rebalance_sell_base: Decimal,
        profit_ticks: int,
        rebalance_mode: str,
        inventory_repair_steps: int = 0,
    ) -> tuple[Decimal, Decimal]:
        ask_market_price = self._rebalance_ask_market_price(
            state=state,
            profit_ticks=profit_ticks,
            inventory_repair_steps=inventory_repair_steps,
        )
        ask_base_size = state.profitable_rebalance_sell_size(
            ask_market_price,
            tick_size=state.instrument.tick_size,
            profit_ticks=profit_ticks,
        )
        if ask_base_size >= state.instrument.min_size:
            ask_price = self._rebalance_ask_price(
                state=state,
                base_size=ask_base_size,
                profit_ticks=profit_ticks,
                inventory_repair_steps=inventory_repair_steps,
            )
            return ask_base_size, ask_price
        if profit_ticks <= 0:
            ask_base_size = self._competitive_rebalance_base_size(
                state=state,
                rebalance_base=rebalance_sell_base,
                rebalance_mode=rebalance_mode,
                inventory_repair_steps=inventory_repair_steps,
            )
            if ask_base_size >= state.instrument.min_size:
                ask_price = ask_market_price
                if rebalance_mode == "release":
                    sell_price_floor = state.min_rebalance_sell_price(
                        ask_base_size,
                        tick_size=state.instrument.tick_size,
                        profit_ticks=-max(self.config.rebalance_release_max_negative_ticks, 0),
                    )
                else:
                    sell_price_floor = state.min_rebalance_sell_price(
                        ask_base_size,
                        tick_size=state.instrument.tick_size,
                        profit_ticks=0,
                    )
                if sell_price_floor is not None:
                    ask_price = max(ask_price, sell_price_floor)
                return ask_base_size, quantize_up(ask_price, state.instrument.tick_size)
        ask_price = self._rebalance_ask_price(
            state=state,
            base_size=rebalance_sell_base,
            profit_ticks=profit_ticks,
            inventory_repair_steps=inventory_repair_steps,
        )
        return rebalance_sell_base, ask_price

    def _rebalance_bid_market_price(
        self,
        *,
        state: BotState,
        profit_ticks: int,
        inventory_repair_steps: int = 0,
    ) -> Decimal:
        bid_price = state.book.best_bid.price
        bid_price = self._apply_rebalance_buy_improvement(
            state=state,
            price=bid_price,
            inventory_repair_steps=inventory_repair_steps,
            allow_inside_spread=profit_ticks <= 0,
        )
        hard_buy_cap = self._buy_price_cap(state=state)
        if hard_buy_cap is not None:
            bid_price = min(bid_price, hard_buy_cap)
        return quantize_down(bid_price, state.instrument.tick_size)

    def _rebalance_ask_market_price(
        self,
        *,
        state: BotState,
        profit_ticks: int,
        inventory_repair_steps: int = 0,
    ) -> Decimal:
        ask_price = state.book.best_ask.price
        ask_price = self._apply_rebalance_sell_improvement(
            state=state,
            price=ask_price,
            inventory_repair_steps=inventory_repair_steps,
            allow_inside_spread=profit_ticks <= 0,
        )
        return quantize_up(ask_price, state.instrument.tick_size)

    def _entry_bid_price(
        self,
        *,
        state: BotState,
        spread_ticks: Decimal,
        skew_low: bool,
        skew_high: bool,
    ) -> Decimal:
        bid_price = state.book.best_bid.price
        tick_size = state.instrument.tick_size
        if skew_high:
            if spread_ticks <= Decimal(self.config.min_spread_ticks):
                return bid_price
            passive_pull = bid_price - tick_size
            return quantize_down(max(passive_pull, tick_size), tick_size)
        if skew_low and spread_ticks > Decimal(self.config.min_spread_ticks):
            improved = bid_price + tick_size
            if improved < state.book.best_ask.price:
                return quantize_down(improved, tick_size)
        return bid_price

    def _sell_price_floor(self, *, state: BotState) -> Decimal | None:
        if self.config.normal_sell_price_floor <= 0:
            return None
        if not state.instrument:
            return None
        return quantize_up(self.config.normal_sell_price_floor, state.instrument.tick_size)

    def _entry_ask_price(
        self,
        *,
        state: BotState,
        spread_ticks: Decimal,
        skew_low: bool,
        skew_high: bool,
    ) -> Decimal:
        ask_price = state.book.best_ask.price
        tick_size = state.instrument.tick_size
        if skew_low:
            if spread_ticks <= Decimal(self.config.min_spread_ticks):
                return ask_price
            return quantize_up(ask_price + tick_size, tick_size)
        if skew_high and spread_ticks > Decimal(self.config.min_spread_ticks):
            improved = ask_price - tick_size
            if improved > state.book.best_bid.price:
                return quantize_up(improved, tick_size)
        return ask_price

    def _secondary_rebalance_bid_intent(
        self,
        *,
        state: BotState,
        base_size: Decimal | None,
        quote_notional: Decimal,
        rebalance_mode: str,
        inventory_repair_steps: int = 0,
    ) -> OrderIntent | None:
        tick_offset = self._secondary_rebalance_price_offset_ticks(
            state=state,
            side="buy",
            rebalance_mode=rebalance_mode,
        )
        tick_size = state.instrument.tick_size
        bid_price = state.book.best_bid.price - tick_size * Decimal(tick_offset)
        bid_price = quantize_down(max(bid_price, tick_size), tick_size)
        hard_buy_cap = self._buy_price_cap(state=state)
        if hard_buy_cap is not None:
            bid_price = min(bid_price, hard_buy_cap)
        return self._secondary_rebalance_intent(
            state=state,
            side="buy",
            price=bid_price,
            base_size=base_size,
            quote_notional=quote_notional,
            reason="rebalance_secondary_bid",
            rebalance_mode=rebalance_mode,
            inventory_repair_steps=inventory_repair_steps,
        )

    def _secondary_rebalance_ask_intent(
        self,
        *,
        state: BotState,
        base_size: Decimal | None,
        quote_notional: Decimal,
        rebalance_mode: str,
        inventory_repair_steps: int = 0,
    ) -> OrderIntent | None:
        tick_offset = self._secondary_rebalance_price_offset_ticks(
            state=state,
            side="sell",
            rebalance_mode=rebalance_mode,
        )
        tick_size = state.instrument.tick_size
        ask_price = state.book.best_ask.price + tick_size * Decimal(tick_offset)
        ask_price = quantize_up(ask_price, tick_size)
        return self._secondary_rebalance_intent(
            state=state,
            side="sell",
            price=ask_price,
            base_size=base_size,
            quote_notional=quote_notional,
            reason="rebalance_secondary_ask",
            rebalance_mode=rebalance_mode,
            inventory_repair_steps=inventory_repair_steps,
        )

    def _secondary_rebalance_intent(
        self,
        *,
        state: BotState,
        side: str,
        price: Decimal,
        base_size: Decimal | None,
        quote_notional: Decimal,
        reason: str,
        rebalance_mode: str,
        inventory_repair_steps: int = 0,
    ) -> OrderIntent | None:
        if not state.instrument or price <= 0:
            return None
        factor = self._secondary_rebalance_size_factor(
            state=state,
            side=side,
            rebalance_mode=rebalance_mode,
            inventory_repair_steps=inventory_repair_steps,
        )
        if factor <= 0:
            return None
        edge_factor = self._secondary_positive_edge_size_factor(
            state=state,
            side=side,
            price=price,
        )
        if edge_factor is None:
            return None
        factor *= edge_factor
        if factor <= 0:
            return None

        scaled_base_size: Decimal | None = None
        scaled_quote_notional = quote_notional * factor
        if base_size is not None:
            scaled_base_size = quantize_down(base_size * factor, state.instrument.lot_size)
            if scaled_base_size < state.instrument.min_size:
                return None
            scaled_quote_notional = scaled_base_size * price

        projected_base_size = self._projected_base_size(
            state=state,
            price=price,
            base_size=scaled_base_size,
            quote_notional=scaled_quote_notional,
        )
        if projected_base_size is None:
            return None

        return self._entry_intent(
            side=side,
            price=price,
            base_size=scaled_base_size,
            quote_notional=scaled_quote_notional,
            reason=reason,
        )

    def _entry_base_size(self, *, state: BotState) -> Decimal | None:
        if self.trading.entry_base_size <= 0:
            return None
        if not state.instrument:
            return None
        return quantize_up(self.trading.entry_base_size, state.instrument.lot_size)

    def _build_side_layers(self, *, primary: OrderIntent | None, state: BotState) -> tuple[OrderIntent, ...]:
        if primary is None:
            return ()
        layers = [primary]
        if self.max_orders_per_side > 1:
            secondary = self._secondary_entry_layer(primary=primary, state=state)
            if secondary is not None:
                layers.append(secondary)
        return tuple(layers[: self.max_orders_per_side])

    def _secondary_entry_layer(self, *, primary: OrderIntent, state: BotState) -> OrderIntent | None:
        if not state.instrument:
            return None
        tick_size = state.instrument.tick_size
        spread_ticks = state.book.spread / tick_size if state.book and tick_size > 0 else Decimal("0")
        if spread_ticks < Decimal("2"):
            return None
        if primary.reason == "join_best_bid":
            layered_price = quantize_down(max(primary.price - tick_size, tick_size), tick_size)
            hard_buy_cap = self._buy_price_cap(state=state)
            if hard_buy_cap is not None:
                layered_price = min(layered_price, hard_buy_cap)
            if layered_price <= 0 or layered_price == primary.price:
                return None
            if not self._secondary_entry_layer_passes_edge_filter(state=state, side="buy", price=layered_price):
                return None
            return self._entry_intent(
                side="buy",
                price=layered_price,
                base_size=primary.base_size,
                quote_notional=primary.quote_notional,
                reason="join_second_bid",
            )
        if primary.reason == "join_best_ask":
            layered_price = quantize_up(primary.price + tick_size, tick_size)
            sell_floor = self._sell_price_floor(state=state)
            if sell_floor is not None:
                layered_price = max(layered_price, sell_floor)
            if layered_price == primary.price:
                return None
            if not self._secondary_entry_layer_passes_edge_filter(state=state, side="sell", price=layered_price):
                return None
            return self._entry_intent(
                side="sell",
                price=layered_price,
                base_size=primary.base_size,
                quote_notional=primary.quote_notional,
                reason="join_second_ask",
            )
        return None

    def _effective_rebalance_profit_ticks(
        self,
        *,
        state: BotState,
        rebalance_buy_base: Decimal,
        rebalance_sell_base: Decimal,
    ) -> int:
        profit_ticks = max(self.config.rebalance_min_profit_ticks, 0)
        if profit_ticks <= 0:
            return 0
        if rebalance_buy_base <= 0 and rebalance_sell_base <= 0:
            return profit_ticks
        timeout_ms = int(max(self.config.rebalance_reload_timeout_seconds, 0) * 1000)
        if timeout_ms <= 0:
            return profit_ticks
        rebalance_side = "buy" if rebalance_buy_base > 0 else "sell"
        lot_age_ms = state.oldest_rebalance_lot_age_ms(rebalance_side, reference_ms=now_ms())
        if lot_age_ms is None or lot_age_ms < timeout_ms:
            return profit_ticks
        oldest_lot = state.oldest_rebalance_lot(rebalance_side)
        if oldest_lot is None:
            return profit_ticks
        if not self._rebalance_reload_condition_changed(state=state, rebalance_side=rebalance_side, lot=oldest_lot):
            return profit_ticks
        return 0

    def _rebalance_mode(
        self,
        *,
        state: BotState,
        rebalance_buy_base: Decimal,
        rebalance_sell_base: Decimal,
        profit_ticks: int,
    ) -> str:
        if rebalance_buy_base <= 0 and rebalance_sell_base <= 0:
            return "fresh"
        if profit_ticks > 0:
            return "fresh"
        rebalance_side = "buy" if rebalance_buy_base > 0 else "sell"
        lot_age_ms = state.oldest_rebalance_lot_age_ms(rebalance_side, reference_ms=now_ms())
        oldest_lot = state.oldest_rebalance_lot(rebalance_side)
        if lot_age_ms is None or oldest_lot is None:
            return "aged"

        max_age_ms = int(max(self.config.rebalance_max_order_age_seconds, 0) * 1000)
        drift_ticks = self._rebalance_lot_drift_ticks(state=state, lot=oldest_lot)
        if max_age_ms > 0 and lot_age_ms >= max_age_ms:
            return "release"
        if drift_ticks >= max(int(self.config.rebalance_drift_ticks), 0):
            return "release"
        return "aged"

    @staticmethod
    def _rebalance_reload_condition_changed(*, state: BotState, rebalance_side: str, lot) -> bool:
        if not state.book or not state.book.best_bid or not state.book.best_ask:
            return False
        if lot.reference_best_bid is None or lot.reference_best_ask is None:
            return False
        if state.book.best_bid.price != lot.reference_best_bid:
            return True
        if state.book.best_ask.price != lot.reference_best_ask:
            return True
        return False

    @staticmethod
    def _rebalance_lot_drift_ticks(*, state: BotState, lot) -> int:
        if not state.instrument or not state.book or not state.book.best_bid or not state.book.best_ask:
            return 0
        tick_size = state.instrument.tick_size
        if tick_size <= 0:
            return 0
        drift_ticks = Decimal("0")
        if lot.reference_best_bid is not None:
            drift_ticks = max(drift_ticks, abs(state.book.best_bid.price - lot.reference_best_bid) / tick_size)
        if lot.reference_best_ask is not None:
            drift_ticks = max(drift_ticks, abs(state.book.best_ask.price - lot.reference_best_ask) / tick_size)
        return int(drift_ticks)

    def _inventory_repair_step_count(
        self,
        *,
        state: BotState,
        rebalance_buy_base: Decimal,
        rebalance_sell_base: Decimal,
    ) -> int:
        step_ms = int(max(self.trading.order_ttl_seconds, 0) * 1000)
        if step_ms <= 0:
            return 0
        if rebalance_buy_base > 0:
            rebalance_side = "buy"
        elif rebalance_sell_base > 0:
            rebalance_side = "sell"
        else:
            return 0
        lot_age_ms = state.oldest_rebalance_lot_age_ms(rebalance_side, reference_ms=now_ms())
        if lot_age_ms is None or lot_age_ms < step_ms:
            return 0
        return int(lot_age_ms // step_ms)

    def _secondary_rebalance_size_factor(
        self,
        *,
        state: BotState,
        side: str,
        rebalance_mode: str,
        inventory_repair_steps: int,
    ) -> Decimal:
        factor = max(self.config.rebalance_secondary_size_factor, Decimal("0"))
        if factor <= 0:
            return Decimal("0")
        if inventory_repair_steps > 1 and rebalance_mode != "fresh":
            repair_penalty = min(Decimal("0.50"), Decimal(inventory_repair_steps - 1) * Decimal("0.10"))
            factor *= Decimal("1") - repair_penalty
        if rebalance_mode == "release":
            overlay_floor = min(max(self.config.rebalance_overlay_floor_factor, Decimal("0")), factor)
            factor = overlay_floor
        factor *= self._secondary_rebalance_position_taper(
            state=state,
            side=side,
            rebalance_mode=rebalance_mode,
        )
        factor *= self._secondary_rebalance_direction_taper(
            state=state,
            side=side,
        )
        return factor

    def _competitive_rebalance_base_size(
        self,
        *,
        state: BotState,
        rebalance_base: Decimal,
        rebalance_mode: str,
        inventory_repair_steps: int,
    ) -> Decimal:
        if not state.instrument:
            return rebalance_base
        reference_base_size = self._entry_base_size(state=state)
        if reference_base_size is None or reference_base_size <= 0:
            return rebalance_base
        release_factor = min(max(self.config.rebalance_release_size_factor, Decimal("0")), Decimal("1"))
        if rebalance_mode == "release":
            step_bonus = Decimal(max(inventory_repair_steps - 1, 0)) * Decimal("0.25")
            release_factor = min(Decimal("1"), release_factor + step_bonus)
        target_base_size = reference_base_size * release_factor
        if rebalance_mode == "release" and self.config.rebalance_release_excess_only:
            excess_base_size = quantize_down(
                max(rebalance_base - reference_base_size, Decimal("0")),
                state.instrument.lot_size,
            )
            if excess_base_size < state.instrument.min_size:
                return Decimal("0")
            target_base_size = min(target_base_size, excess_base_size)
        unwind_base_size = quantize_down(min(rebalance_base, target_base_size), state.instrument.lot_size)
        if unwind_base_size < state.instrument.min_size:
            if rebalance_mode == "release" and self.config.rebalance_release_excess_only:
                return Decimal("0")
            return rebalance_base
        return unwind_base_size

    def _secondary_rebalance_position_taper(self, *, state: BotState, side: str, rebalance_mode: str) -> Decimal:
        reference_base_size = self._entry_base_size(state=state)
        if reference_base_size is None or reference_base_size <= 0:
            return Decimal("1")

        adverse_position = self._secondary_rebalance_adverse_position(state=state, side=side)
        if adverse_position <= reference_base_size:
            return Decimal("1")

        fade_limit = reference_base_size * Decimal("2")
        if adverse_position >= fade_limit:
            return Decimal("0")

        floor_ratio = self._secondary_rebalance_overlay_floor_ratio()
        progress = (adverse_position - reference_base_size) / reference_base_size
        taper = Decimal("1") - progress * (Decimal("1") - floor_ratio)
        return max(floor_ratio, taper)

    def _secondary_rebalance_overlay_floor_ratio(self) -> Decimal:
        base_factor = max(self.config.rebalance_secondary_size_factor, Decimal("0"))
        if base_factor <= 0:
            return Decimal("0")
        floor_factor = min(max(self.config.rebalance_overlay_floor_factor, Decimal("0")), base_factor)
        return floor_factor / base_factor

    def _secondary_positive_edge_size_factor(
        self,
        *,
        state: BotState,
        side: str,
        price: Decimal,
    ) -> Decimal | None:
        edge_ticks = self._passive_edge_ticks(state=state, side=side, price=price)
        if edge_ticks is None:
            return None
        min_edge_ticks = max(int(self.config.secondary_min_positive_edge_ticks), 0)
        if edge_ticks < min_edge_ticks:
            return None
        full_size_edge_ticks = max(int(self.config.secondary_full_size_edge_ticks), min_edge_ticks)
        if edge_ticks >= full_size_edge_ticks:
            return Decimal("1")
        thin_factor = min(max(self.config.secondary_thin_edge_size_factor, Decimal("0")), Decimal("1"))
        if thin_factor <= 0:
            return None
        return thin_factor

    def _secondary_entry_layer_passes_edge_filter(
        self,
        *,
        state: BotState,
        side: str,
        price: Decimal,
    ) -> bool:
        required_edge_ticks = max(int(self.config.secondary_entry_layer_min_edge_ticks), 0)
        if required_edge_ticks <= 0:
            return True
        edge_ticks = self._passive_edge_ticks(state=state, side=side, price=price)
        if edge_ticks is None:
            return False
        return edge_ticks >= required_edge_ticks

    @staticmethod
    def _passive_edge_ticks(*, state: BotState, side: str, price: Decimal) -> int | None:
        if not state.instrument or not state.book:
            return None
        best_bid = state.book.best_bid.price if state.book.best_bid else None
        best_ask = state.book.best_ask.price if state.book.best_ask else None
        return passive_edge_ticks(
            side=side,
            price=price,
            best_bid=best_bid,
            best_ask=best_ask,
            tick_size=state.instrument.tick_size,
        )

    def _secondary_rebalance_direction_taper(self, *, state: BotState, side: str) -> Decimal:
        drift_limit = max(int(self.config.rebalance_drift_ticks), 0)
        adverse_drift_ticks = self._secondary_rebalance_adverse_drift_ticks(state=state, side=side)
        if drift_limit <= 0 or adverse_drift_ticks <= 0:
            return Decimal("1")
        floor_ratio = self._secondary_rebalance_overlay_floor_ratio()
        if adverse_drift_ticks >= drift_limit:
            return floor_ratio
        progress = Decimal(adverse_drift_ticks) / Decimal(drift_limit)
        taper = Decimal("1") - progress * (Decimal("1") - floor_ratio)
        return max(floor_ratio, taper)

    def _secondary_rebalance_price_offset_ticks(self, *, state: BotState, side: str, rebalance_mode: str) -> int:
        offset = max(self.config.rebalance_secondary_price_offset_ticks, 0)
        if rebalance_mode == "release":
            return offset + 1
        reference_base_size = self._entry_base_size(state=state)
        if reference_base_size is None or reference_base_size <= 0:
            return offset
        adverse_position = self._secondary_rebalance_adverse_position(state=state, side=side)
        if adverse_position > reference_base_size:
            return offset + 1
        return offset

    @staticmethod
    def _secondary_rebalance_adverse_position(*, state: BotState, side: str) -> Decimal:
        strategy_position = state.strategy_position_base()
        if side == "buy":
            return max(strategy_position, Decimal("0"))
        if side == "sell":
            return max(-strategy_position, Decimal("0"))
        return Decimal("0")

    @staticmethod
    def _secondary_rebalance_adverse_drift_ticks(*, state: BotState, side: str) -> int:
        if not state.instrument or not state.book or not state.book.best_bid or not state.book.best_ask:
            return 0
        rebalance_side = "sell" if side == "buy" else "buy"
        lot = state.oldest_rebalance_lot(rebalance_side)
        if lot is None:
            return 0
        tick_size = state.instrument.tick_size
        if tick_size <= 0:
            return 0

        adverse_ticks = Decimal("0")
        if side == "buy":
            if lot.reference_best_bid is not None:
                adverse_ticks = max(adverse_ticks, (lot.reference_best_bid - state.book.best_bid.price) / tick_size)
            if lot.reference_best_ask is not None:
                adverse_ticks = max(adverse_ticks, (lot.reference_best_ask - state.book.best_ask.price) / tick_size)
        elif side == "sell":
            if lot.reference_best_bid is not None:
                adverse_ticks = max(adverse_ticks, (state.book.best_bid.price - lot.reference_best_bid) / tick_size)
            if lot.reference_best_ask is not None:
                adverse_ticks = max(adverse_ticks, (state.book.best_ask.price - lot.reference_best_ask) / tick_size)
        return max(int(adverse_ticks), 0)

    @staticmethod
    def _available_passive_improvement_ticks(*, best_price: Decimal, opposite_price: Decimal, tick_size: Decimal) -> int:
        if tick_size <= 0:
            return 0
        spread_ticks = int((opposite_price - best_price) / tick_size)
        return max(spread_ticks - 1, 0)

    def _apply_rebalance_buy_improvement(
        self,
        *,
        state: BotState,
        price: Decimal,
        inventory_repair_steps: int,
        allow_inside_spread: bool,
    ) -> Decimal:
        if not allow_inside_spread or inventory_repair_steps <= 0 or not state.instrument or not state.book:
            return price
        best_bid = state.book.best_bid.price if state.book.best_bid else None
        best_ask = state.book.best_ask.price if state.book.best_ask else None
        if best_bid is None or best_ask is None:
            return price
        improvement_ticks = min(
            inventory_repair_steps,
            self._available_passive_improvement_ticks(
                best_price=best_bid,
                opposite_price=best_ask,
                tick_size=state.instrument.tick_size,
            ),
        )
        if improvement_ticks <= 0:
            return price
        improved = price + state.instrument.tick_size * Decimal(improvement_ticks)
        improved = min(improved, best_ask - state.instrument.tick_size)
        return quantize_down(improved, state.instrument.tick_size)

        return price

    def _apply_rebalance_sell_improvement(
        self,
        *,
        state: BotState,
        price: Decimal,
        inventory_repair_steps: int,
        allow_inside_spread: bool,
    ) -> Decimal:
        if not allow_inside_spread or inventory_repair_steps <= 0 or not state.instrument or not state.book:
            return price
        best_bid = state.book.best_bid.price if state.book.best_bid else None
        best_ask = state.book.best_ask.price if state.book.best_ask else None
        if best_bid is None or best_ask is None:
            return price
        improvement_ticks = min(
            inventory_repair_steps,
            self._available_passive_improvement_ticks(
                best_price=best_bid,
                opposite_price=best_ask,
                tick_size=state.instrument.tick_size,
            ),
        )
        if improvement_ticks <= 0:
            return price
        improved = price - state.instrument.tick_size * Decimal(improvement_ticks)
        improved = max(improved, best_bid + state.instrument.tick_size)
        return quantize_up(improved, state.instrument.tick_size)

        return price

    @staticmethod
    def _projected_base_size(
        *,
        state: BotState,
        price: Decimal,
        base_size: Decimal | None,
        quote_notional: Decimal,
    ) -> Decimal | None:
        if not state.instrument or price <= 0:
            return None
        if base_size is not None:
            return base_size
        projected_base = quantize_down(quote_notional / price, state.instrument.lot_size)
        if projected_base < state.instrument.min_size:
            return None
        return projected_base

    def _projected_inventory_ratio(
        self,
        *,
        state: BotState,
        side: str,
        base_size: Decimal,
        price: Decimal,
    ) -> Decimal | None:
        if not state.instrument or not state.book or not state.book.mid:
            return None
        base_total = state.total_balance(state.instrument.base_ccy)
        quote_total = state.total_balance(state.instrument.quote_ccy)
        quote_delta = base_size * price
        if side == "buy":
            base_total += base_size
            quote_total -= quote_delta
        elif side == "sell":
            base_total -= base_size
            quote_total += quote_delta
        else:
            return None
        if base_total < 0 or quote_total < 0:
            return None
        nav = base_total * state.book.mid + quote_total
        if nav <= 0:
            return None
        return (base_total * state.book.mid) / nav

    @staticmethod
    def _tradable_rebalance_size(*, state: BotState, side: str) -> Decimal:
        if not state.instrument:
            return Decimal("0")
        base_size = state.rebalance_base_size(side)
        if base_size < state.instrument.min_size:
            return Decimal("0")
        return base_size

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
