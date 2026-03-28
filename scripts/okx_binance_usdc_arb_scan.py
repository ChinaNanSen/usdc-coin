from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.binance_rest import BinanceRestClient
from src.config import BotConfig, load_config
from src.market_observer import build_market_observation
from src.okx_rest import OKXRestClient
from src.utils import decimal_to_str


@dataclass(frozen=True)
class ArbLeg:
    exchange: str
    bid: Decimal
    ask: Decimal
    best_bid_depth: Decimal
    best_ask_depth: Decimal
    maker_fee: Decimal
    taker_fee: Decimal
    vol24h_quote: Decimal
    issues: tuple[str, ...]


@dataclass(frozen=True)
class ArbOpportunity:
    direction: str
    maker_exchange: str
    taker_exchange: str
    maker_price: Decimal
    taker_price: Decimal
    gross_edge_bp: Decimal
    net_edge_bp: Decimal
    max_quote_notional: Decimal
    maker_depth_quote: Decimal
    taker_depth_quote: Decimal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OKX vs Binance USDC/USDT read-only arbitrage scanner")
    parser.add_argument("--okx-config", type=str, default=str(ROOT / "config" / "config.usdc.yaml"))
    parser.add_argument("--binance-config", type=str, default=str(ROOT / "config" / "config.binance.usdc.mainnet.yaml"))
    parser.add_argument("--reference-quote-size", type=str, default="3000")
    parser.add_argument("--loops", type=int, default=1, help="0 means infinite loop")
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    parser.add_argument("--jsonl", type=str, default=str(ROOT / "data" / "arb" / "okx_binance_usdc_scan.jsonl"))
    return parser.parse_args()


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _observation_to_leg(exchange: str, observation) -> ArbLeg:
    maker_fee = observation.maker_fee if observation.fee_available else Decimal("0")
    taker_fee = observation.taker_fee if observation.fee_available else Decimal("0")
    return ArbLeg(
        exchange=exchange,
        bid=observation.best_bid,
        ask=observation.best_ask,
        best_bid_depth=observation.best_bid_depth,
        best_ask_depth=observation.best_ask_depth,
        maker_fee=maker_fee,
        taker_fee=taker_fee,
        vol24h_quote=observation.vol24h_quote,
        issues=observation.issues,
    )


def _quote_notional(price: Decimal, size: Decimal) -> Decimal:
    return price * size if price > 0 and size > 0 else Decimal("0")


def _calc_opportunity(*, maker_exchange: str, taker_exchange: str, maker_ask: Decimal, taker_bid: Decimal, maker_ask_depth: Decimal, taker_bid_depth: Decimal, maker_fee: Decimal, taker_fee: Decimal) -> ArbOpportunity:
    if maker_ask <= 0 or taker_bid <= 0:
        gross_edge_bp = Decimal("0")
    else:
        gross_edge_bp = ((taker_bid - maker_ask) / maker_ask) * Decimal("10000")
    net_edge_bp = gross_edge_bp - (maker_fee + taker_fee) * Decimal("10000")
    maker_depth_quote = _quote_notional(maker_ask, maker_ask_depth)
    taker_depth_quote = _quote_notional(taker_bid, taker_bid_depth)
    max_quote_notional = min(maker_depth_quote, taker_depth_quote)
    return ArbOpportunity(
        direction=f"buy_{maker_exchange}_sell_{taker_exchange}",
        maker_exchange=maker_exchange,
        taker_exchange=taker_exchange,
        maker_price=maker_ask,
        taker_price=taker_bid,
        gross_edge_bp=gross_edge_bp,
        net_edge_bp=net_edge_bp,
        max_quote_notional=max_quote_notional,
        maker_depth_quote=maker_depth_quote,
        taker_depth_quote=taker_depth_quote,
    )


async def collect_leg(exchange_name: str, config: BotConfig, reference_quote_size: Decimal):
    rest = BinanceRestClient(config.exchange) if exchange_name == "binance" else OKXRestClient(config.exchange)
    try:
        await rest.sync_time_offset()
        instrument = await rest.fetch_instrument(config.trading.inst_id, config.trading.inst_type)
        book = await rest.fetch_order_book(config.trading.inst_id, 5)
        ticker = await rest.fetch_ticker(config.trading.inst_id)
        fee = await rest.fetch_trade_fee(config.trading.inst_type, config.trading.inst_id)
        observation = build_market_observation(
            instrument=instrument,
            book=book,
            ticker=ticker,
            fee=fee,
            reference_quote_size=reference_quote_size,
        )
        return _observation_to_leg(exchange_name, observation), observation
    finally:
        await rest.close()


def render_report(*, timestamp_ms: int, okx_obs, binance_obs, opportunities: list[ArbOpportunity]) -> str:
    lines = [
        "OKX vs Binance USDC/USDT Read-Only Arb Scan",
        f"- ts_ms={timestamp_ms}",
        f"- okx bid={decimal_to_str(okx_obs.best_bid)} ask={decimal_to_str(okx_obs.best_ask)} maker={decimal_to_str(okx_obs.maker_fee)} taker={decimal_to_str(okx_obs.taker_fee)} best_depth_quote bid={decimal_to_str(_quote_notional(okx_obs.best_bid, okx_obs.best_bid_depth))} ask={decimal_to_str(_quote_notional(okx_obs.best_ask, okx_obs.best_ask_depth))} issues={','.join(okx_obs.issues) or 'ok'}",
        f"- binance bid={decimal_to_str(binance_obs.best_bid)} ask={decimal_to_str(binance_obs.best_ask)} maker={decimal_to_str(binance_obs.maker_fee)} taker={decimal_to_str(binance_obs.taker_fee)} best_depth_quote bid={decimal_to_str(_quote_notional(binance_obs.best_bid, binance_obs.best_bid_depth))} ask={decimal_to_str(_quote_notional(binance_obs.best_ask, binance_obs.best_ask_depth))} issues={','.join(binance_obs.issues) or 'ok'}",
    ]
    for opp in opportunities:
        lines.append(
            f"- {opp.direction}: gross_bp={decimal_to_str(opp.gross_edge_bp)} net_bp={decimal_to_str(opp.net_edge_bp)} max_quote_notional={decimal_to_str(opp.max_quote_notional)} maker_px={decimal_to_str(opp.maker_price)} taker_px={decimal_to_str(opp.taker_price)}"
        )
    return "\n".join(lines)


def _to_jsonable(value):
    if isinstance(value, Decimal):
        return decimal_to_str(value)
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return value


async def run_once(okx_config: BotConfig, binance_config: BotConfig, reference_quote_size: Decimal) -> tuple[str, dict]:
    okx_leg, okx_obs = await collect_leg("okx", okx_config, reference_quote_size)
    binance_leg, binance_obs = await collect_leg("binance", binance_config, reference_quote_size)

    opportunities = [
        _calc_opportunity(
            maker_exchange="okx",
            taker_exchange="binance",
            maker_ask=okx_leg.ask,
            taker_bid=binance_leg.bid,
            maker_ask_depth=okx_leg.best_ask_depth,
            taker_bid_depth=binance_leg.best_bid_depth,
            maker_fee=okx_leg.maker_fee,
            taker_fee=binance_leg.taker_fee,
        ),
        _calc_opportunity(
            maker_exchange="binance",
            taker_exchange="okx",
            maker_ask=binance_leg.ask,
            taker_bid=okx_leg.bid,
            maker_ask_depth=binance_leg.best_ask_depth,
            taker_bid_depth=okx_leg.best_bid_depth,
            maker_fee=binance_leg.maker_fee,
            taker_fee=okx_leg.taker_fee,
        ),
    ]
    timestamp_ms = int(time.time() * 1000)
    report = render_report(
        timestamp_ms=timestamp_ms,
        okx_obs=okx_obs,
        binance_obs=binance_obs,
        opportunities=opportunities,
    )
    payload = {
        "ts_ms": timestamp_ms,
        "reference_quote_size": decimal_to_str(reference_quote_size),
        "okx": _to_jsonable(asdict(okx_leg)),
        "binance": _to_jsonable(asdict(binance_leg)),
        "opportunities": _to_jsonable([asdict(item) for item in opportunities]),
    }
    return report, payload


async def main() -> None:
    args = parse_args()
    setup_logging()
    okx_config = load_config(args.okx_config, validate_live_credentials=False)
    binance_config = load_config(args.binance_config, validate_live_credentials=False)
    reference_quote_size = Decimal(args.reference_quote_size)
    jsonl_path = Path(args.jsonl)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    remaining = args.loops
    while True:
        report, payload = await run_once(okx_config, binance_config, reference_quote_size)
        print(report)
        with jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        if remaining == 1:
            break
        if remaining > 1:
            remaining -= 1
        await asyncio.sleep(args.interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())
