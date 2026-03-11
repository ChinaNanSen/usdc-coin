from __future__ import annotations

from decimal import Decimal

from .config import ShadowConfig, TradingConfig
from .executor import JournalWriter
from .models import BookSnapshot, LiveOrder, TradeTick
from .state import BotState
from .utils import quantize_down


class ShadowFillSimulator:
    def __init__(
        self,
        *,
        state: BotState,
        trading: TradingConfig,
        config: ShadowConfig,
        journal: JournalWriter,
    ):
        self.state = state
        self.trading = trading
        self.config = config
        self.journal = journal

    def on_order_placed(self, order: LiveOrder) -> None:
        self.state.reserve_shadow_order(order)
        order.queue_ahead_size = self._initial_queue_ahead(order, self.state.book)

    def on_order_canceled(self, order: LiveOrder, *, reason: str) -> None:
        self.state.release_shadow_order(order)
        self.journal.append(
            "shadow_cancel_release",
            {
                "cl_ord_id": order.cl_ord_id,
                "side": order.side,
                "reason": reason,
                "remaining_size": order.remaining_size,
            },
        )

    def on_order_amended(self, previous_order: LiveOrder, current_order: LiveOrder) -> None:
        self.state.release_shadow_order(previous_order)
        self.state.reserve_shadow_order(current_order)
        current_order.queue_ahead_size = self._initial_queue_ahead(current_order, self.state.book)

    async def on_book(self, book: BookSnapshot) -> None:
        if self.config.update_queue_from_books:
            for order in list(self.state.bot_orders()):
                visible_ahead = self._visible_queue_ahead(order, book)
                if order.queue_ahead_size > 0:
                    order.queue_ahead_size = min(order.queue_ahead_size, visible_ahead)

        if not self.config.fill_on_book_cross:
            return

        for order in list(self.state.bot_orders()):
            if order.side == "buy" and book.best_ask and order.price >= book.best_ask.price:
                self._fill_order(order, fill_size=order.remaining_size, fill_ts_ms=book.last_update_ms, reason="book_cross")
            elif order.side == "sell" and book.best_bid and order.price <= book.best_bid.price:
                self._fill_order(order, fill_size=order.remaining_size, fill_ts_ms=book.last_update_ms, reason="book_cross")

    async def on_trade(self, trade: TradeTick) -> None:
        self.state.set_last_trade(trade)
        for order in list(self.state.bot_orders()):
            if not self._trade_matches(order, trade):
                continue
            if trade.last_update_ms - order.created_at_ms < int(self.config.min_rest_seconds * 1000):
                continue

            remaining_trade_size = trade.size
            if order.queue_ahead_size > 0:
                consumed_ahead = min(order.queue_ahead_size, remaining_trade_size)
                order.queue_ahead_size -= consumed_ahead
                remaining_trade_size -= consumed_ahead

            fill_size = quantize_down(min(order.remaining_size, remaining_trade_size), self.state.instrument.lot_size)
            if fill_size <= 0:
                continue
            self._fill_order(order, fill_size=fill_size, fill_ts_ms=trade.last_update_ms, reason="trade_touch")

    def _fill_order(self, order: LiveOrder, *, fill_size: Decimal, fill_ts_ms: int, reason: str) -> None:
        if fill_size <= 0:
            return
        fill_price = order.price
        self.state.apply_shadow_fill(order, fill_size=fill_size, fill_price=fill_price, fill_ts_ms=fill_ts_ms)
        self.journal.append(
            "shadow_fill",
            {
                "cl_ord_id": order.cl_ord_id,
                "side": order.side,
                "fill_size": fill_size,
                "fill_price": fill_price,
                "reason": reason,
                "remaining_size": order.remaining_size,
            },
        )

    def _initial_queue_ahead(self, order: LiveOrder, book: BookSnapshot | None) -> Decimal:
        return self._visible_queue_ahead(order, book) * self.config.queue_ahead_fraction

    def _visible_queue_ahead(self, order: LiveOrder, book: BookSnapshot | None) -> Decimal:
        if not book:
            return Decimal("0")

        total = Decimal("0")
        if order.side == "buy":
            for level in book.bids:
                if level.price > order.price:
                    total += level.size
                    continue
                if level.price == order.price:
                    total += level.size
                break
            return total

        if order.side == "sell":
            for level in book.asks:
                if level.price < order.price:
                    total += level.size
                    continue
                if level.price == order.price:
                    total += level.size
                break
            return total

        return Decimal("0")

    @staticmethod
    def _trade_matches(order: LiveOrder, trade: TradeTick) -> bool:
        if order.side == "buy":
            return trade.side == "sell" and trade.price <= order.price
        if order.side == "sell":
            return trade.side == "buy" and trade.price >= order.price
        return False
