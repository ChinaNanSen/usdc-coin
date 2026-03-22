from decimal import Decimal
import asyncio
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.binance_auth import BinanceSigner
from src.binance_rest import BinanceRestClient, BinanceAPIError
from src.config import ExchangeConfig


def test_binance_signer_adds_signature():
    signer = BinanceSigner("key", "secret")
    signed = signer.sign_query({"symbol": "USDCUSDT", "timestamp": "1"})
    assert "timestamp=1" in signed
    assert signed.index("symbol=USDCUSDT") < signed.index("timestamp=1")
    assert "signature=" in signed


def test_binance_rest_fetch_instrument_parses_exchange_info():
    payload = {
        "symbols": [
            {
                "symbol": "USDCUSDT",
                "baseAsset": "USDC",
                "quoteAsset": "USDT",
                "status": "TRADING",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.0001"},
                    {"filterType": "LOT_SIZE", "stepSize": "0.01", "minQty": "1"},
                    {"filterType": "NOTIONAL", "maxNotional": "1000000"},
                ],
            }
        ]
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async def run():
        client = BinanceRestClient(ExchangeConfig(name="binance"))
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.binance.com")
        try:
            return await client.fetch_instrument("USDC-USDT", "SPOT")
        finally:
            await client.close()

    instrument = asyncio.run(run())
    assert instrument.inst_id == "USDC-USDT"
    assert instrument.base_ccy == "USDC"
    assert instrument.quote_ccy == "USDT"
    assert instrument.tick_size == Decimal("0.0001")
    assert instrument.lot_size == Decimal("0.01")
    assert instrument.min_size == Decimal("1")
    assert instrument.state == "live"


def test_binance_rest_fetch_balances_parses_account_payload():
    payload = {
        "balances": [
            {"asset": "USDC", "free": "12.5", "locked": "0.5"},
            {"asset": "USDT", "free": "30", "locked": "2"},
        ]
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async def run():
        client = BinanceRestClient(ExchangeConfig(name="binance", api_key="k", secret_key="s"))
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.binance.com")
        try:
            return await client.fetch_balances(["USDC", "USDT"])
        finally:
            await client.close()

    balances = asyncio.run(run())
    assert balances["USDC"].total == Decimal("13.0")
    assert balances["USDC"].available == Decimal("12.5")
    assert balances["USDT"].frozen == Decimal("2")


def test_binance_rest_fetch_trade_fee_parses_commission_payload():
    payload = {
        "symbol": "USDCUSDT",
        "standardCommission": {"maker": "0.00000000", "taker": "0.00100000"},
        "discount": {"enabledForAccount": True},
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async def run():
        client = BinanceRestClient(ExchangeConfig(name="binance", api_key="k", secret_key="s"))
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.binance.com")
        try:
            return await client.fetch_trade_fee("SPOT", "USDC-USDT")
        finally:
            await client.close()

    fee = asyncio.run(run())
    assert fee["maker"] == Decimal("0")
    assert fee["taker"] == Decimal("0.001")
    assert fee["feeType"] == "standardCommission"


def test_binance_rest_place_limit_order_raises_binance_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})

    async def run():
        client = BinanceRestClient(ExchangeConfig(name="binance", api_key="k", secret_key="s"))
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.binance.com")
        try:
            await client.place_limit_order(
                inst_id="USDC-USDT",
                side="buy",
                price=Decimal("1"),
                size=Decimal("1"),
                cl_ord_id="testbinance001",
                post_only=True,
            )
        finally:
            await client.close()

    try:
        asyncio.run(run())
    except BinanceAPIError as exc:
        assert exc.code == "-1121"
    else:
        raise AssertionError("Expected BinanceAPIError")
