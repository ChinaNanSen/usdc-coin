import asyncio
from decimal import Decimal
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.bot import TrendBot6
from src.config import BotConfig


class StubJournal:
    def __init__(self):
        self.events = []

    def append(self, event: str, payload: dict) -> None:
        self.events.append((event, payload))


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
