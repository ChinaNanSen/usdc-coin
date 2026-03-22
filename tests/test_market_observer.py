import asyncio
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import BotConfig
from src.exchange_errors import ExchangeAPIError
from src.market_observer import (
    build_market_observation,
    collect_market_observations,
    render_market_observer_report,
)
from src.models import BookLevel, BookSnapshot, InstrumentMeta
from src.okx_rest import OKXAPIError


def _instrument(inst_id: str) -> InstrumentMeta:
    base_ccy, quote_ccy = inst_id.split("-")
    return InstrumentMeta(
        inst_id=inst_id,
        inst_type="SPOT",
        base_ccy=base_ccy,
        quote_ccy=quote_ccy,
        tick_size=Decimal("0.0001"),
        lot_size=Decimal("0.0001"),
        min_size=Decimal("1"),
        max_market_amount=Decimal("1000000"),
        max_limit_amount=Decimal("20000000"),
        state="live",
    )


def _book() -> BookSnapshot:
    return BookSnapshot(
        ts_ms=1,
        received_ms=2,
        bids=[BookLevel(price=Decimal("1.0001"), size=Decimal("400000"))],
        asks=[BookLevel(price=Decimal("1.0002"), size=Decimal("500000"))],
    )


class DummyObserverRest:
    def __init__(self, _exchange_config):
        self.closed = False

    async def sync_time_offset(self) -> None:
        return None

    async def fetch_instrument(self, inst_id: str, _inst_type: str) -> InstrumentMeta:
        return _instrument(inst_id)

    async def fetch_order_book(self, _inst_id: str, _depth: int) -> BookSnapshot:
        return _book()

    async def fetch_ticker(self, inst_id: str) -> dict[str, Decimal | str | int]:
        return {
            "inst_id": inst_id,
            "bid_px": Decimal("1.0001"),
            "ask_px": Decimal("1.0002"),
            "vol24h": Decimal("1000000"),
            "vol_ccy24h": Decimal("1000000"),
            "ts_ms": 3,
        }

    async def fetch_trade_fee(self, _inst_type: str, inst_id: str) -> dict[str, Decimal | str]:
        if inst_id == "DAI-USDT":
            raise OKXAPIError(
                path="/api/v5/account/trade-fee",
                code="51001",
                msg="Instrument ID, Instrument ID code, or Spread ID doesn't exist.",
                status_code=200,
            )
        return {
            "maker": Decimal("0"),
            "taker": Decimal("0"),
            "feeType": "level_based",
        }

    async def close(self) -> None:
        self.closed = True


class DummyBinanceObserverRest(DummyObserverRest):
    async def fetch_trade_fee(self, _inst_type: str, inst_id: str) -> dict[str, Decimal | str]:
        if inst_id == "DAI-USDT":
            raise ExchangeAPIError(
                path="/api/v3/account/commission",
                code="-1121",
                msg="Invalid symbol.",
                status_code=400,
            )
        return {
            "maker": Decimal("0"),
            "taker": Decimal("0"),
            "feeType": "standardCommission",
        }


def test_build_market_observation_computes_fee_spread_and_depth_multiples():
    observation = build_market_observation(
        instrument=InstrumentMeta(
            inst_id="USDG-USDT",
            inst_type="SPOT",
            base_ccy="USDG",
            quote_ccy="USDT",
            tick_size=Decimal("0.0001"),
            lot_size=Decimal("0.0001"),
            min_size=Decimal("1"),
            max_market_amount=Decimal("1000000"),
            max_limit_amount=Decimal("20000000"),
            state="live",
        ),
        book=BookSnapshot(
            ts_ms=1,
            received_ms=2,
            bids=[
                BookLevel(price=Decimal("1.0001"), size=Decimal("400000")),
                BookLevel(price=Decimal("1.0000"), size=Decimal("600000")),
            ],
            asks=[
                BookLevel(price=Decimal("1.0002"), size=Decimal("500000")),
                BookLevel(price=Decimal("1.0003"), size=Decimal("300000")),
            ],
        ),
        ticker={
            "inst_id": "USDG-USDT",
            "bid_px": Decimal("1.0001"),
            "ask_px": Decimal("1.0002"),
            "vol24h": Decimal("5705108.1351"),
            "vol_ccy24h": Decimal("5705127.24028008"),
            "ts_ms": 3,
        },
        fee={
            "maker": Decimal("0"),
            "taker": Decimal("0"),
            "feeType": "level_based",
        },
        reference_quote_size=Decimal("5000"),
    )

    assert observation.inst_id == "USDG-USDT"
    assert observation.spread_ticks == Decimal("1")
    assert observation.fee_ok is True
    assert observation.best_bid_depth_multiple == Decimal("80")
    assert observation.best_ask_depth_multiple == Decimal("100")
    assert observation.top5_bid_depth_multiple == Decimal("200")
    assert observation.top5_ask_depth_multiple == Decimal("160")
    assert observation.issues == ()


def test_render_market_observer_report_surfaces_non_zero_fee_and_thin_book():
    observation = build_market_observation(
        instrument=InstrumentMeta(
            inst_id="PYUSD-USDT",
            inst_type="SPOT",
            base_ccy="PYUSD",
            quote_ccy="USDT",
            tick_size=Decimal("0.0001"),
            lot_size=Decimal("0.0001"),
            min_size=Decimal("1"),
            max_market_amount=Decimal("1000000"),
            max_limit_amount=Decimal("20000000"),
            state="live",
        ),
        book=BookSnapshot(
            ts_ms=1,
            received_ms=2,
            bids=[BookLevel(price=Decimal("1.0000"), size=Decimal("1000"))],
            asks=[BookLevel(price=Decimal("1.0001"), size=Decimal("2000"))],
        ),
        ticker={
            "inst_id": "PYUSD-USDT",
            "bid_px": Decimal("1.0000"),
            "ask_px": Decimal("1.0001"),
            "vol24h": Decimal("908818.4992"),
            "vol_ccy24h": Decimal("908676.61528251"),
            "ts_ms": 3,
        },
        fee={
            "maker": Decimal("0.0005"),
            "taker": Decimal("0.001"),
            "feeType": "level_based",
        },
        reference_quote_size=Decimal("5000"),
    )

    report = render_market_observer_report([observation], reference_quote_size=Decimal("5000"))

    assert "PYUSD-USDT" in report
    assert "maker=0.0005" in report
    assert "best_depth_x" in report
    assert "fee_nonzero" in report
    assert "best_level_thin" in report


def test_collect_market_observations_keeps_pair_when_fee_fetch_fails(monkeypatch):
    monkeypatch.setattr("src.market_observer.OKXRestClient", DummyObserverRest)

    observations = asyncio.run(
        collect_market_observations(
            config=BotConfig(mode="live"),
            inst_ids=["USDC-USDT", "DAI-USDT"],
            reference_quote_size=Decimal("5000"),
        )
    )

    assert [observation.inst_id for observation in observations] == ["USDC-USDT", "DAI-USDT"]

    dai_observation = observations[1]
    report = render_market_observer_report(observations, reference_quote_size=Decimal("5000"))

    assert dai_observation.fee_available is False
    assert dai_observation.fee_ok is False
    assert "fee_unavailable" in dai_observation.issues
    assert "fee_fetch_failed:51001" in dai_observation.issues
    assert "DAI-USDT" in report
    assert "maker=na" in report
    assert "fee_unavailable" in report


def test_collect_market_observations_uses_binance_rest_when_exchange_name_is_binance(monkeypatch):
    monkeypatch.setattr("src.market_observer.BinanceRestClient", DummyBinanceObserverRest)
    config = BotConfig(mode="live")
    config.exchange.name = "binance"

    observations = asyncio.run(
        collect_market_observations(
            config=config,
            inst_ids=["USDC-USDT", "DAI-USDT"],
            reference_quote_size=Decimal("5000"),
        )
    )

    assert [observation.inst_id for observation in observations] == ["USDC-USDT", "DAI-USDT"]
    assert observations[0].fee_type == "standardCommission"
    assert "fee_fetch_failed:-1121" in observations[1].issues
