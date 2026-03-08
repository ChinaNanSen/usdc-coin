from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable

import websockets

from .models import BookLevel, BookSnapshot, TradeTick
from .utils import now_ms, parse_decimal

logger = logging.getLogger(__name__)

BookCallback = Callable[[BookSnapshot], Awaitable[None]]
TradeCallback = Callable[[TradeTick], Awaitable[None]]
ReconnectCallback = Callable[[str], Awaitable[None]]
StatusCallback = Callable[[str, bool], Awaitable[None]]
ErrorCallback = Callable[[str, Exception], Awaitable[None]]


class PublicBookStream:
    def __init__(
        self,
        *,
        url: str,
        inst_id: str,
        on_book: BookCallback,
        on_trade: TradeCallback | None = None,
        on_reconnect: ReconnectCallback | None = None,
        on_status: StatusCallback | None = None,
        on_error: ErrorCallback | None = None,
        subscribe_trades: bool = False,
    ):
        self.url = url
        self.inst_id = inst_id
        self.on_book = on_book
        self.on_trade = on_trade
        self.on_reconnect = on_reconnect
        self.on_status = on_status
        self.on_error = on_error
        self.subscribe_trades = subscribe_trades
        self.ws = None
        self.running = False
        self.task: asyncio.Task | None = None
        self._connected_once = False

    async def start(self) -> None:
        if self.task:
            return
        self.running = True
        self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self.running = False
        await self._emit_status(False)
        if self.ws:
            await self.ws.close()
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
        self.task = None

    async def _run(self) -> None:
        while self.running:
            try:
                async with websockets.connect(self.url, ping_interval=None, close_timeout=5) as ws:
                    self.ws = ws
                    if self._connected_once and self.on_reconnect:
                        await self.on_reconnect("public_books5")
                    self._connected_once = True
                    subscribe_args = [{"channel": "books5", "instId": self.inst_id}]
                    if self.subscribe_trades:
                        subscribe_args.append({"channel": "trades", "instId": self.inst_id})
                    await ws.send(json.dumps({"op": "subscribe", "args": subscribe_args}))
                    await self._emit_status(True)
                    while self.running:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError:
                            await ws.send("ping")
                            continue
                        if raw == "pong":
                            continue
                        data = json.loads(raw)
                        if data.get("event") in {"subscribe", "unsubscribe"}:
                            continue
                        channel = data.get("arg", {}).get("channel")
                        if channel == "books5":
                            for item in data.get("data", []):
                                snapshot = BookSnapshot(
                                    ts_ms=int(item["ts"]),
                                    received_ms=now_ms(),
                                    bids=[
                                        BookLevel(price=parse_decimal(level[0]), size=parse_decimal(level[1]), order_count=int(level[3]))
                                        for level in item.get("bids", [])
                                    ],
                                    asks=[
                                        BookLevel(price=parse_decimal(level[0]), size=parse_decimal(level[1]), order_count=int(level[3]))
                                        for level in item.get("asks", [])
                                    ],
                                )
                                await self.on_book(snapshot)
                            continue
                        if channel == "trades" and self.on_trade:
                            received_ms = now_ms()
                            for item in data.get("data", []):
                                trade = TradeTick(
                                    ts_ms=int(item["ts"]),
                                    price=parse_decimal(item["px"]),
                                    size=parse_decimal(item["sz"]),
                                    side=str(item.get("side") or ""),
                                    received_ms=received_ms,
                                    trade_id=str(item.get("tradeId") or "") or None,
                                )
                                await self.on_trade(trade)
            except Exception as exc:
                if self.on_error:
                    await self.on_error("public_books5", exc)
                await self._emit_status(False)
                logger.warning("Public book stream reconnecting: %s", exc)
                await asyncio.sleep(1)

    async def _emit_status(self, connected: bool) -> None:
        if self.on_status:
            await self.on_status("public_books5", connected)
