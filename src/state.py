from __future__ import annotations

from collections import deque
from decimal import Decimal
import json
from pathlib import Path

from .models import Balance, BookSnapshot, FeeSnapshot, InstrumentMeta, LiveOrder, StrategyLot, TradeTick
from .utils import is_managed_cl_ord_id, now_ms, parse_decimal, quantize_down, quantize_up, to_jsonable


class BotState:
    def __init__(self, *, managed_prefix: str, state_path: str):
        self.managed_prefix = managed_prefix
        self.state_path = Path(state_path)
        self.instrument: InstrumentMeta | None = None
        self.book: BookSnapshot | None = None
        self.balances: dict[str, Balance] = {}
        self.live_orders: dict[str, LiveOrder] = {}
        self.reconnect_events: deque[int] = deque()
        self.initial_nav_quote: Decimal | None = None
        self.last_fill_ms: int | None = None
        self.runtime_state = "INIT"
        self.runtime_reason = "booting"
        self.pause_until_ms = 0
        self.stream_status = {"public_books5": False, "private_user": False}
        self.consecutive_place_failures = 0
        self.consecutive_cancel_failures = 0
        self.last_place_failure_ms = 0
        self.last_cancel_failure_ms = 0
        self.resync_required = False
        self.resync_reason = ""
        self.fee_snapshot: FeeSnapshot | None = None
        self.last_trade: TradeTick | None = None
        self.last_market_trade: TradeTick | None = None
        self.last_fee_check_ms = 0
        self.last_instrument_check_ms = 0
        self.last_consistency_check_ms = 0
        self.last_consistency_ok = False
        self.last_consistency_reason = ""
        self.consecutive_consistency_failures = 0
        self.shadow_realized_pnl_quote = Decimal("0")
        self.shadow_base_cost_quote: Decimal | None = None
        self.shadow_fill_count = 0
        self.shadow_fill_volume_quote = Decimal("0")
        self.observed_fill_count = 0
        self.observed_fill_volume_quote = Decimal("0")
        self.live_realized_pnl_quote = Decimal("0")
        self.live_position_lots: deque[StrategyLot] = deque()
        self.initial_external_base_inventory: Decimal | None = None
        self.external_base_inventory_remaining: Decimal = Decimal("0")

    def set_instrument(self, instrument: InstrumentMeta) -> None:
        self.instrument = instrument
        self.last_instrument_check_ms = now_ms()
        self._init_external_inventory_if_possible()

    def set_book(self, book: BookSnapshot) -> None:
        self.book = book
        self._init_nav_if_possible()
        self._init_shadow_cost_if_possible()

    def set_balances(self, balances: dict[str, Balance]) -> None:
        self.balances.update(balances)
        self._init_nav_if_possible()
        self._init_shadow_cost_if_possible()
        self._init_external_inventory_if_possible()

    def seed_shadow_balances(self, *, base_ccy: str, quote_ccy: str, base_balance: Decimal, quote_balance: Decimal) -> None:
        self.balances[base_ccy] = Balance(ccy=base_ccy, total=base_balance, available=base_balance)
        self.balances[quote_ccy] = Balance(ccy=quote_ccy, total=quote_balance, available=quote_balance)
        self._init_nav_if_possible()
        self._init_shadow_cost_if_possible()

    def set_fee_snapshot(self, snapshot: FeeSnapshot) -> None:
        self.fee_snapshot = snapshot
        self.last_fee_check_ms = snapshot.checked_at_ms

    def set_last_trade(self, trade: TradeTick) -> None:
        self.last_trade = trade

    def set_last_market_trade(self, trade: TradeTick) -> None:
        self.last_market_trade = trade

    def load_persisted_accounting(self) -> dict[str, int | str] | None:
        if not self.state_path.exists():
            return None
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

        self.initial_nav_quote = self._optional_decimal(payload.get("initial_nav_quote"))
        self.last_fill_ms = self._optional_int(payload.get("last_fill_ms"))
        self.shadow_realized_pnl_quote = parse_decimal(payload.get("shadow_realized_pnl_quote") or "0")
        self.shadow_base_cost_quote = self._optional_decimal(payload.get("shadow_base_cost_quote"))
        self.shadow_fill_count = self._optional_int(payload.get("shadow_fill_count")) or 0
        self.shadow_fill_volume_quote = parse_decimal(payload.get("shadow_fill_volume_quote") or "0")
        self.observed_fill_count = self._optional_int(payload.get("observed_fill_count")) or 0
        self.observed_fill_volume_quote = parse_decimal(payload.get("observed_fill_volume_quote") or "0")
        self.live_realized_pnl_quote = parse_decimal(payload.get("live_realized_pnl_quote") or "0")
        self.initial_external_base_inventory = self._optional_decimal(payload.get("initial_external_base_inventory"))
        self.external_base_inventory_remaining = parse_decimal(payload.get("external_base_inventory_remaining") or "0")

        restored_lots: deque[StrategyLot] = deque()
        for item in payload.get("live_position_lots", []):
            lot = self._parse_strategy_lot(item)
            if lot is not None:
                restored_lots.append(lot)
        self.live_position_lots = restored_lots

        last_trade = self._parse_trade_tick(payload.get("last_trade"))
        if last_trade is not None:
            self.last_trade = last_trade
        last_market_trade = self._parse_trade_tick(payload.get("last_market_trade"))
        if last_market_trade is not None:
            self.last_market_trade = last_market_trade

        return {
            "live_lot_count": len(self.live_position_lots),
            "live_realized_pnl_quote": str(self.live_realized_pnl_quote),
            "observed_fill_count": self.observed_fill_count,
        }

    def apply_account_update(self, payload: dict) -> None:
        for item in payload.get("details", []):
            ccy = item.get("ccy")
            if not ccy:
                continue
            total = parse_decimal(item.get("cashBal") or item.get("eq") or "0")
            available = parse_decimal(item.get("availBal") or item.get("availEq") or total)
            frozen = max(total - available, Decimal("0"))
            self.balances[ccy] = Balance(ccy=ccy, total=total, available=available, frozen=frozen)
        self._init_nav_if_possible()

    def replace_live_orders(self, payloads: list[dict], *, source: str = "rest_sync") -> None:
        self.live_orders = {}
        for payload in payloads:
            self.apply_order_update(payload, source=source)

    def apply_order_update(self, payload: dict, *, source: str = "ws") -> LiveOrder:
        cl_ord_id = payload.get("clOrdId") or payload.get("ordId") or ""
        state = str(payload.get("state") or "live").lower()
        previous = self.live_orders.get(cl_ord_id)
        order = LiveOrder(
            inst_id=payload.get("instId", self.instrument.inst_id if self.instrument else ""),
            side=str(payload.get("side") or ""),
            ord_id=str(payload.get("ordId") or ""),
            cl_ord_id=cl_ord_id,
            price=parse_decimal(payload.get("px") or "0"),
            size=parse_decimal(payload.get("sz") or "0"),
            filled_size=parse_decimal(payload.get("accFillSz") or payload.get("fillSz") or "0"),
            state=state,
            created_at_ms=int(payload.get("cTime") or now_ms()),
            updated_at_ms=int(payload.get("uTime") or now_ms()),
            source=source,
            cancel_requested=previous.cancel_requested if previous else False,
        )
        previous_filled = previous.filled_size if previous else Decimal("0")
        fill_delta = order.filled_size - previous_filled
        if fill_delta > 0:
            fill_price = parse_decimal(payload.get("fillPx") or payload.get("avgPx") or payload.get("px") or "0")
            self.observed_fill_count += 1
            if fill_price > 0:
                self.observed_fill_volume_quote += fill_delta * fill_price
                if is_managed_cl_ord_id(cl_ord_id, self.managed_prefix):
                    self._record_live_fill(
                        side=order.side,
                        fill_size=fill_delta,
                        fill_price=fill_price,
                        fill_ts_ms=order.updated_at_ms,
                        cl_ord_id=cl_ord_id,
                        order_price=order.price,
                    )
        if state == "filled":
            self.last_fill_ms = order.updated_at_ms
        if order.is_terminal:
            self.live_orders.pop(cl_ord_id, None)
        else:
            self.live_orders[cl_ord_id] = order
        return order

    def bot_orders(self, side: str | None = None) -> list[LiveOrder]:
        orders = [order for order in self.live_orders.values() if is_managed_cl_ord_id(order.cl_ord_id, self.managed_prefix)]
        if side:
            orders = [order for order in orders if order.side == side]
        return sorted(orders, key=lambda item: item.created_at_ms)

    def reserve_shadow_order(self, order: LiveOrder) -> None:
        if not self.instrument:
            raise RuntimeError("instrument missing for shadow reserve")
        if order.side == "buy":
            reserved_quote = order.remaining_size * order.price
            self._adjust_balance(self.instrument.quote_ccy, available_delta=-reserved_quote, frozen_delta=reserved_quote)
            return
        if order.side == "sell":
            self._adjust_balance(self.instrument.base_ccy, available_delta=-order.remaining_size, frozen_delta=order.remaining_size)
            return
        raise ValueError(f"unsupported side for shadow reserve: {order.side}")

    def release_shadow_order(self, order: LiveOrder) -> None:
        if not self.instrument:
            raise RuntimeError("instrument missing for shadow release")
        if order.remaining_size <= 0:
            return
        if order.side == "buy":
            reserved_quote = order.remaining_size * order.price
            self._adjust_balance(self.instrument.quote_ccy, available_delta=reserved_quote, frozen_delta=-reserved_quote)
            return
        if order.side == "sell":
            self._adjust_balance(self.instrument.base_ccy, available_delta=order.remaining_size, frozen_delta=-order.remaining_size)
            return
        raise ValueError(f"unsupported side for shadow release: {order.side}")

    def apply_shadow_fill(self, order: LiveOrder, *, fill_size: Decimal, fill_price: Decimal, fill_ts_ms: int) -> None:
        if not self.instrument:
            raise RuntimeError("instrument missing for shadow fill")
        if fill_size <= 0:
            return
        fill_size = min(fill_size, order.remaining_size)
        if fill_size <= 0:
            return

        self._init_shadow_cost_if_possible()
        quote_amount = fill_size * fill_price
        base_ccy = self.instrument.base_ccy
        quote_ccy = self.instrument.quote_ccy

        if order.side == "buy":
            self._adjust_balance(quote_ccy, total_delta=-quote_amount, frozen_delta=-quote_amount)
            self._adjust_balance(base_ccy, total_delta=fill_size, available_delta=fill_size)
            self.shadow_base_cost_quote = (self.shadow_base_cost_quote or Decimal("0")) + quote_amount
        elif order.side == "sell":
            base_before = self.total_balance(base_ccy)
            average_cost = fill_price
            if base_before > 0 and self.shadow_base_cost_quote is not None:
                average_cost = self.shadow_base_cost_quote / base_before
            realized = quote_amount - (average_cost * fill_size)
            self.shadow_realized_pnl_quote += realized
            self._adjust_balance(base_ccy, total_delta=-fill_size, frozen_delta=-fill_size)
            self._adjust_balance(quote_ccy, total_delta=quote_amount, available_delta=quote_amount)
            if self.shadow_base_cost_quote is not None:
                self.shadow_base_cost_quote -= average_cost * fill_size
                if self.shadow_base_cost_quote < 0:
                    self.shadow_base_cost_quote = Decimal("0")
        else:
            raise ValueError(f"unsupported side for shadow fill: {order.side}")

        order.filled_size += fill_size
        order.updated_at_ms = fill_ts_ms
        order.queue_ahead_size = Decimal("0")
        self.last_fill_ms = fill_ts_ms
        self.last_trade = TradeTick(
            ts_ms=fill_ts_ms,
            received_ms=fill_ts_ms,
            price=fill_price,
            size=fill_size,
            side=order.side,
            trade_id=order.cl_ord_id,
            order_price=order.price,
        )
        self.shadow_fill_count += 1
        self.shadow_fill_volume_quote += quote_amount

        if order.remaining_size <= 0:
            order.state = "filled"
            self.live_orders.pop(order.cl_ord_id, None)
        else:
            self.live_orders[order.cl_ord_id] = order

    def set_stream_status(self, stream_name: str, connected: bool) -> None:
        self.stream_status[stream_name] = connected

    def streams_ready(self, *, require_public: bool, require_private: bool) -> bool:
        public_ok = self.stream_status.get("public_books5", False) if require_public else True
        private_ok = self.stream_status.get("private_user", False) if require_private else True
        return public_ok and private_ok

    def set_runtime_state(self, runtime_state: str, reason: str = "") -> None:
        self.runtime_state = runtime_state
        if reason:
            self.runtime_reason = reason

    def set_pause(self, *, reason: str, duration_ms: int) -> None:
        self.runtime_state = "PAUSED"
        self.runtime_reason = reason
        self.pause_until_ms = max(self.pause_until_ms, now_ms() + max(duration_ms, 0))

    def clear_pause_if_elapsed(self) -> None:
        if self.runtime_state == "PAUSED" and not self.resync_required and self.pause_until_ms and now_ms() >= self.pause_until_ms:
            self.runtime_state = "READY"
            self.runtime_reason = "pause elapsed"
            self.pause_until_ms = 0

    def is_pause_active(self) -> bool:
        return self.runtime_state == "PAUSED" and now_ms() < self.pause_until_ms

    def request_resync(self, reason: str) -> None:
        self.resync_required = True
        self.resync_reason = reason

    def clear_resync(self) -> None:
        self.resync_required = False
        self.resync_reason = ""

    def mark_reconnect(self) -> None:
        current = now_ms()
        self.reconnect_events.append(current)
        threshold = current - 300_000
        while self.reconnect_events and self.reconnect_events[0] < threshold:
            self.reconnect_events.popleft()

    def reconnect_count_5m(self) -> int:
        threshold = now_ms() - 300_000
        while self.reconnect_events and self.reconnect_events[0] < threshold:
            self.reconnect_events.popleft()
        return len(self.reconnect_events)

    def record_place_result(self, success: bool) -> None:
        if success:
            self.consecutive_place_failures = 0
            self.last_place_failure_ms = 0
            return
        self.consecutive_place_failures += 1
        self.last_place_failure_ms = now_ms()

    def record_cancel_result(self, success: bool) -> None:
        if success:
            self.consecutive_cancel_failures = 0
            self.last_cancel_failure_ms = 0
            return
        self.consecutive_cancel_failures += 1
        self.last_cancel_failure_ms = now_ms()

    def reset_place_failures(self) -> None:
        self.consecutive_place_failures = 0
        self.last_place_failure_ms = 0

    def reset_cancel_failures(self) -> None:
        self.consecutive_cancel_failures = 0
        self.last_cancel_failure_ms = 0

    def place_failure_cooldown_remaining_ms(self, cooldown_seconds: float) -> int:
        if self.consecutive_place_failures <= 0 or self.last_place_failure_ms <= 0:
            return 0
        remaining = int(cooldown_seconds * 1000) - (now_ms() - self.last_place_failure_ms)
        return max(remaining, 0)

    def cancel_failure_cooldown_remaining_ms(self, cooldown_seconds: float) -> int:
        if self.consecutive_cancel_failures <= 0 or self.last_cancel_failure_ms <= 0:
            return 0
        remaining = int(cooldown_seconds * 1000) - (now_ms() - self.last_cancel_failure_ms)
        return max(remaining, 0)

    def record_consistency_result(self, ok: bool, reason: str) -> None:
        self.last_consistency_check_ms = now_ms()
        self.last_consistency_ok = ok
        self.last_consistency_reason = reason
        self.consecutive_consistency_failures = 0 if ok else self.consecutive_consistency_failures + 1

    def free_balance(self, ccy: str) -> Decimal:
        return self.balances.get(ccy, Balance(ccy=ccy, total=Decimal("0"), available=Decimal("0"))).available

    def total_balance(self, ccy: str) -> Decimal:
        return self.balances.get(ccy, Balance(ccy=ccy, total=Decimal("0"), available=Decimal("0"))).total

    def strategy_position_base(self) -> Decimal:
        return sum((lot.qty for lot in self.live_position_lots), Decimal("0"))

    def rebalance_base_size(self, side: str) -> Decimal:
        position = self.strategy_position_base()
        if side == "sell" and position > 0:
            return position
        if side == "buy" and position < 0:
            return -position
        return Decimal("0")

    def min_rebalance_sell_price(self, base_size: Decimal, *, tick_size: Decimal, profit_ticks: int) -> Decimal | None:
        if base_size <= 0:
            return None
        remaining = base_size
        max_cost: Decimal | None = None
        for lot in self.live_position_lots:
            if lot.qty <= 0:
                continue
            matched = min(remaining, lot.qty)
            if matched <= 0:
                continue
            max_cost = lot.price if max_cost is None else max(max_cost, lot.price)
            remaining -= matched
            if remaining <= 0:
                break
        if max_cost is None:
            return None
        target = max_cost + tick_size * Decimal(max(profit_ticks, 0))
        return quantize_up(target, tick_size)

    def max_rebalance_buy_price(self, base_size: Decimal, *, tick_size: Decimal, profit_ticks: int) -> Decimal | None:
        if base_size <= 0:
            return None
        remaining = base_size
        min_open_price: Decimal | None = None
        for lot in self.live_position_lots:
            if lot.qty >= 0:
                continue
            matched = min(remaining, -lot.qty)
            if matched <= 0:
                continue
            min_open_price = lot.price if min_open_price is None else min(min_open_price, lot.price)
            remaining -= matched
            if remaining <= 0:
                break
        if min_open_price is None:
            return None
        target = min_open_price - tick_size * Decimal(max(profit_ticks, 0))
        return quantize_down(target, tick_size)

    def inventory_ratio(self) -> Decimal | None:
        if not self.instrument or not self.book or not self.book.mid:
            return None
        base_total = self.total_balance(self.instrument.base_ccy)
        quote_total = self.total_balance(self.instrument.quote_ccy)
        nav = base_total * self.book.mid + quote_total
        if nav <= 0:
            return None
        return (base_total * self.book.mid) / nav

    def nav_quote(self) -> Decimal | None:
        if not self.instrument or not self.book or not self.book.mid:
            return None
        base_total = self.total_balance(self.instrument.base_ccy)
        quote_total = self.total_balance(self.instrument.quote_ccy)
        return base_total * self.book.mid + quote_total

    def daily_pnl_quote(self) -> Decimal | None:
        nav = self.nav_quote()
        if nav is None or self.initial_nav_quote is None:
            return None
        return nav - self.initial_nav_quote

    def live_unrealized_pnl_quote(self) -> Decimal | None:
        if not self.book or self.book.mid is None:
            return None
        return sum(((self.book.mid - lot.price) * lot.qty for lot in self.live_position_lots), Decimal("0"))

    def live_total_pnl_quote(self) -> Decimal | None:
        unrealized = self.live_unrealized_pnl_quote()
        if unrealized is None:
            return None
        return self.live_realized_pnl_quote + unrealized

    def shadow_unrealized_pnl_quote(self) -> Decimal | None:
        total_pnl = self.daily_pnl_quote()
        if total_pnl is None:
            return None
        return total_pnl - self.shadow_realized_pnl_quote

    def persist(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "instrument": self.instrument,
            "book": self.book,
            "balances": self.balances,
            "live_orders": self.live_orders,
            "initial_nav_quote": self.initial_nav_quote,
            "last_fill_ms": self.last_fill_ms,
            "runtime_state": self.runtime_state,
            "runtime_reason": self.runtime_reason,
            "pause_until_ms": self.pause_until_ms,
            "stream_status": self.stream_status,
            "consecutive_place_failures": self.consecutive_place_failures,
            "consecutive_cancel_failures": self.consecutive_cancel_failures,
            "last_place_failure_ms": self.last_place_failure_ms,
            "last_cancel_failure_ms": self.last_cancel_failure_ms,
            "resync_required": self.resync_required,
            "resync_reason": self.resync_reason,
            "fee_snapshot": self.fee_snapshot,
            "last_trade": self.last_trade,
            "last_market_trade": self.last_market_trade,
            "last_fee_check_ms": self.last_fee_check_ms,
            "last_instrument_check_ms": self.last_instrument_check_ms,
            "last_consistency_check_ms": self.last_consistency_check_ms,
            "last_consistency_ok": self.last_consistency_ok,
            "last_consistency_reason": self.last_consistency_reason,
            "consecutive_consistency_failures": self.consecutive_consistency_failures,
            "shadow_realized_pnl_quote": self.shadow_realized_pnl_quote,
            "shadow_base_cost_quote": self.shadow_base_cost_quote,
            "shadow_fill_count": self.shadow_fill_count,
            "shadow_fill_volume_quote": self.shadow_fill_volume_quote,
            "observed_fill_count": self.observed_fill_count,
            "observed_fill_volume_quote": self.observed_fill_volume_quote,
            "live_realized_pnl_quote": self.live_realized_pnl_quote,
            "live_unrealized_pnl_quote": self.live_unrealized_pnl_quote(),
            "live_total_pnl_quote": self.live_total_pnl_quote(),
            "strategy_position_base": self.strategy_position_base(),
            "live_position_lots": list(self.live_position_lots),
            "initial_external_base_inventory": self.initial_external_base_inventory,
            "external_base_inventory_remaining": self.external_base_inventory_remaining,
        }
        self.state_path.write_text(json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")

    def _init_nav_if_possible(self) -> None:
        if self.initial_nav_quote is None and self._has_balance_snapshot():
            nav = self.nav_quote()
            if nav is not None and nav > 0:
                self.initial_nav_quote = nav

    def _init_shadow_cost_if_possible(self) -> None:
        if self.shadow_base_cost_quote is None and self.instrument and self.book and self.book.mid is not None and self._has_balance_snapshot():
            self.shadow_base_cost_quote = self.total_balance(self.instrument.base_ccy) * self.book.mid

    @staticmethod
    def _optional_decimal(value) -> Decimal | None:
        if value in (None, "", "null"):
            return None
        return parse_decimal(value)

    @staticmethod
    def _optional_int(value) -> int | None:
        if value in (None, "", "null"):
            return None
        return int(value)

    @staticmethod
    def _parse_trade_tick(value) -> TradeTick | None:
        if not isinstance(value, dict):
            return None
        try:
            return TradeTick(
                ts_ms=int(value.get("ts_ms") or 0),
                price=parse_decimal(value.get("price") or "0"),
                size=parse_decimal(value.get("size") or "0"),
                side=str(value.get("side") or ""),
                received_ms=BotState._optional_int(value.get("received_ms")),
                trade_id=str(value.get("trade_id") or "") or None,
                order_price=BotState._optional_decimal(value.get("order_price")),
            )
        except (TypeError, ValueError, ArithmeticError):
            return None

    @staticmethod
    def _parse_strategy_lot(value) -> StrategyLot | None:
        if not isinstance(value, dict):
            return None
        try:
            return StrategyLot(
                qty=parse_decimal(value.get("qty") or "0"),
                price=parse_decimal(value.get("price") or "0"),
                ts_ms=int(value.get("ts_ms") or 0),
                cl_ord_id=str(value.get("cl_ord_id") or ""),
            )
        except (TypeError, ValueError, ArithmeticError):
            return None

    def _init_external_inventory_if_possible(self) -> None:
        if self.initial_external_base_inventory is not None or not self.instrument or not self._has_balance_snapshot():
            return
        self.initial_external_base_inventory = self.total_balance(self.instrument.base_ccy)
        self.external_base_inventory_remaining = self.initial_external_base_inventory

    def mark_cancel_requested(self, cl_ord_id: str) -> None:
        order = self.live_orders.get(cl_ord_id)
        if not order:
            return
        order.cancel_requested = True
        order.updated_at_ms = now_ms()

    def _adjust_balance(
        self,
        ccy: str,
        *,
        total_delta: Decimal = Decimal("0"),
        available_delta: Decimal = Decimal("0"),
        frozen_delta: Decimal = Decimal("0"),
    ) -> None:
        current = self.balances.get(ccy, Balance(ccy=ccy, total=Decimal("0"), available=Decimal("0"), frozen=Decimal("0")))
        total = current.total + total_delta
        available = current.available + available_delta
        frozen = current.frozen + frozen_delta
        if total < 0:
            total = Decimal("0")
        if available < 0:
            available = Decimal("0")
        if frozen < 0:
            frozen = Decimal("0")
        self.balances[ccy] = Balance(ccy=ccy, total=total, available=available, frozen=frozen)

    def _has_balance_snapshot(self) -> bool:
        if not self.instrument:
            return False
        return self.instrument.base_ccy in self.balances and self.instrument.quote_ccy in self.balances

    def _record_live_fill(
        self,
        *,
        side: str,
        fill_size: Decimal,
        fill_price: Decimal,
        fill_ts_ms: int,
        cl_ord_id: str,
        order_price: Decimal,
    ) -> None:
        if fill_size <= 0 or fill_price <= 0:
            return

        remaining = fill_size
        if side == "buy":
            while remaining > 0 and self.live_position_lots and self.live_position_lots[0].qty < 0:
                lot = self.live_position_lots[0]
                matched = min(remaining, -lot.qty)
                self.live_realized_pnl_quote += matched * (lot.price - fill_price)
                lot.qty += matched
                remaining -= matched
                if lot.qty == 0:
                    self.live_position_lots.popleft()
            if remaining > 0 and self.initial_external_base_inventory is not None:
                restorable = self.initial_external_base_inventory - self.external_base_inventory_remaining
                if restorable > 0:
                    restored = min(remaining, restorable)
                    self.external_base_inventory_remaining += restored
                    remaining -= restored
            if remaining > 0:
                self.live_position_lots.append(
                    StrategyLot(qty=remaining, price=fill_price, ts_ms=fill_ts_ms, cl_ord_id=cl_ord_id)
                )
        elif side == "sell":
            while remaining > 0 and self.live_position_lots and self.live_position_lots[0].qty > 0:
                lot = self.live_position_lots[0]
                matched = min(remaining, lot.qty)
                self.live_realized_pnl_quote += matched * (fill_price - lot.price)
                lot.qty -= matched
                remaining -= matched
                if lot.qty == 0:
                    self.live_position_lots.popleft()
            if remaining > 0 and self.external_base_inventory_remaining > 0:
                reduced = min(remaining, self.external_base_inventory_remaining)
                self.external_base_inventory_remaining -= reduced
                remaining -= reduced
            if remaining > 0:
                self.live_position_lots.append(
                    StrategyLot(qty=-remaining, price=fill_price, ts_ms=fill_ts_ms, cl_ord_id=cl_ord_id)
                )
        else:
            raise ValueError(f"unsupported side for live fill: {side}")

        self.last_fill_ms = fill_ts_ms
        self.last_trade = TradeTick(
            ts_ms=fill_ts_ms,
            received_ms=fill_ts_ms,
            price=fill_price,
            size=fill_size,
            side=side,
            trade_id=cl_ord_id,
            order_price=order_price,
        )
