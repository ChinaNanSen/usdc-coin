from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.okx_rest import OKXRestClient
from src.config import ExchangeConfig


class DummyTickerRest(OKXRestClient):
    async def _request(self, method, path, *, params=None, json_body=None, private=False):
        assert method == "GET"
        assert path == "/api/v5/market/ticker"
        assert params == {"instId": "USDC-USDT"}
        return [
            {
                "instId": "USDC-USDT",
                "bidPx": "1.0001",
                "askPx": "1.0002",
                "vol24h": "30984543.48826",
                "volCcy24h": "30988008.3181610414",
                "ts": "1234567890",
            }
        ]


async def _fetch():
    client = DummyTickerRest(ExchangeConfig())
    try:
        return await client.fetch_ticker("USDC-USDT")
    finally:
        await client.close()


def test_fetch_ticker_parses_okx_payload():
    import asyncio

    ticker = asyncio.run(_fetch())

    assert ticker["inst_id"] == "USDC-USDT"
    assert ticker["bid_px"] == Decimal("1.0001")
    assert ticker["ask_px"] == Decimal("1.0002")
    assert ticker["vol24h"] == Decimal("30984543.48826")
    assert ticker["vol_ccy24h"] == Decimal("30988008.3181610414")
    assert ticker["ts_ms"] == 1234567890
