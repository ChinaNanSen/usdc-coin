from __future__ import annotations

import asyncio
import contextlib
import logging
import traceback
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .audit_store import SQLiteAuditStore
from .binance_market_data import BinancePublicMarketStream
from .binance_private_stream import BinancePrivateUserStream
from .binance_rest import BinanceRestClient
from .config import BotConfig
from .consistency import StateConsistencyChecker
from .executor import JournalWriter, OrderExecutor
from .market_gate import evaluate_market_gate
from .market_data import PublicBookStream
from .models import FeeSnapshot
from .okx_rest import OKXRestClient
from .private_stream import PrivateUserStream
from .risk import RiskManager
from .shadow import ShadowFillSimulator
from .state import BotState
from .status_panel import TerminalStatusPanel
from .strategy import MicroMakerStrategy
from .utils import now_ms

logger = logging.getLogger(__name__)


class TrendBot6:
    def __init__(self, config: BotConfig):
        self.config = config
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.state = BotState(managed_prefix=config.managed_prefix, state_path=config.telemetry.state_path)
        self.state.configure_balance_budgets(
            base_ccy=config.trading.base_ccy,
            quote_ccy=config.trading.quote_ccy,
            base_total=config.trading.budget_base_total,
            quote_total=config.trading.budget_quote_total,
        )
        restored_state = self.state.load_persisted_accounting()
        self.audit_store = SQLiteAuditStore(
            config.telemetry.sqlite_path,
            enabled=config.telemetry.sqlite_enabled,
        )
        self.audit_store.open()
        self.journal = JournalWriter(
            config.telemetry.journal_path,
            sqlite_store=self.audit_store,
            runtime_state_getter=lambda: self.state.runtime_state,
            run_id=self.run_id,
        )
        if restored_state:
            self.journal.append("state_restored", restored_state)
        self.rest = self._build_rest_client(config)
        self.risk = RiskManager(config.risk, config.trading, mode=config.mode)
        self.strategy = MicroMakerStrategy(
            config.strategy,
            config.trading,
            max_orders_per_side=config.risk.max_managed_orders_per_side,
        )
        self.shadow_simulator = (
            ShadowFillSimulator(state=self.state, trading=config.trading, config=config.shadow, journal=self.journal)
            if config.mode == "shadow"
            else None
        )
        self.executor = OrderExecutor(
            rest=self.rest,
            state=self.state,
            config=config,
            journal=self.journal,
            shadow_simulator=self.shadow_simulator,
        )
        self.consistency_checker = StateConsistencyChecker(
            risk=config.risk,
            trading=config.trading,
            managed_prefix=config.managed_prefix,
        )
        self.status_panel = TerminalStatusPanel(
            config=config.telemetry,
            mode=config.mode,
            simulated=config.exchange.simulated,
            live_allowed_instruments=tuple(config.risk.live_allowed_instruments),
            observe_only_instruments=tuple(config.risk.observe_only_instruments),
        )
        self.public_stream: PublicBookStream | None = None
        self.private_stream: PrivateUserStream | None = None
        self._last_balance_poll_ms = 0
        self._last_snapshot_ms = 0
        self._last_resync_attempt_ms = 0
        self._quote_cycle_lock = asyncio.Lock()
        self._book_requote_event = asyncio.Event()
        self._book_requote_task: asyncio.Task | None = None
        self._last_book_requote_signal_ms = 0
        self._last_book_requote_reason = "book_top_price_changed"
        self.stop_request_path = Path(config.telemetry.stop_request_path)
        self._clear_stale_stop_request()

    async def run(self) -> None:
        logger.info("Trend Bot 6 starting in [%s] mode", self.config.mode)
        await self._bootstrap()
        try:
            while self.state.runtime_state != "STOPPED":
                try:
                    if self._check_stop_request():
                        continue
                    await self._tick()
                except Exception as exc:
                    logger.exception("Tick failed: %s", exc)
                    error_message = self._exception_message(exc)
                    self.journal.append(
                        "tick_error",
                        {
                            "error": str(exc),
                            "error_repr": repr(exc),
                            "error_type": type(exc).__name__,
                            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                        },
                    )
                    self.state.request_resync(f"tick failure: {error_message}")
                    self.state.set_pause(
                        reason=f"tick failure: {error_message}",
                        duration_ms=int(self.config.risk.pause_after_reconnect_seconds * 1000),
                    )
                await asyncio.sleep(self.config.trading.loop_interval_seconds)
        finally:
            await self._stop_book_requote_worker()
            await self.shutdown()

    async def shutdown(self) -> None:
        await self._stop_book_requote_worker()
        shutdown_reason = (
            self.state.runtime_reason
            if self.state.runtime_state == "STOPPED" and self.state.runtime_reason and self.state.runtime_reason != "booting"
            else "shutdown"
        )
        self.state.set_runtime_state("STOPPED", shutdown_reason)
        logger.info("Shutting down Trend Bot 6")
        if self.config.mode == "live" and self.config.risk.cancel_managed_orders_on_shutdown:
            try:
                await self.executor.cancel_all_managed_orders(reason="shutdown")
            except Exception as exc:
                logger.warning("Failed to cancel on shutdown: %s", exc)
        if self.private_stream:
            await self.private_stream.stop()
        if self.public_stream:
            await self.public_stream.stop()
        self.state.persist()
        self.audit_store.close()
        await self.rest.close()
        self._clear_stop_request_file()

    async def _bootstrap(self) -> None:
        self.state.set_runtime_state("INIT", "bootstrap")
        self.state.set_stream_status("public_books5", False)
        self.state.set_stream_status("private_user", self.config.mode != "live")

        await self.rest.sync_time_offset()
        await self._refresh_instrument(force=True)
        if not self._check_live_market_gate():
            return

        book = await self.rest.fetch_order_book(self.config.trading.inst_id, self.config.trading.bootstrap_depth)
        self.state.set_book(book)
        self.journal.append("bootstrap_instrument", {"instrument": self.state.instrument})
        self.journal.append("bootstrap_book", {"book": book})

        if self.config.mode == "live":
            balances = await self.rest.fetch_balances([self.config.trading.base_ccy, self.config.trading.quote_ccy])
            self.state.set_balances(balances)
            if not self._check_live_budget_gate():
                return
            await self._refresh_fee(force=True)
            await self.executor.bootstrap_pending_orders()
            if not await self._run_consistency_check(context="bootstrap", stop_on_failure=True):
                return
        else:
            self.state.seed_shadow_balances(
                base_ccy=self.config.trading.base_ccy,
                quote_ccy=self.config.trading.quote_ccy,
                base_balance=self.config.trading.shadow_base_balance,
                quote_balance=self.config.trading.shadow_quote_balance,
            )
            self.state.set_runtime_state("READY", "shadow bootstrap complete")

        self.public_stream = self._build_public_stream()
        await self.public_stream.start()

        if self.config.mode == "live":
            self.private_stream = self._build_private_stream()
            trade_client_name = "private_ws"
            if self._prefer_rest_trade_routing():
                trade_client_name = "rest"
            if self.config.exchange.simulated:
                self.journal.append(
                    "simulated_trade_routing",
                    {
                        "trade_client": trade_client_name,
                        "reason": (
                            "configured simulated instrument uses rest trading fallback"
                            if trade_client_name == "rest"
                            else "simulated instrument allows private ws trading"
                        ),
                        "inst_id": self.config.trading.inst_id,
                    },
                )
            if trade_client_name == "private_ws":
                self.executor.attach_trade_client(self.private_stream)
            await self.private_stream.start()

    @staticmethod
    def _build_rest_client(config: BotConfig):
        if config.exchange.name == "binance":
            return BinanceRestClient(config.exchange)
        return OKXRestClient(config.exchange)

    def _build_public_stream(self):
        if self.config.exchange.name == "binance":
            return BinancePublicMarketStream(
                url=self.config.exchange.public_ws_url,
                inst_id=self.config.trading.inst_id,
                on_book=self._on_book,
                on_trade=self._on_trade,
                on_reconnect=self._on_reconnect,
                on_status=self._on_stream_status,
                on_error=self._on_stream_error,
                on_activity=self._on_stream_activity,
                subscribe_trades=True,
            )
        return PublicBookStream(
            url=self.config.exchange.public_ws_url,
            inst_id=self.config.trading.inst_id,
            on_book=self._on_book,
            on_trade=self._on_trade,
            on_reconnect=self._on_reconnect,
            on_status=self._on_stream_status,
            on_error=self._on_stream_error,
            on_activity=self._on_stream_activity,
            subscribe_trades=True,
        )

    def _build_private_stream(self):
        if self.config.exchange.name == "binance":
            return BinancePrivateUserStream(
                url=self.config.exchange.private_ws_url,
                rest=self.rest,
                inst_id=self.config.trading.inst_id,
                on_order=self._on_order,
                on_account=self._on_account,
                on_reconnect=self._on_reconnect,
                on_status=self._on_stream_status,
                on_error=self._on_stream_error,
            )
        return PrivateUserStream(
            url=self.config.exchange.private_ws_url,
            signer=self.rest.signer,
            time_offset_ms=self.rest.time_offset_ms,
            inst_type=self.config.trading.inst_type,
            on_order=self._on_order,
            on_account=self._on_account,
            on_reconnect=self._on_reconnect,
            on_status=self._on_stream_status,
            on_error=self._on_stream_error,
        )

    async def _tick(self) -> None:
        await self._run_quote_cycle(trigger="loop", include_maintenance=True)

    async def _run_quote_cycle(self, *, trigger: str, include_maintenance: bool) -> None:
        async with self._quote_cycle_lock:
            if include_maintenance:
                await self._refresh_balances_if_due()
                await self._refresh_instrument(force=False)
                await self._refresh_fee(force=False)
                await self._maybe_resync()
            self.state.clear_pause_if_elapsed()

            risk_status = self.risk.evaluate(self.state)
            decision = self.strategy.decide(self.state, risk_status)
            self._update_runtime_state(risk_status, decision)
            self.journal.append(
                "decision",
                {
                    "runtime_state": self.state.runtime_state,
                    "trigger": trigger,
                    "risk": risk_status,
                    "decision": decision,
                    "balances": self.state.balances,
                    "live_orders": self.state.live_orders,
                    "fee_snapshot": self.state.fee_snapshot,
                },
            )
            await self.executor.reconcile(decision, risk_status=risk_status)
            self.status_panel.maybe_render(state=self.state, risk_status=risk_status, decision=decision)

            loop_ms = now_ms()
            if include_maintenance and loop_ms - self._last_snapshot_ms >= int(self.config.telemetry.snapshot_interval_seconds * 1000):
                self.state.persist()
                self._last_snapshot_ms = loop_ms

    async def _refresh_balances_if_due(self) -> None:
        if self.config.mode != "live":
            return
        loop_ms = now_ms()
        if loop_ms - self._last_balance_poll_ms < int(self.config.trading.balance_poll_interval_seconds * 1000):
            return
        balances = await self.rest.fetch_balances([self.config.trading.base_ccy, self.config.trading.quote_ccy])
        self.state.set_balances(balances)
        self._last_balance_poll_ms = loop_ms

    async def _refresh_instrument(self, *, force: bool) -> None:
        loop_ms = now_ms()
        if not force and loop_ms - self.state.last_instrument_check_ms < int(self.config.risk.instrument_poll_interval_seconds * 1000):
            return
        instrument = await self.rest.fetch_instrument(self.config.trading.inst_id, self.config.trading.inst_type)
        self.state.set_instrument(instrument)

    async def _refresh_fee(self, *, force: bool) -> None:
        if self.config.mode != "live":
            return
        loop_ms = now_ms()
        if not force and loop_ms - self.state.last_fee_check_ms < int(self.config.risk.fee_poll_interval_seconds * 1000):
            return
        fee_data = await self.rest.fetch_trade_fee(self.config.trading.inst_type, self.config.trading.inst_id)
        snapshot = FeeSnapshot(
            inst_type=self.config.trading.inst_type,
            inst_id=self.config.trading.inst_id,
            maker=fee_data["maker"],
            taker=fee_data["taker"],
            effective_maker=fee_data["maker"],
            effective_taker=fee_data["taker"],
            checked_at_ms=loop_ms,
            fee_type=fee_data.get("feeType", ""),
            zero_fee_override=False,
        )
        self.state.set_fee_snapshot(snapshot)
        self.journal.append("fee_snapshot", {"snapshot": snapshot})

    def _check_live_market_gate(self) -> bool:
        if self.config.mode != "live":
            return True
        market_gate = evaluate_market_gate(
            inst_id=self.config.trading.inst_id,
            live_allowed_instruments=self.config.risk.live_allowed_instruments,
            observe_only_instruments=self.config.risk.observe_only_instruments,
        )
        if market_gate.live_allowed:
            return True

        logger.warning("Startup market gate blocked live run for %s: %s", market_gate.inst_id, market_gate.reason)
        self.journal.append(
            "startup_market_gate_blocked",
            {
                "inst_id": market_gate.inst_id,
                "reason": market_gate.reason,
                "live_allowed_instruments": list(market_gate.live_allowed_instruments),
                "observe_only_instruments": list(market_gate.observe_only_instruments),
            },
        )
        self.state.set_runtime_state("STOPPED", market_gate.reason)
        return False

    def _check_live_budget_gate(self) -> bool:
        if self.config.mode != "live":
            return True
        errors = self.state.validate_configured_budgets(
            ccys=(self.config.trading.base_ccy, self.config.trading.quote_ccy),
        )
        if not errors:
            return True

        reason = f"instance budget exceeds account balance: {'; '.join(errors)}"
        logger.warning("Startup budget gate blocked live run for %s: %s", self.config.trading.inst_id, reason)
        self.journal.append(
            "startup_budget_gate_blocked",
            {
                "inst_id": self.config.trading.inst_id,
                "reason": reason,
                "budget_base_total": self.config.trading.budget_base_total,
                "budget_quote_total": self.config.trading.budget_quote_total,
                "exchange_base_total": self.state.exchange_total_balance(self.config.trading.base_ccy),
                "exchange_quote_total": self.state.exchange_total_balance(self.config.trading.quote_ccy),
            },
        )
        self.state.set_runtime_state("STOPPED", reason)
        return False

    def _prefer_rest_trade_routing(self) -> bool:
        if self.config.exchange.name == "binance":
            return True
        return self.config.exchange.simulated and self.config.trading.inst_id in self.config.risk.simulated_rest_trade_instruments

    def _check_stop_request(self) -> bool:
        if not self.stop_request_path.exists():
            return False
        self.journal.append(
            "stop_requested",
            {
                "inst_id": self.config.trading.inst_id,
                "path": str(self.stop_request_path),
            },
        )
        self.state.set_runtime_state("STOPPED", f"stop requested: {self.stop_request_path.name}")
        return True

    def _clear_stale_stop_request(self) -> None:
        if not self.stop_request_path.exists():
            return
        try:
            self.stop_request_path.unlink()
        except OSError:
            logger.warning("Failed to clear stale stop request file: %s", self.stop_request_path)

    def _clear_stop_request_file(self) -> None:
        if not self.stop_request_path.exists():
            return
        try:
            self.stop_request_path.unlink()
        except OSError:
            logger.warning("Failed to remove stop request file during shutdown: %s", self.stop_request_path)

    async def _maybe_resync(self) -> None:
        if self.config.mode != "live" or not self.state.resync_required:
            return
        loop_ms = now_ms()
        if loop_ms - self._last_resync_attempt_ms < 1000:
            return
        self._last_resync_attempt_ms = loop_ms
        try:
            balances = await self.rest.fetch_balances([self.config.trading.base_ccy, self.config.trading.quote_ccy])
            self.state.set_balances(balances)
            await self.executor.reload_pending_orders()
            book = await self.rest.fetch_order_book(self.config.trading.inst_id, self.config.trading.bootstrap_depth)
            self.state.set_book(book)
            if not await self._run_consistency_check(context="resync", stop_on_failure=False):
                return
            self.state.clear_resync()
            if self.state.runtime_state == "PAUSED":
                self.state.set_runtime_state("READY", "resync complete")
            self.journal.append("resync_complete", {"reason": "state reloaded"})
        except Exception as exc:
            self.state.set_pause(
                reason=f"resync retry after failure: {exc}",
                duration_ms=int(self.config.risk.pause_after_reconnect_seconds * 1000),
            )
            self.journal.append("resync_error", {"error": str(exc)})

    def _update_runtime_state(self, risk_status, decision) -> None:
        target_state = risk_status.runtime_state
        target_reason = risk_status.reason
        if risk_status.ok and target_state == "READY":
            target_state = "QUOTING" if (decision.bid or decision.ask) else "READY"
            target_reason = decision.reason
        elif risk_status.ok and target_state == "REDUCE_ONLY":
            target_reason = decision.reason
        self.state.set_runtime_state(target_state, target_reason)

    async def _run_consistency_check(self, *, context: str, stop_on_failure: bool) -> bool:
        report = self.consistency_checker.check(self.state)
        self.state.record_consistency_result(report.ok, report.reason)
        self.journal.append("consistency_check", {"context": context, "report": report})
        if report.ok:
            if context == "resync":
                self.state.clear_resync_passive_violations()
            return True

        offending_order_ids = report.offending_managed_orders
        if context == "resync" and offending_order_ids:
            offending_order_ids = self.state.note_resync_passive_violations(report.offending_managed_orders)
            if not offending_order_ids:
                self.state.request_resync(f"{context} consistency failed: {report.reason}")
                self.state.set_pause(
                    reason=f"{context} passive price check deferred: {report.reason}",
                    duration_ms=int(self.config.risk.pause_after_reconnect_seconds * 1000),
                )
                self.journal.append(
                    "consistency_check_deferred",
                    {
                        "context": context,
                        "reason": report.reason,
                        "offending_managed_orders": report.offending_managed_orders,
                    },
                )
                return False

        if self.config.mode == "live" and report.cancel_managed and self.config.risk.cancel_managed_on_consistency_failure:
            if offending_order_ids:
                await self.executor.cancel_managed_orders(
                    cl_ord_ids=offending_order_ids,
                    reason=f"consistency_failure:{context}",
                )
            else:
                await self.executor.cancel_all_managed_orders(reason=f"consistency_failure:{context}")

        if stop_on_failure or self.state.consecutive_consistency_failures >= self.config.risk.max_consistency_failures:
            self.state.set_runtime_state("STOPPED", f"consistency failure: {report.reason}")
            return False

        self.state.request_resync(f"{context} consistency failed: {report.reason}")
        self.state.set_pause(
            reason=f"{context} consistency failed: {report.reason}",
            duration_ms=int(self.config.risk.pause_after_reconnect_seconds * 1000),
        )
        return False

    @staticmethod
    def _exception_message(exc: Exception) -> str:
        text = str(exc).strip()
        if text:
            return f"{type(exc).__name__}: {text}"
        return repr(exc)

    async def _on_book(self, book) -> None:
        previous_book = self.state.book
        self.state.set_book(book)
        self.state.evaluate_fill_markouts()
        toxic_events = self.state.evaluate_toxic_flow(
            min_observation_ms=max(int(self.config.strategy.toxic_flow_min_observation_ms), 0),
            max_observation_ms=max(int(self.config.strategy.toxic_flow_max_observation_ms), 0),
            adverse_ticks=max(int(self.config.strategy.toxic_flow_adverse_ticks), 0),
            cooldown_ms=int(max(self.config.strategy.toxic_flow_cooldown_seconds, 0) * 1000),
        )
        for event in toxic_events:
            self.journal.append("toxic_flow_cooldown", event)
        if self.shadow_simulator:
            await self.shadow_simulator.on_book(book)
        reason = self._book_requote_reason(previous_book, book)
        if reason:
            self._signal_book_requote(reason)

    async def _on_trade(self, trade) -> None:
        self.state.set_last_market_trade(trade)
        if self.shadow_simulator:
            await self.shadow_simulator.on_trade(trade)

    async def _on_order(self, payload: dict) -> None:
        normalized = dict(payload)
        inst_id = str(normalized.get("instId") or "")
        if inst_id and inst_id != self.config.trading.inst_id:
            self.journal.append(
                "order_update_ignored_foreign_inst",
                {
                    "inst_id": inst_id,
                    "expected_inst_id": self.config.trading.inst_id,
                    "cl_ord_id": normalized.get("clOrdId") or normalized.get("ordId") or "",
                },
            )
            return
        for key in ("cTime", "uTime", "fillTime"):
            value = normalized.get(key)
            if value not in (None, "", "0"):
                normalized[key] = str(self._exchange_ms_to_local_ms(int(value)))
        order = self.state.apply_order_update(normalized, source="ws_order")
        amend_resolution = self.state.resolve_pending_amend_update(payload=normalized, order=order)
        if amend_resolution is not None:
            event, event_payload = amend_resolution
            self.journal.append(event, event_payload)
        self.journal.append("order_update", {"order": order, "raw": payload})

    async def _on_account(self, payload: dict) -> None:
        self.state.apply_account_update(payload)
        self.journal.append("account_update", payload)

    async def _on_stream_status(self, stream_name: str, connected: bool) -> None:
        self.state.set_stream_status(stream_name, connected)
        self.journal.append("stream_status", {"stream": stream_name, "connected": connected})
        if self.state.runtime_state == "STOPPED":
            return
        if self.config.mode == "live" and not connected:
            self.state.request_resync(f"{stream_name} disconnected")
            self.state.set_pause(
                reason=f"{stream_name} disconnected",
                duration_ms=int(self.config.risk.pause_after_reconnect_seconds * 1000),
            )

    async def _on_stream_error(self, stream_name: str, exc: Exception) -> None:
        self.journal.append(
            "stream_error",
            {
                "stream": stream_name,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )

    async def _on_stream_activity(self, stream_name: str, activity: str) -> None:
        del activity
        self.state.mark_stream_activity(stream_name)

    def _exchange_ms_to_local_ms(self, exchange_ms: int) -> int:
        return int(exchange_ms - self.rest.time_offset_ms)

    async def _on_reconnect(self, stream_name: str) -> None:
        if self.state.runtime_state == "STOPPED":
            return
        logger.warning("Reconnect detected: %s", stream_name)
        self.state.mark_reconnect()
        self.state.request_resync(f"{stream_name} reconnected")
        self.state.set_pause(
            reason=f"{stream_name} reconnected",
            duration_ms=int(self.config.risk.pause_after_reconnect_seconds * 1000),
        )
        self.journal.append("reconnect", {"stream": stream_name})
        if self.config.mode == "live" and stream_name == "public_books5":
            self.journal.append(
                "public_reconnect_resync_only",
                {
                    "stream": stream_name,
                    "immediate_cancel": False,
                    "configured_cancel_on_public_reconnect": self.config.risk.cancel_managed_orders_on_public_reconnect,
                },
            )

    def _book_requote_reason(self, previous_book, current_book) -> str | None:
        if not self.config.trading.event_driven_requote:
            return None
        if previous_book is None:
            return None

        previous_best_bid = previous_book.best_bid.price if previous_book.best_bid else None
        previous_best_ask = previous_book.best_ask.price if previous_book.best_ask else None
        current_best_bid = current_book.best_bid.price if current_book.best_bid else None
        current_best_ask = current_book.best_ask.price if current_book.best_ask else None

        if previous_best_bid == current_best_bid and previous_best_ask == current_best_ask:
            return None
        return "book_top_price_changed"

    def _signal_book_requote(self, reason: str) -> None:
        if self.state.runtime_state == "STOPPED":
            return
        self._last_book_requote_reason = reason
        self._last_book_requote_signal_ms = now_ms()
        self._book_requote_event.set()
        self._ensure_book_requote_worker()

    def _ensure_book_requote_worker(self) -> None:
        if self._book_requote_task and not self._book_requote_task.done():
            return
        self._book_requote_task = asyncio.create_task(self._book_requote_worker())

    async def _stop_book_requote_worker(self) -> None:
        if not self._book_requote_task:
            return
        self._book_requote_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._book_requote_task
        self._book_requote_task = None
        self._book_requote_event.clear()

    async def _book_requote_worker(self) -> None:
        try:
            while self.state.runtime_state != "STOPPED":
                await self._book_requote_event.wait()
                while self.state.runtime_state != "STOPPED":
                    due_ms = self._last_book_requote_signal_ms + self.config.trading.book_requote_debounce_ms
                    delay_ms = due_ms - now_ms()
                    if delay_ms > 0:
                        await asyncio.sleep(delay_ms / 1000)
                        continue

                    observed_signal_ms = self._last_book_requote_signal_ms
                    trigger = self._last_book_requote_reason
                    self._book_requote_event.clear()
                    await self._run_quote_cycle(trigger=trigger, include_maintenance=False)
                    if observed_signal_ms == self._last_book_requote_signal_ms and not self._book_requote_event.is_set():
                        break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Book reprice failed: %s", exc)
            self.journal.append("book_requote_error", {"error": str(exc)})
            self.state.request_resync(f"book reprice failure: {exc}")
            self.state.set_pause(
                reason=f"book reprice failure: {exc}",
                duration_ms=int(self.config.risk.pause_after_reconnect_seconds * 1000),
            )
