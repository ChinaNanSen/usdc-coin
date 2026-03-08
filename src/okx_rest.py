from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

from .config import ExchangeConfig
from .models import Balance, BookLevel, BookSnapshot, InstrumentMeta
from .okx_auth import OKXSigner
from .utils import dumps_json, now_ms, parse_decimal, rest_timestamp

logger = logging.getLogger(__name__)


class OKXAPIError(RuntimeError):
    def __init__(
        self,
        *,
        path: str,
        code: str = "",
        msg: str = "",
        status_code: int | None = None,
        data: list[dict[str, Any]] | None = None,
    ):
        self.path = path
        self.code = str(code or "")
        self.msg = str(msg or "")
        self.status_code = status_code
        self.data = data or []
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        parts = [self.path]
        if self.status_code is not None:
            parts.append(f"http_status={self.status_code}")
        if self.code:
            parts.append(f"code={self.code}")
        if self.msg:
            parts.append(f"msg={self.msg}")
        item_details = self._format_item_details()
        if item_details:
            parts.append(f"details=[{item_details}]")
        return ": ".join(parts[:1]) + (" " + " ".join(parts[1:]) if len(parts) > 1 else "")

    def _format_item_details(self) -> str:
        parts: list[str] = []
        for item in self.data[:3]:
            detail = []
            if item.get("sCode") not in (None, "", "0", 0):
                detail.append(f"sCode={item.get('sCode')}")
            if item.get("sMsg"):
                detail.append(f"sMsg={item.get('sMsg')}")
            if item.get("clOrdId"):
                detail.append(f"clOrdId={item.get('clOrdId')}")
            if item.get("ordId"):
                detail.append(f"ordId={item.get('ordId')}")
            if item.get("tag"):
                detail.append(f"tag={item.get('tag')}")
            if detail:
                parts.append(", ".join(detail))
        return " | ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "http_status": self.status_code,
            "code": self.code,
            "msg": self.msg,
            "data": self.data,
        }

    @classmethod
    def from_payload(
        cls,
        *,
        path: str,
        payload: dict[str, Any],
        status_code: int | None = None,
    ) -> "OKXAPIError":
        return cls(
            path=path,
            code=str(payload.get("code") or ""),
            msg=str(payload.get("msg") or "Unknown OKX error"),
            status_code=status_code,
            data=list(payload.get("data") or []),
        )


class OKXRestClient:
    def __init__(self, config: ExchangeConfig):
        self.config = config
        self.signer = OKXSigner(config.api_key, config.secret_key, config.passphrase)
        self.time_offset_ms = 0
        self.client = httpx.AsyncClient(
            base_url=config.rest_url,
            timeout=config.request_timeout_seconds,
            headers={"User-Agent": config.user_agent},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def sync_time_offset(self) -> None:
        data = await self._request("GET", "/api/v5/public/time", private=False)
        server_ms = int(data[0]["ts"])
        local_ms = int(time.time() * 1000)
        self.time_offset_ms = server_ms - local_ms
        logger.info("Synced server time offset: %sms", self.time_offset_ms)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        private: bool = False,
    ) -> list[dict[str, Any]]:
        params = params or {}
        query_string = urlencode([(key, str(value)) for key, value in params.items() if value is not None])
        path_with_query = path if not query_string else f"{path}?{query_string}"
        body = dumps_json(json_body) if json_body else ""

        headers: dict[str, str] = {}
        if private:
            timestamp = rest_timestamp(self.time_offset_ms)
            headers.update(self.signer.rest_headers(timestamp, method, path_with_query, body))
            if self.config.simulated:
                headers["x-simulated-trading"] = "1"

        try:
            response = await self.client.request(method, path, params=params, content=body or None, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            raise OKXAPIError(
                path=path,
                msg=detail[:1000] or str(exc),
                status_code=exc.response.status_code,
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise OKXAPIError(path=path, msg=f"Invalid JSON response: {response.text[:1000]}") from exc

        if payload.get("code") != "0":
            raise OKXAPIError.from_payload(path=path, payload=payload, status_code=response.status_code)
        return payload.get("data", [])

    async def fetch_instrument(self, inst_id: str, inst_type: str) -> InstrumentMeta:
        data = await self._request(
            "GET",
            "/api/v5/public/instruments",
            params={"instType": inst_type, "instId": inst_id},
            private=False,
        )
        if not data:
            raise OKXAPIError(f"Instrument not found: {inst_id}")
        item = data[0]
        return InstrumentMeta(
            inst_id=item["instId"],
            inst_type=item["instType"],
            base_ccy=item["baseCcy"],
            quote_ccy=item["quoteCcy"],
            tick_size=parse_decimal(item["tickSz"]),
            lot_size=parse_decimal(item["lotSz"]),
            min_size=parse_decimal(item["minSz"]),
            max_market_amount=parse_decimal(item.get("maxMktAmt") or "0"),
            max_limit_amount=parse_decimal(item.get("maxLmtAmt") or "0"),
            inst_id_code=str(item.get("instIdCode") or "") or None,
            state=str(item.get("state") or "live"),
            rule_type=str(item.get("ruleType") or "normal"),
        )

    async def fetch_order_book(self, inst_id: str, depth: int = 5) -> BookSnapshot:
        data = await self._request(
            "GET",
            "/api/v5/market/books",
            params={"instId": inst_id, "sz": depth},
            private=False,
        )
        if not data:
            raise OKXAPIError(f"Order book empty: {inst_id}")
        book = data[0]
        return BookSnapshot(
            ts_ms=int(book["ts"]),
            received_ms=now_ms(),
            bids=[BookLevel(price=parse_decimal(level[0]), size=parse_decimal(level[1]), order_count=int(level[3])) for level in book["bids"]],
            asks=[BookLevel(price=parse_decimal(level[0]), size=parse_decimal(level[1]), order_count=int(level[3])) for level in book["asks"]],
        )

    async def fetch_balances(self, ccys: list[str]) -> dict[str, Balance]:
        data = await self._request(
            "GET",
            "/api/v5/account/balance",
            params={"ccy": ",".join(ccys)},
            private=True,
        )
        balances: dict[str, Balance] = {}
        if not data:
            return balances
        details = data[0].get("details", [])
        for item in details:
            ccy = item.get("ccy")
            if not ccy:
                continue
            total = parse_decimal(item.get("cashBal") or item.get("eq") or "0")
            available = parse_decimal(item.get("availBal") or item.get("availEq") or total)
            frozen = max(total - available, Decimal("0"))
            balances[ccy] = Balance(ccy=ccy, total=total, available=available, frozen=frozen)
        return balances

    async def fetch_trade_fee(self, inst_type: str, inst_id: str) -> dict[str, Any]:
        data = await self._request(
            "GET",
            "/api/v5/account/trade-fee",
            params={"instType": inst_type, "instId": inst_id},
            private=True,
        )
        if not data:
            raise OKXAPIError(f"Trade fee empty: {inst_id}")
        item = data[0]
        return {
            "maker": parse_decimal(item.get("maker") or "0"),
            "taker": parse_decimal(item.get("taker") or "0"),
            "feeType": str(item.get("feeType") or ""),
            "level": str(item.get("level") or ""),
        }

    async def list_pending_orders(self, inst_id: str, inst_type: str) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            "/api/v5/trade/orders-pending",
            params={"instType": inst_type, "instId": inst_id},
            private=True,
        )

    async def place_limit_order(
        self,
        *,
        inst_id: str,
        side: str,
        price: Decimal,
        size: Decimal,
        cl_ord_id: str,
        post_only: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "instId": inst_id,
            "tdMode": "cash",
            "side": side,
            "ordType": "post_only" if post_only else "limit",
            "px": str(price),
            "sz": str(size),
            "clOrdId": cl_ord_id,
        }
        data = await self._request("POST", "/api/v5/trade/order", json_body=payload, private=True)
        if not data:
            raise OKXAPIError(path="/api/v5/trade/order", msg="empty data")
        item = data[0]
        if str(item.get("sCode") or "0") != "0":
            raise OKXAPIError(
                path="/api/v5/trade/order",
                code=str(item.get("sCode") or ""),
                msg=str(item.get("sMsg") or "place order failed"),
                data=[item],
            )
        return item

    async def cancel_order(self, *, inst_id: str, ord_id: str | None = None, cl_ord_id: str | None = None) -> dict[str, Any]:
        payload = {"instId": inst_id}
        if ord_id:
            payload["ordId"] = ord_id
        if cl_ord_id:
            payload["clOrdId"] = cl_ord_id
        data = await self._request("POST", "/api/v5/trade/cancel-order", json_body=payload, private=True)
        if not data:
            raise OKXAPIError(path="/api/v5/trade/cancel-order", msg="empty data")
        item = data[0]
        if str(item.get("sCode") or "0") != "0":
            raise OKXAPIError(
                path="/api/v5/trade/cancel-order",
                code=str(item.get("sCode") or ""),
                msg=str(item.get("sMsg") or "cancel order failed"),
                data=[item],
            )
        return item
