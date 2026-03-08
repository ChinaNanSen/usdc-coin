from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

from .audit_store import SQLiteAuditStore
from .config import BotConfig
from .consistency import StateConsistencyChecker
from .executor import JournalWriter, OrderExecutor
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
        self.rest = OKXRestClient(config.exchange)
        self.risk = RiskManager(config.risk, config.trading, mode=config.mode)
        self.strategy = MicroMakerStrategy(config.strategy, config.trading)
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
        )
        self.public_stream: PublicBookStream | None = None
        self.private_stream: PrivateUserStream | None = None
        self._last_balance_poll_ms = 0
        self._last_snapshot_ms = 0
        self._last_resync_attempt_ms = 0

    async def run(self) -> None:
        logger.info("Trend Bot 6 starting in [%s] mode", self.config.mode)
        await self._bootstrap()
        try:
            while self.state.runtime_state != "STOPPED":
                try:
                    await self._tick()
                except Exception as exc:
                    logger.exception("Tick failed: %s", exc)
                    self.journal.append("tick_error", {"error": str(exc)})
                    self.state.request_resync(f"tick failure: {exc}")
                    self.state.set_pause(
                        reason=f"tick failure: {exc}",
                        duration_ms=int(self.config.risk.pause_after_reconnect_seconds * 1000),
                    )
                await asyncio.sleep(self.config.trading.loop_interval_seconds)
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        self.state.set_runtime_state("STOPPED", "shutdown")
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

    async def _bootstrap(self) -> None:
        self.state.set_runtime_state("INIT", "bootstrap")
        self.state.set_stream_status("public_books5", False)
        self.state.set_stream_status("private_user", self.config.mode != "live")

        await self.rest.sync_time_offset()
        await self._refresh_instrument(force=True)

        book = await self.rest.fetch_order_book(self.config.trading.inst_id, self.config.trading.bootstrap_depth)
        self.state.set_book(book)
        self.journal.append("bootstrap_instrument", {"instrument": self.state.instrument})
        self.journal.append("bootstrap_book", {"book": book})

        if self.config.mode == "live":
            balances = await self.rest.fetch_balances([self.config.trading.base_ccy, self.config.trading.quote_ccy])
            self.state.set_balances(balances)
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

        self.public_stream = PublicBookStream(
            url=self.config.exchange.public_ws_url,
            inst_id=self.config.trading.inst_id,
            on_book=self._on_book,
            on_trade=self._on_trade if self.shadow_simulator and self.config.shadow.subscribe_trades else None,
            on_reconnect=self._on_reconnect,
            on_status=self._on_stream_status,
            on_error=self._on_stream_error,
            subscribe_trades=bool(self.shadow_simulator and self.config.shadow.subscribe_trades),
        )
        await self.public_stream.start()

        if self.config.mode == "live":
            self.private_stream = PrivateUserStream(
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
            await self.private_stream.start()

    async def _tick(self) -> None:
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
        if loop_ms - self._last_snapshot_ms >= int(self.config.telemetry.snapshot_interval_seconds * 1000):
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
        zero_fee_override = self.config.trading.inst_id in self.config.risk.zero_fee_instruments
        effective_maker = Decimal("0") if zero_fee_override else fee_data["maker"]
        effective_taker = Decimal("0") if zero_fee_override else fee_data["taker"]
        snapshot = FeeSnapshot(
            inst_type=self.config.trading.inst_type,
            inst_id=self.config.trading.inst_id,
            maker=fee_data["maker"],
            taker=fee_data["taker"],
            effective_maker=effective_maker,
            effective_taker=effective_taker,
            checked_at_ms=loop_ms,
            fee_type=fee_data.get("feeType", ""),
            zero_fee_override=zero_fee_override,
        )
        self.state.set_fee_snapshot(snapshot)
        self.journal.append("fee_snapshot", {"snapshot": snapshot})

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
            return True

        if self.config.mode == "live" and report.cancel_managed and self.config.risk.cancel_managed_on_consistency_failure:
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

    async def _on_book(self, book) -> None:
        self.state.set_book(book)
        if self.shadow_simulator:
            await self.shadow_simulator.on_book(book)

    async def _on_trade(self, trade) -> None:
        if self.shadow_simulator:
            await self.shadow_simulator.on_trade(trade)

    async def _on_order(self, payload: dict) -> None:
        normalized = dict(payload)
        for key in ("cTime", "uTime", "fillTime"):
            value = normalized.get(key)
            if value not in (None, "", "0"):
                normalized[key] = str(self._exchange_ms_to_local_ms(int(value)))
        order = self.state.apply_order_update(normalized, source="ws_order")
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
        if self.config.mode == "live" and stream_name == "public_books5" and self.config.risk.cancel_managed_orders_on_public_reconnect:
            await self.executor.cancel_all_managed_orders(reason="public_reconnect")
