from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable

import websockets

from .okx_auth import OKXSigner
from .utils import ws_login_timestamp

logger = logging.getLogger(__name__)

RawHandler = Callable[[dict], Awaitable[None]]
ReconnectHandler = Callable[[str], Awaitable[None]]
StatusHandler = Callable[[str, bool], Awaitable[None]]
ErrorHandler = Callable[[str, Exception], Awaitable[None]]


class PrivateUserStream:
    def __init__(
        self,
        *,
        url: str,
        signer: OKXSigner,
        time_offset_ms: int,
        inst_type: str,
        on_order: RawHandler,
        on_account: RawHandler,
        on_reconnect: ReconnectHandler | None = None,
        on_status: StatusHandler | None = None,
        on_error: ErrorHandler | None = None,
    ):
        self.url = url
        self.signer = signer
        self.time_offset_ms = time_offset_ms
        self.inst_type = inst_type
        self.on_order = on_order
        self.on_account = on_account
        self.on_reconnect = on_reconnect
        self.on_status = on_status
        self.on_error = on_error
        self.running = False
        self.ws = None
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
                        await self.on_reconnect("private_user")
                    self._connected_once = True

                    await self._login(ws)
                    await ws.send(
                        json.dumps(
                            {
                                "op": "subscribe",
                                "args": [
                                    {"channel": "orders", "instType": self.inst_type},
                                    {"channel": "account"},
                                ],
                            }
                        )
                    )
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
                        if data.get("event") in {"login", "subscribe", "unsubscribe"}:
                            continue
                        channel = data.get("arg", {}).get("channel")
                        if channel == "orders":
                            for item in data.get("data", []):
                                await self.on_order(item)
                        elif channel == "account":
                            for item in data.get("data", []):
                                await self.on_account(item)
            except Exception as exc:
                if self.on_error:
                    await self.on_error("private_user", exc)
                await self._emit_status(False)
                logger.warning("Private user stream reconnecting: %s", exc)
                await asyncio.sleep(1)

    async def _login(self, ws) -> None:
        timestamp = ws_login_timestamp(self.time_offset_ms)
        await ws.send(json.dumps({"op": "login", "args": [self.signer.ws_login_args(timestamp)]}))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if response.get("event") != "login" or response.get("code") != "0":
            raise RuntimeError(f"Private WS login failed: {response}")

    async def _emit_status(self, connected: bool) -> None:
        if self.on_status:
            await self.on_status("private_user", connected)
