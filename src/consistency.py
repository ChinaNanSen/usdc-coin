from __future__ import annotations

from decimal import Decimal

from .config import RiskConfig, TradingConfig
from .models import ConsistencyReport
from .state import BotState
from .utils import is_managed_cl_ord_id, quantize_down


class StateConsistencyChecker:
    def __init__(self, *, risk: RiskConfig, trading: TradingConfig, managed_prefix: str):
        self.risk = risk
        self.trading = trading
        self.managed_prefix = managed_prefix

    def check(self, state: BotState) -> ConsistencyReport:
        instrument = state.instrument
        book = state.book
        if not instrument or not book:
            return ConsistencyReport(ok=False, reason="missing instrument or book", cancel_managed=True)

        if not book.best_bid or not book.best_ask:
            return ConsistencyReport(ok=False, reason="book top levels missing", cancel_managed=True)

        if book.best_bid.price <= 0 or book.best_ask.price <= 0:
            return ConsistencyReport(ok=False, reason="book top price invalid", cancel_managed=True)

        if book.best_bid.price >= book.best_ask.price:
            return ConsistencyReport(ok=False, reason="book crossed or locked", cancel_managed=True)

        required_ccys = {self.trading.base_ccy, self.trading.quote_ccy}
        missing_balances = [ccy for ccy in required_ccys if ccy not in state.balances]
        if missing_balances:
            return ConsistencyReport(ok=False, reason=f"missing balances: {missing_balances}", cancel_managed=True)

        foreign_orders: list[str] = []
        managed_buy_orders = 0
        managed_sell_orders = 0
        pending_buy_notional = Decimal("0")
        pending_sell_size = Decimal("0")

        for order in state.live_orders.values():
            if order.inst_id != self.trading.inst_id:
                return ConsistencyReport(ok=False, reason=f"unexpected instId on pending order: {order.inst_id}", cancel_managed=True)

            if order.price <= 0 or order.size <= 0:
                return ConsistencyReport(ok=False, reason=f"invalid live order values: {order.cl_ord_id}", cancel_managed=True)

            if order.price != quantize_down(order.price, instrument.tick_size):
                return ConsistencyReport(ok=False, reason=f"order price not aligned: {order.cl_ord_id}", cancel_managed=True)

            if order.size != quantize_down(order.size, instrument.lot_size):
                return ConsistencyReport(ok=False, reason=f"order size not aligned: {order.cl_ord_id}", cancel_managed=True)

            remaining_size = max(order.size - order.filled_size, Decimal("0"))
            if remaining_size <= 0:
                return ConsistencyReport(ok=False, reason=f"live order has no remaining size: {order.cl_ord_id}", cancel_managed=True)

            if is_managed_cl_ord_id(order.cl_ord_id, self.managed_prefix):
                if order.side == "buy":
                    managed_buy_orders += 1
                    pending_buy_notional += remaining_size * order.price
                    if self.risk.require_passive_prices_on_resync and order.price >= book.best_ask.price:
                        return ConsistencyReport(ok=False, reason=f"buy order crosses ask on resync: {order.cl_ord_id}", cancel_managed=True)
                elif order.side == "sell":
                    managed_sell_orders += 1
                    pending_sell_size += remaining_size
                    if self.risk.require_passive_prices_on_resync and order.price <= book.best_bid.price:
                        return ConsistencyReport(ok=False, reason=f"sell order crosses bid on resync: {order.cl_ord_id}", cancel_managed=True)
                else:
                    return ConsistencyReport(ok=False, reason=f"unknown managed order side: {order.side}", cancel_managed=True)
            else:
                foreign_orders.append(order.cl_ord_id or order.ord_id)

        if managed_buy_orders > self.risk.max_managed_orders_per_side:
            return ConsistencyReport(
                ok=False,
                reason=f"too many managed buy orders: {managed_buy_orders}",
                cancel_managed=True,
                managed_buy_orders=managed_buy_orders,
                managed_sell_orders=managed_sell_orders,
            )

        if managed_sell_orders > self.risk.max_managed_orders_per_side:
            return ConsistencyReport(
                ok=False,
                reason=f"too many managed sell orders: {managed_sell_orders}",
                cancel_managed=True,
                managed_buy_orders=managed_buy_orders,
                managed_sell_orders=managed_sell_orders,
            )

        if foreign_orders and self.risk.fail_on_foreign_pending_orders:
            return ConsistencyReport(
                ok=False,
                reason=f"foreign pending orders present: {foreign_orders}",
                cancel_managed=True,
                foreign_orders=tuple(foreign_orders),
                managed_buy_orders=managed_buy_orders,
                managed_sell_orders=managed_sell_orders,
                pending_buy_notional=pending_buy_notional,
                pending_sell_size=pending_sell_size,
            )

        total_quote = state.total_balance(self.trading.quote_ccy)
        total_base = state.total_balance(self.trading.base_ccy)
        if pending_buy_notional > total_quote + self.risk.balance_consistency_tolerance_quote:
            return ConsistencyReport(
                ok=False,
                reason=f"buy pending exceeds quote balance: {pending_buy_notional} > {total_quote}",
                cancel_managed=True,
                managed_buy_orders=managed_buy_orders,
                managed_sell_orders=managed_sell_orders,
                pending_buy_notional=pending_buy_notional,
                pending_sell_size=pending_sell_size,
            )

        if pending_sell_size > total_base + instrument.min_size:
            return ConsistencyReport(
                ok=False,
                reason=f"sell pending exceeds base balance: {pending_sell_size} > {total_base}",
                cancel_managed=True,
                managed_buy_orders=managed_buy_orders,
                managed_sell_orders=managed_sell_orders,
                pending_buy_notional=pending_buy_notional,
                pending_sell_size=pending_sell_size,
            )

        return ConsistencyReport(
            ok=True,
            reason="state consistent",
            cancel_managed=False,
            foreign_orders=tuple(foreign_orders),
            managed_buy_orders=managed_buy_orders,
            managed_sell_orders=managed_sell_orders,
            pending_buy_notional=pending_buy_notional,
            pending_sell_size=pending_sell_size,
        )
