from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

import httpx

from .binance_auth import BinanceSigner
from .config import ExchangeConfig
from .exchange_errors import ExchangeAPIError
from .models import Balance, BookLevel, BookSnapshot, InstrumentMeta
from .utils import now_ms, parse_decimal


class BinanceAPIError(ExchangeAPIError):
    def _format_item_details(self) -> str:
        parts: list[str] = []
        for item in self.data[:3]:
            detail = []
            if item.get("code") not in (None, "", 0, "0"):
                detail.append(f"code={item.get('code')}")
            if item.get("msg"):
                detail.append(f"msg={item.get('msg')}")
            if item.get("clientOrderId"):
                detail.append(f"clientOrderId={item.get('clientOrderId')}")
            if item.get("orderId"):
                detail.append(f"orderId={item.get('orderId')}")
            if detail:
                parts.append(", ".join(detail))
        return " | ".join(parts)

    @classmethod
    def from_payload(
        cls,
        *,
        path: str,
        payload: dict[str, Any],
        status_code: int | None = None,
    ) -> "BinanceAPIError":
        return cls(
            path=path,
            code=str(payload.get("code") or ""),
            msg=str(payload.get("msg") or "Unknown Binance error"),
            status_code=status_code,
            data=[payload],
        )


class BinanceRestClient:
    def __init__(self, config: ExchangeConfig):
        self.config = config
        self.signer = BinanceSigner(config.api_key, config.secret_key)
        self.time_offset_ms = 0
        self.client = httpx.AsyncClient(
            base_url=config.rest_url,
            timeout=config.request_timeout_seconds,
            headers={"User-Agent": config.user_agent},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def sync_time_offset(self) -> None:
        payload = await self._request("GET", "/api/v3/time")
        server_ms = int(payload["serverTime"])
        local_ms = int(time.time() * 1000)
        self.time_offset_ms = server_ms - local_ms

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        signed: bool = False,
        api_key_only: bool = False,
    ) -> Any:
        params = {key: str(value) for key, value in (params or {}).items() if value is not None}
        headers: dict[str, str] = {}
        if signed or api_key_only:
            headers.update(self.signer.api_key_headers())
        if signed:
            params.setdefault("timestamp", str(now_ms() + self.time_offset_ms))
            params.setdefault("recvWindow", "5000")
            query = self.signer.sign_query(params)
            request_params = None
            request_url = f"{path}?{query}"
        else:
            request_params = params
            request_url = path
        try:
            response = await self.client.request(method, request_url, params=request_params, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            try:
                payload = exc.response.json()
            except ValueError:
                raise BinanceAPIError(path=path, msg=detail[:1000] or str(exc), status_code=exc.response.status_code) from exc
            raise BinanceAPIError.from_payload(path=path, payload=payload, status_code=exc.response.status_code) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise BinanceAPIError(path=path, msg=f"Invalid JSON response: {response.text[:1000]}") from exc
        if isinstance(payload, dict) and payload.get("code") not in (None, 200, "200") and "msg" in payload and path != "/api/v3/time":
            # Binance error payloads often come back as JSON with code/msg.
            if str(payload.get("code")) != "0":
                raise BinanceAPIError.from_payload(path=path, payload=payload, status_code=response.status_code)
        return payload

    @staticmethod
    def _symbol(inst_id: str) -> str:
        return str(inst_id).replace("-", "").upper()

    async def fetch_instrument(self, inst_id: str, inst_type: str) -> InstrumentMeta:
        if inst_type != "SPOT":
            raise BinanceAPIError(path="/api/v3/exchangeInfo", msg=f"Unsupported instType for Binance: {inst_type}")
        payload = await self._request("GET", "/api/v3/exchangeInfo", params={"symbol": self._symbol(inst_id)})
        symbols = list(payload.get("symbols") or [])
        if not symbols:
            raise BinanceAPIError(path="/api/v3/exchangeInfo", msg=f"Instrument not found: {inst_id}")
        item = symbols[0]
        filters = {f.get("filterType"): f for f in item.get("filters", [])}
        price_filter = filters.get("PRICE_FILTER") or {}
        lot_filter = filters.get("LOT_SIZE") or {}
        notional_filter = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
        return InstrumentMeta(
            inst_id=inst_id,
            inst_type="SPOT",
            base_ccy=str(item.get("baseAsset") or ""),
            quote_ccy=str(item.get("quoteAsset") or ""),
            tick_size=parse_decimal(price_filter.get("tickSize") or "0"),
            lot_size=parse_decimal(lot_filter.get("stepSize") or "0"),
            min_size=parse_decimal(lot_filter.get("minQty") or "0"),
            max_market_amount=parse_decimal(notional_filter.get("maxNotional") or "0"),
            max_limit_amount=parse_decimal(notional_filter.get("maxNotional") or "0"),
            inst_id_code=None,
            state="live" if str(item.get("status") or "TRADING").upper() == "TRADING" else str(item.get("status") or ""),
            rule_type="normal",
        )

    async def fetch_order_book(self, inst_id: str, depth: int = 5) -> BookSnapshot:
        payload = await self._request("GET", "/api/v3/depth", params={"symbol": self._symbol(inst_id), "limit": depth})
        return BookSnapshot(
            ts_ms=now_ms(),
            received_ms=now_ms(),
            bids=[BookLevel(price=parse_decimal(level[0]), size=parse_decimal(level[1])) for level in payload.get("bids", [])],
            asks=[BookLevel(price=parse_decimal(level[0]), size=parse_decimal(level[1])) for level in payload.get("asks", [])],
        )

    async def fetch_ticker(self, inst_id: str) -> dict[str, Any]:
        payload = await self._request("GET", "/api/v3/ticker/24hr", params={"symbol": self._symbol(inst_id)})
        return {
            "inst_id": inst_id,
            "bid_px": parse_decimal(payload.get("bidPrice") or "0"),
            "ask_px": parse_decimal(payload.get("askPrice") or "0"),
            "vol24h": parse_decimal(payload.get("volume") or "0"),
            "vol_ccy24h": parse_decimal(payload.get("quoteVolume") or "0"),
            "ts_ms": now_ms(),
        }

    async def fetch_balances(self, ccys: list[str]) -> dict[str, Balance]:
        payload = await self._request("GET", "/api/v3/account", signed=True)
        balances: dict[str, Balance] = {}
        for item in payload.get("balances", []):
            ccy = str(item.get("asset") or "")
            if ccy not in ccys:
                continue
            available = parse_decimal(item.get("free") or "0")
            frozen = parse_decimal(item.get("locked") or "0")
            balances[ccy] = Balance(ccy=ccy, total=available + frozen, available=available, frozen=frozen)
        return balances

    async def fetch_trade_fee(self, inst_type: str, inst_id: str) -> dict[str, Any]:
        if inst_type != "SPOT":
            raise BinanceAPIError(path="/api/v3/account/commission", msg=f"Unsupported instType for Binance: {inst_type}")
        payload = await self._request("GET", "/api/v3/account/commission", params={"symbol": self._symbol(inst_id)}, signed=True)
        standard = payload.get("standardCommission") or {}
        return {
            "maker": parse_decimal(standard.get("maker") or "0"),
            "taker": parse_decimal(standard.get("taker") or "0"),
            "feeType": "standardCommission",
            "discount": payload.get("discount") or {},
        }

    async def list_pending_orders(self, inst_id: str, inst_type: str) -> list[dict[str, Any]]:
        if inst_type != "SPOT":
            raise BinanceAPIError(path="/api/v3/openOrders", msg=f"Unsupported instType for Binance: {inst_type}")
        payload = await self._request("GET", "/api/v3/openOrders", params={"symbol": self._symbol(inst_id)}, signed=True)
        return list(payload or [])

    async def place_limit_order(
        self,
        *,
        inst_id: str,
        side: str,
        price: Decimal,
        size: Decimal,
        cl_ord_id: str,
        post_only: bool = False,
        req_id: str | None = None,
        inst_id_code: str | None = None,
    ) -> dict[str, Any]:
        del req_id, inst_id_code
        payload = {
            "symbol": self._symbol(inst_id),
            "side": side.upper(),
            "type": "LIMIT_MAKER" if post_only else "LIMIT",
            "price": str(price),
            "quantity": str(size),
            "newClientOrderId": cl_ord_id,
        }
        if not post_only:
            payload["timeInForce"] = "GTC"
        return await self._request("POST", "/api/v3/order", params=payload, signed=True)

    async def cancel_order(
        self,
        *,
        inst_id: str,
        ord_id: str | None = None,
        cl_ord_id: str | None = None,
        req_id: str | None = None,
        inst_id_code: str | None = None,
    ) -> dict[str, Any]:
        del req_id, inst_id_code
        payload = {"symbol": self._symbol(inst_id)}
        if ord_id:
            payload["orderId"] = ord_id
        if cl_ord_id:
            payload["origClientOrderId"] = cl_ord_id
        return await self._request("DELETE", "/api/v3/order", params=payload, signed=True)

    async def fetch_order(self, *, inst_id: str, ord_id: str | None = None, cl_ord_id: str | None = None) -> dict[str, Any]:
        payload = {"symbol": self._symbol(inst_id)}
        if ord_id:
            payload["orderId"] = ord_id
        if cl_ord_id:
            payload["origClientOrderId"] = cl_ord_id
        return await self._request("GET", "/api/v3/order", params=payload, signed=True)

    async def start_user_data_stream(self) -> str:
        payload = await self._request("POST", "/api/v3/userDataStream", api_key_only=True)
        listen_key = str(payload.get("listenKey") or "")
        if not listen_key:
            raise BinanceAPIError(path="/api/v3/userDataStream", msg="listenKey missing")
        return listen_key

    async def keepalive_user_data_stream(self, listen_key: str) -> None:
        await self._request("PUT", "/api/v3/userDataStream", params={"listenKey": listen_key}, api_key_only=True)

    async def close_user_data_stream(self, listen_key: str) -> None:
        await self._request("DELETE", "/api/v3/userDataStream", params={"listenKey": listen_key}, api_key_only=True)
