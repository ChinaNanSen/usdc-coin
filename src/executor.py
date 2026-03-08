from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .audit_store import SQLiteAuditStore
from .config import BotConfig
from .log_labels import summarize_okx_error, translate_reason
from .models import InstrumentMeta, LiveOrder, QuoteDecision, RiskStatus
from .okx_rest import OKXAPIError, OKXRestClient
from .state import BotState
from .utils import build_cl_ord_id, decimal_to_str, is_managed_cl_ord_id, now_ms, quantize_down, to_jsonable

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .shadow import ShadowFillSimulator


class JournalWriter:
    def __init__(
        self,
        path: str,
        *,
        sqlite_store: SQLiteAuditStore | None = None,
        runtime_state_getter: Callable[[], str | None] | None = None,
        run_id: str | None = None,
    ):
        self.path = Path(path)
        self.sqlite_store = sqlite_store
        self.runtime_state_getter = runtime_state_getter
        self.run_id = run_id

    def append(self, event: str, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ts_ms = now_ms()
        runtime_state = self.runtime_state_getter() if self.runtime_state_getter else None
        record = {
            "ts_ms": ts_ms,
            "event": event,
            "runtime_state": runtime_state,
            "run_id": self.run_id,
            "payload": to_jsonable(payload),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        if self.sqlite_store:
            self.sqlite_store.append_event(
                ts_ms=ts_ms,
                event=event,
                payload=payload,
                runtime_state=runtime_state,
                run_id=self.run_id,
            )


class OrderExecutor:
    def __init__(
        self,
        *,
        rest: OKXRestClient,
        state: BotState,
        config: BotConfig,
        journal: JournalWriter,
        shadow_simulator: "ShadowFillSimulator | None" = None,
    ):
        self.rest = rest
        self.state = state
        self.config = config
        self.journal = journal
        self.shadow_simulator = shadow_simulator
        self._last_action_by_side: dict[str, int] = {}

    async def bootstrap_pending_orders(self) -> None:
        await self._sync_pending_orders(
            fail_on_foreign=self.config.risk.fail_on_foreign_pending_orders,
            cancel_managed=self.config.risk.cancel_managed_orders_on_startup,
        )

    async def reload_pending_orders(self) -> None:
        await self._sync_pending_orders(fail_on_foreign=False, cancel_managed=False)

    async def reconcile(self, decision: QuoteDecision, risk_status: RiskStatus | None = None) -> None:
        await self._reconcile_side("buy", decision.bid, risk_status=risk_status)
        await self._reconcile_side("sell", decision.ask, risk_status=risk_status)

    async def cancel_all_managed_orders(self, *, reason: str) -> None:
        for order in list(self.state.bot_orders()):
            await self._cancel_order(order, reason=reason)

    async def _sync_pending_orders(self, *, fail_on_foreign: bool, cancel_managed: bool) -> None:
        orders = await self.rest.list_pending_orders(
            inst_id=self.config.trading.inst_id,
            inst_type=self.config.trading.inst_type,
        )
        self.state.replace_live_orders(orders, source="rest_sync")
        foreign = [
            order.cl_ord_id or order.ord_id
            for order in self.state.live_orders.values()
            if not is_managed_cl_ord_id(order.cl_ord_id, self.config.managed_prefix)
        ]
        if foreign and fail_on_foreign:
            raise RuntimeError(f"Foreign pending orders detected: {foreign}")
        if cancel_managed:
            await self.cancel_all_managed_orders(reason="startup_cleanup")

    async def _reconcile_side(self, side: str, intent, *, risk_status: RiskStatus | None = None) -> None:
        live_orders = self.state.bot_orders(side)
        primary = live_orders[0] if live_orders else None
        for extra in live_orders[1:]:
            await self._cancel_order(extra, reason="duplicate_side_order")

        if intent is None:
            if primary:
                if self._should_keep_order_without_intent(risk_status):
                    return
                await self._cancel_order(primary, reason="side_disabled")
            return

        base_size = self._resolved_base_size_for_intent(
            side=side,
            intent=intent,
            instrument=self.state.instrument,
            existing_order=primary,
        )
        if base_size < self.state.instrument.min_size:
            self.journal.append(
                "skip_order",
                {
                    "side": side,
                    "reason": "size_below_min",
                    "reason_zh": translate_reason("size_below_min"),
                    "base_size": base_size,
                },
            )
            return

        if primary:
            age_ms = now_ms() - primary.created_at_ms
            same_price = primary.price == intent.price
            same_size = primary.remaining_size == base_size
            ttl_expired = age_ms > int(self.config.trading.order_ttl_seconds * 1000)
            if same_price and same_size:
                if not ttl_expired:
                    return
                if not self.config.trading.cancel_on_ttl_expiry:
                    return
            await self._cancel_order(primary, reason="reprice_or_ttl")
            return

        if not self._cooldown_ok(side):
            return

        if self.config.mode == "shadow":
            cl_ord_id = build_cl_ord_id(self.config.managed_prefix, side)
            payload = {
                "instId": self.config.trading.inst_id,
                "side": side,
                "ordId": "",
                "clOrdId": cl_ord_id,
                "px": decimal_to_str(intent.price),
                "sz": decimal_to_str(base_size),
                "accFillSz": "0",
                "state": "live",
                "cTime": str(now_ms()),
                "uTime": str(now_ms()),
            }
            order = self.state.apply_order_update(payload, source="shadow_place")
            if self.shadow_simulator:
                self.shadow_simulator.on_order_placed(order)
            self.state.record_place_result(True)
            self.journal.append(
                "shadow_quote",
                {
                    "cl_ord_id": cl_ord_id,
                    "side": side,
                    "price": intent.price,
                    "base_size": base_size,
                    "quote_notional": base_size * intent.price,
                    "reason": intent.reason,
                },
            )
            self._last_action_by_side[side] = now_ms()
            return

        cl_ord_id = build_cl_ord_id(self.config.managed_prefix, side)
        try:
            response = await self.rest.place_limit_order(
                inst_id=self.config.trading.inst_id,
                side=side,
                price=intent.price,
                size=base_size,
                cl_ord_id=cl_ord_id,
                post_only=True,
            )
        except Exception as exc:
            self.state.record_place_result(False)
            payload = {
                "side": side,
                "reason": str(exc),
                "reason_zh": "下单失败",
                "side_zh": "买单" if side == "buy" else "卖单",
            }
            if isinstance(exc, OKXAPIError):
                payload["okx"] = exc.to_dict()
                payload["okx_zh"] = summarize_okx_error(payload["okx"])
            self.journal.append("place_order_error", payload)
            logger.warning("下单失败 | %s | %s", payload["side_zh"], payload.get("okx_zh") or payload["reason"])
            return

        payload = {
            "instId": self.config.trading.inst_id,
            "side": side,
            "ordId": response.get("ordId", ""),
            "clOrdId": cl_ord_id,
            "px": decimal_to_str(intent.price),
            "sz": decimal_to_str(base_size),
            "accFillSz": "0",
            "state": "live",
            "cTime": str(now_ms()),
            "uTime": str(now_ms()),
        }
        self.state.apply_order_update(payload, source="rest_place")
        self.state.record_place_result(True)
        self.journal.append("place_order", payload)
        self._last_action_by_side[side] = now_ms()

    async def _cancel_order(self, order: LiveOrder, *, reason: str) -> None:
        if not self._cooldown_ok(order.side):
            return
        if self.config.mode == "shadow":
            if self.shadow_simulator:
                self.shadow_simulator.on_order_canceled(order, reason=reason)
            self.journal.append(
                "shadow_cancel",
                {
                    "side": order.side,
                    "cl_ord_id": order.cl_ord_id,
                    "reason": reason,
                    "reason_zh": translate_reason(reason),
                },
            )
            self.state.live_orders.pop(order.cl_ord_id, None)
            self.state.record_cancel_result(True)
            self._last_action_by_side[order.side] = now_ms()
            return
        try:
            await self.rest.cancel_order(inst_id=order.inst_id, ord_id=order.ord_id or None, cl_ord_id=order.cl_ord_id or None)
        except Exception as exc:
            if self._is_benign_terminal_cancel_error(exc):
                payload = {
                    "cl_ord_id": order.cl_ord_id,
                    "ord_id": order.ord_id,
                    "reason": reason,
                    "reason_zh": translate_reason(reason),
                    "error": str(exc),
                }
                if isinstance(exc, OKXAPIError):
                    payload["okx"] = exc.to_dict()
                    payload["okx_zh"] = summarize_okx_error(payload["okx"])
                self.state.live_orders.pop(order.cl_ord_id, None)
                self.state.record_cancel_result(True)
                self.journal.append("cancel_order_terminal", payload)
                logger.info("撤单已无须执行 | %s | %s", translate_reason(reason), payload.get("okx_zh") or payload["error"])
                self._last_action_by_side[order.side] = now_ms()
                return
            self.state.record_cancel_result(False)
            payload = {
                "cl_ord_id": order.cl_ord_id,
                "ord_id": order.ord_id,
                "reason": reason,
                "reason_zh": translate_reason(reason),
                "error": str(exc),
            }
            if isinstance(exc, OKXAPIError):
                payload["okx"] = exc.to_dict()
                payload["okx_zh"] = summarize_okx_error(payload["okx"])
            self.journal.append(
                "cancel_order_error",
                payload,
            )
            logger.warning("撤单失败 | %s | %s", translate_reason(reason), payload.get("okx_zh") or payload["error"])
            return
        self.state.live_orders.pop(order.cl_ord_id, None)
        self.state.record_cancel_result(True)
        self.journal.append(
            "cancel_order",
            {
                "cl_ord_id": order.cl_ord_id,
                "ord_id": order.ord_id,
                "reason": reason,
                "reason_zh": translate_reason(reason),
            },
        )
        self._last_action_by_side[order.side] = now_ms()

    def _cooldown_ok(self, side: str) -> bool:
        last = self._last_action_by_side.get(side, 0)
        return (now_ms() - last) >= int(self.config.trading.action_cooldown_seconds * 1000)

    def _should_keep_order_without_intent(self, risk_status: RiskStatus | None) -> bool:
        if risk_status is None:
            return False
        if risk_status.reason.startswith("stale book:") and not self.config.risk.cancel_orders_on_stale_book:
            return True
        return False

    @staticmethod
    def _is_benign_terminal_cancel_error(exc: Exception) -> bool:
        if not isinstance(exc, OKXAPIError):
            return False
        if not exc.data:
            return False
        terminal_codes = {"51400"}
        found_terminal = False
        for item in exc.data:
            s_code = str(item.get("sCode") or "")
            if s_code in terminal_codes:
                found_terminal = True
                continue
            return False
        return found_terminal

    def _resolved_base_size_for_intent(self, *, side: str, intent, instrument: InstrumentMeta, existing_order: LiveOrder | None = None) -> Decimal:
        if intent.base_size is not None:
            desired = quantize_down(intent.base_size, instrument.lot_size)
        else:
            desired = self._base_size_for_intent(intent.price, intent.quote_notional, instrument)
        max_placeable = self._max_placeable_base_size(
            side=side,
            price=intent.price,
            instrument=instrument,
            existing_order=existing_order,
        )
        return min(desired, max_placeable)

    def _max_placeable_base_size(
        self,
        *,
        side: str,
        price: Decimal,
        instrument: InstrumentMeta,
        existing_order: LiveOrder | None = None,
    ) -> Decimal:
        if not self.state.instrument:
            return Decimal("0")
        if side == "buy":
            reusable_quote = Decimal("0")
            if existing_order and existing_order.side == "buy":
                reusable_quote = existing_order.remaining_size * existing_order.price
            free_quote = (
                self.state.free_balance(self.state.instrument.quote_ccy)
                + reusable_quote
                - self.config.risk.min_free_quote_buffer
            )
            if free_quote <= 0:
                return Decimal("0")
            return quantize_down(free_quote / price, instrument.lot_size)
        if side == "sell":
            reusable_base = Decimal("0")
            if existing_order and existing_order.side == "sell":
                reusable_base = existing_order.remaining_size
            free_base = (
                self.state.free_balance(self.state.instrument.base_ccy)
                + reusable_base
                - self.config.risk.min_free_base_buffer
            )
            if free_base <= 0:
                return Decimal("0")
            return quantize_down(free_base, instrument.lot_size)
        return Decimal("0")

    @staticmethod
    def _base_size_for_intent(price: Decimal, quote_notional: Decimal, instrument: InstrumentMeta) -> Decimal:
        raw = quote_notional / price
        return quantize_down(raw, instrument.lot_size)
