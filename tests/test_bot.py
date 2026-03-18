import asyncio
from decimal import Decimal
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bot import TrendBot6
from src.config import BotConfig
from src.models import Balance, InstrumentMeta
from src.models import BookLevel, BookSnapshot
from src.utils import build_cl_ord_id


class StubJournal:
    def __init__(self):
        self.events = []

    def append(self, event: str, payload: dict) -> None:
        self.events.append((event, payload))


def make_book(*, bid: str, ask: str, ts_ms: int) -> BookSnapshot:
    return BookSnapshot(
        ts_ms=ts_ms,
        received_ms=ts_ms,
        bids=[BookLevel(price=Decimal(bid), size=Decimal("100000"))],
        asks=[BookLevel(price=Decimal(ask), size=Decimal("100000"))],
    )


def test_public_reconnect_resyncs_without_immediate_cancel(tmp_path):
    config = BotConfig(mode="live")
    config.telemetry.sqlite_enabled = False
    config.telemetry.journal_path = str(tmp_path / "journal.jsonl")
    config.telemetry.sqlite_path = str(tmp_path / "audit.db")
    config.telemetry.state_path = str(tmp_path / "state.json")

    bot = TrendBot6(config)
    bot.journal = StubJournal()
    cancel_calls: list[str] = []

    async def fake_cancel_all_managed_orders(*, reason: str) -> None:
        cancel_calls.append(reason)

    bot.executor.cancel_all_managed_orders = fake_cancel_all_managed_orders  # type: ignore[method-assign]

    async def run() -> None:
        await bot._on_reconnect("public_books5")
        await bot.rest.close()

    try:
        asyncio.run(run())
    finally:
        bot.audit_store.close()

    assert cancel_calls == []
    assert bot.state.resync_required is True
    assert bot.state.resync_reason == "public_books5 reconnected"
    assert bot.state.pause_until_ms > 0
    assert ("reconnect", {"stream": "public_books5"}) in bot.journal.events
    assert (
        "public_reconnect_resync_only",
        {
            "stream": "public_books5",
            "immediate_cancel": False,
            "configured_cancel_on_public_reconnect": False,
        },
    ) in bot.journal.events


def test_bot_restores_persisted_accounting_on_init(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "initial_nav_quote": "25016.5929021004943",
                "live_realized_pnl_quote": "2.2",
                "observed_fill_count": 4,
                "live_position_lots": [
                    {"qty": "-1693.170218", "price": "1.0001", "ts_ms": 1234, "cl_ord_id": "bot6ms1"}
                ],
                "initial_external_base_inventory": "23008.69913",
                "external_base_inventory_remaining": "21021.301162",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = BotConfig(mode="live")
    config.telemetry.sqlite_enabled = False
    config.telemetry.journal_path = str(tmp_path / "journal.jsonl")
    config.telemetry.sqlite_path = str(tmp_path / "audit.db")
    config.telemetry.state_path = str(state_path)

    bot = TrendBot6(config)
    try:
        assert bot.state.initial_nav_quote == Decimal("25016.5929021004943")
        assert bot.state.live_realized_pnl_quote == Decimal("2.2")
        assert bot.state.observed_fill_count == 4
        assert bot.state.strategy_position_base() == Decimal("-1693.170218")
        journal_text = Path(config.telemetry.journal_path).read_text(encoding="utf-8")
        assert '"event": "state_restored"' in journal_text
    finally:
        bot.audit_store.close()


def test_consistency_resync_cancels_only_offending_managed_orders(tmp_path):
    config = BotConfig(mode="live")
    config.risk.cancel_managed_on_consistency_failure = True
    config.telemetry.sqlite_enabled = False
    config.telemetry.journal_path = str(tmp_path / "journal.jsonl")
    config.telemetry.sqlite_path = str(tmp_path / "audit.db")
    config.telemetry.state_path = str(tmp_path / "state.json")

    bot = TrendBot6(config)
    selective_calls: list[tuple[tuple[str, ...], str]] = []
    all_cancel_calls: list[str] = []

    async def fake_cancel_managed_orders(*, cl_ord_ids, reason: str) -> None:
        selective_calls.append((tuple(cl_ord_ids), reason))

    async def fake_cancel_all_managed_orders(*, reason: str) -> None:
        all_cancel_calls.append(reason)

    bot.executor.cancel_managed_orders = fake_cancel_managed_orders  # type: ignore[method-assign]
    bot.executor.cancel_all_managed_orders = fake_cancel_all_managed_orders  # type: ignore[method-assign]

    bot.state.set_instrument(
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
    bot.state.set_book(make_book(bid="0.9999", ask="1.0000", ts_ms=1))
    bot.state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=Decimal("50000"), available=Decimal("50000")),
            "USDT": Balance(ccy="USDT", total=Decimal("50000"), available=Decimal("50000")),
        }
    )

    bad_sell_id = build_cl_ord_id("bot6", "sell")
    good_buy_id = build_cl_ord_id("bot6", "buy")
    bot.state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "1",
            "clOrdId": bad_sell_id,
            "px": "0.9999",
            "sz": "1000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )
    bot.state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "2",
            "clOrdId": good_buy_id,
            "px": "0.9998",
            "sz": "1000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )

    try:
        first_ok = asyncio.run(bot._run_consistency_check(context="resync", stop_on_failure=False))
        second_ok = asyncio.run(bot._run_consistency_check(context="resync", stop_on_failure=False))
    finally:
        bot.audit_store.close()

    assert first_ok is False
    assert second_ok is False
    assert selective_calls == [((bad_sell_id,), "consistency_failure:resync")]
    assert all_cancel_calls == []


def test_consistency_resync_debounce_clears_after_success(tmp_path):
    config = BotConfig(mode="live")
    config.risk.cancel_managed_on_consistency_failure = True
    config.telemetry.sqlite_enabled = False
    config.telemetry.journal_path = str(tmp_path / "journal.jsonl")
    config.telemetry.sqlite_path = str(tmp_path / "audit.db")
    config.telemetry.state_path = str(tmp_path / "state.json")

    bot = TrendBot6(config)
    selective_calls: list[tuple[tuple[str, ...], str]] = []

    async def fake_cancel_managed_orders(*, cl_ord_ids, reason: str) -> None:
        selective_calls.append((tuple(cl_ord_ids), reason))

    bot.executor.cancel_managed_orders = fake_cancel_managed_orders  # type: ignore[method-assign]

    bot.state.set_instrument(
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
    bot.state.set_book(make_book(bid="0.9999", ask="1.0000", ts_ms=1))
    bot.state.set_balances(
        {
            "USDC": Balance(ccy="USDC", total=Decimal("50000"), available=Decimal("50000")),
            "USDT": Balance(ccy="USDT", total=Decimal("50000"), available=Decimal("50000")),
        }
    )

    bad_sell_id = build_cl_ord_id("bot6", "sell")
    bot.state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "sell",
            "ordId": "1",
            "clOrdId": bad_sell_id,
            "px": "0.9999",
            "sz": "1000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )

    try:
        first_ok = asyncio.run(bot._run_consistency_check(context="resync", stop_on_failure=False))
        bot.state.set_book(make_book(bid="0.9998", ask="0.9999", ts_ms=2))
        cleared_ok = asyncio.run(bot._run_consistency_check(context="resync", stop_on_failure=False))
        bot.state.set_book(make_book(bid="0.9999", ask="1.0000", ts_ms=3))
        second_first_ok = asyncio.run(bot._run_consistency_check(context="resync", stop_on_failure=False))
    finally:
        bot.audit_store.close()

    assert first_ok is False
    assert cleared_ok is True
    assert second_first_ok is False
    assert selective_calls == []


def test_run_logs_tick_error_repr_and_traceback(tmp_path):
    config = BotConfig(mode="shadow")
    config.telemetry.sqlite_enabled = False
    config.telemetry.journal_path = str(tmp_path / "journal.jsonl")
    config.telemetry.sqlite_path = str(tmp_path / "audit.db")
    config.telemetry.state_path = str(tmp_path / "state.json")

    bot = TrendBot6(config)
    bot.journal = StubJournal()

    async def fake_bootstrap() -> None:
        bot.state.set_runtime_state("READY", "test bootstrap")

    async def fake_tick() -> None:
        raise Exception()

    async def fake_sleep(_: float) -> None:
        bot.state.set_runtime_state("STOPPED", "done")

    async def fake_shutdown() -> None:
        return None

    original_sleep = asyncio.sleep
    bot._bootstrap = fake_bootstrap  # type: ignore[method-assign]
    bot._tick = fake_tick  # type: ignore[method-assign]
    bot.shutdown = fake_shutdown  # type: ignore[method-assign]
    asyncio.sleep = fake_sleep  # type: ignore[assignment]

    try:
        asyncio.run(bot.run())
    finally:
        asyncio.sleep = original_sleep  # type: ignore[assignment]
        bot.audit_store.close()

    tick_errors = [payload for event, payload in bot.journal.events if event == "tick_error"]
    assert len(tick_errors) == 1
    assert tick_errors[0]["error"] == ""
    assert tick_errors[0]["error_repr"] == "Exception()"
    assert tick_errors[0]["error_type"] == "Exception"
    assert "fake_tick" in tick_errors[0]["traceback"]
    assert bot.state.resync_reason == "tick failure: Exception()"


def test_on_book_triggers_debounced_quote_cycle_when_top_price_changes(tmp_path):
    config = BotConfig(mode="shadow")
    config.telemetry.sqlite_enabled = False
    config.telemetry.journal_path = str(tmp_path / "journal.jsonl")
    config.telemetry.sqlite_path = str(tmp_path / "audit.db")
    config.telemetry.state_path = str(tmp_path / "state.json")
    config.trading.book_requote_debounce_ms = 20

    bot = TrendBot6(config)
    calls: list[tuple[str, bool]] = []
    bot.state.set_book(make_book(bid="1.0000", ask="1.0001", ts_ms=1))

    async def fake_run_quote_cycle(*, trigger: str, include_maintenance: bool) -> None:
        calls.append((trigger, include_maintenance))

    bot._run_quote_cycle = fake_run_quote_cycle  # type: ignore[method-assign]

    async def run() -> None:
        await bot._on_book(make_book(bid="0.9999", ask="1.0000", ts_ms=2))
        await asyncio.sleep(0.06)
        await bot._stop_book_requote_worker()
        await bot.rest.close()

    try:
        asyncio.run(run())
    finally:
        bot.audit_store.close()

    assert calls == [("book_top_price_changed", False)]


def test_on_book_debounce_coalesces_multiple_price_updates(tmp_path):
    config = BotConfig(mode="shadow")
    config.telemetry.sqlite_enabled = False
    config.telemetry.journal_path = str(tmp_path / "journal.jsonl")
    config.telemetry.sqlite_path = str(tmp_path / "audit.db")
    config.telemetry.state_path = str(tmp_path / "state.json")
    config.trading.book_requote_debounce_ms = 20

    bot = TrendBot6(config)
    calls: list[tuple[str, bool]] = []
    bot.state.set_book(make_book(bid="1.0000", ask="1.0001", ts_ms=1))

    async def fake_run_quote_cycle(*, trigger: str, include_maintenance: bool) -> None:
        calls.append((trigger, include_maintenance))

    bot._run_quote_cycle = fake_run_quote_cycle  # type: ignore[method-assign]

    async def run() -> None:
        await bot._on_book(make_book(bid="0.9999", ask="1.0000", ts_ms=2))
        await bot._on_book(make_book(bid="0.9998", ask="0.9999", ts_ms=3))
        await asyncio.sleep(0.06)
        await bot._stop_book_requote_worker()
        await bot.rest.close()

    try:
        asyncio.run(run())
    finally:
        bot.audit_store.close()

    assert calls == [("book_top_price_changed", False)]


def test_on_book_ignores_same_top_prices(tmp_path):
    config = BotConfig(mode="shadow")
    config.telemetry.sqlite_enabled = False
    config.telemetry.journal_path = str(tmp_path / "journal.jsonl")
    config.telemetry.sqlite_path = str(tmp_path / "audit.db")
    config.telemetry.state_path = str(tmp_path / "state.json")
    config.trading.book_requote_debounce_ms = 20

    bot = TrendBot6(config)
    calls: list[tuple[str, bool]] = []
    bot.state.set_book(make_book(bid="1.0000", ask="1.0001", ts_ms=1))

    async def fake_run_quote_cycle(*, trigger: str, include_maintenance: bool) -> None:
        calls.append((trigger, include_maintenance))

    bot._run_quote_cycle = fake_run_quote_cycle  # type: ignore[method-assign]

    async def run() -> None:
        await bot._on_book(make_book(bid="1.0000", ask="1.0001", ts_ms=2))
        await asyncio.sleep(0.06)
        await bot._stop_book_requote_worker()
        await bot.rest.close()

    try:
        asyncio.run(run())
    finally:
        bot.audit_store.close()

    assert calls == []


def test_bot_logs_ws_amend_failure_and_clears_pending(tmp_path):
    config = BotConfig(mode="live")
    config.telemetry.sqlite_enabled = False
    config.telemetry.journal_path = str(tmp_path / "journal.jsonl")
    config.telemetry.sqlite_path = str(tmp_path / "audit.db")
    config.telemetry.state_path = str(tmp_path / "state.json")

    bot = TrendBot6(config)
    bot.journal = StubJournal()
    bot.state.set_instrument(
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
    bot.state.set_book(make_book(bid="0.9998", ask="0.9999", ts_ms=1))
    buy_id = build_cl_ord_id("bot6", "buy")
    bot.state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "b1",
            "clOrdId": buy_id,
            "px": "0.9998",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )
    bot.state.register_pending_amend(
        cl_ord_id=buy_id,
        ord_id="b1",
        side="buy",
        reason="join_best_bid",
        previous_price=Decimal("0.9998"),
        previous_size=Decimal("10000"),
        previous_remaining_size=Decimal("10000"),
        target_price=Decimal("0.9999"),
        target_size=Decimal("10000"),
        target_remaining_size=Decimal("10000"),
        filled_size=Decimal("0"),
    )

    try:
        asyncio.run(
            bot._on_order(
                {
                    "instId": "USDC-USDT",
                    "side": "buy",
                    "ordId": "b1",
                    "clOrdId": buy_id,
                    "px": "0.9998",
                    "sz": "10000",
                    "accFillSz": "0",
                    "state": "live",
                    "cTime": "1",
                    "uTime": "2",
                    "code": "51511",
                    "msg": "",
                    "amendResult": "-1",
                }
            )
        )
    finally:
        bot.audit_store.close()

    assert bot.state.pending_amend(buy_id) is None
    assert bot.state.live_orders[buy_id].price == Decimal("0.9998")
    assert any(event == "amend_order_error" for event, _ in bot.journal.events)


def test_bot_logs_ws_amend_success_and_clears_pending(tmp_path):
    config = BotConfig(mode="live")
    config.telemetry.sqlite_enabled = False
    config.telemetry.journal_path = str(tmp_path / "journal.jsonl")
    config.telemetry.sqlite_path = str(tmp_path / "audit.db")
    config.telemetry.state_path = str(tmp_path / "state.json")

    bot = TrendBot6(config)
    bot.journal = StubJournal()
    bot.state.set_instrument(
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
    bot.state.set_book(make_book(bid="0.9998", ask="0.9999", ts_ms=1))
    buy_id = build_cl_ord_id("bot6", "buy")
    bot.state.apply_order_update(
        {
            "instId": "USDC-USDT",
            "side": "buy",
            "ordId": "b1",
            "clOrdId": buy_id,
            "px": "0.9998",
            "sz": "10000",
            "accFillSz": "0",
            "state": "live",
            "cTime": "1",
            "uTime": "1",
        },
        source="test",
    )
    bot.state.register_pending_amend(
        cl_ord_id=buy_id,
        ord_id="b1",
        side="buy",
        reason="join_best_bid",
        previous_price=Decimal("0.9998"),
        previous_size=Decimal("10000"),
        previous_remaining_size=Decimal("10000"),
        target_price=Decimal("0.9999"),
        target_size=Decimal("10000"),
        target_remaining_size=Decimal("10000"),
        filled_size=Decimal("0"),
    )

    try:
        asyncio.run(
            bot._on_order(
                {
                    "instId": "USDC-USDT",
                    "side": "buy",
                    "ordId": "b1",
                    "clOrdId": buy_id,
                    "px": "0.9999",
                    "sz": "10000",
                    "accFillSz": "0",
                    "state": "live",
                    "cTime": "1",
                    "uTime": "2",
                    "code": "0",
                    "msg": "",
                    "amendResult": "0",
                }
            )
        )
    finally:
        bot.audit_store.close()

    assert bot.state.pending_amend(buy_id) is None
    assert bot.state.live_orders[buy_id].price == Decimal("0.9999")
    assert any(event == "amend_order" for event, _ in bot.journal.events)
