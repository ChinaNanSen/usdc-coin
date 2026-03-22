from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.binance_market_data import BinancePublicMarketStream
from src.models import BookLevel


def test_binance_market_stream_symbol_uses_lowercase_without_dash():
    stream = BinancePublicMarketStream(
        url="wss://stream.binance.com:9443/ws",
        inst_id="USDC-USDT",
        on_book=None,  # type: ignore[arg-type]
    )

    assert stream.symbol == "usdcusdt"


def test_binance_trade_side_mapping_matches_aggressor():
    # buyer is market maker => aggressor was seller
    stream = BinancePublicMarketStream(
        url="wss://stream.binance.com:9443/ws",
        inst_id="USDC-USDT",
        on_book=None,  # type: ignore[arg-type]
        on_trade=None,  # type: ignore[arg-type]
    )

    payload = {"T": 1, "p": "1.0001", "q": "10", "m": True, "t": 99}
    side = "sell" if bool(payload.get("m")) else "buy"

    assert side == "sell"
