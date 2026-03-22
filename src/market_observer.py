from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from .binance_rest import BinanceRestClient
from .config import BotConfig
from .exchange_errors import ExchangeAPIError
from .models import BookSnapshot, InstrumentMeta
from .okx_rest import OKXAPIError, OKXRestClient
from .utils import decimal_to_str

DEFAULT_OBSERVED_MARKETS: tuple[str, ...] = ("USDC-USDT", "USDG-USDT", "DAI-USDT", "PYUSD-USDT")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketObservation:
    inst_id: str
    inst_state: str
    tick_size: Decimal
    best_bid: Decimal
    best_ask: Decimal
    spread_ticks: Decimal
    fee_available: bool
    maker_fee: Decimal
    taker_fee: Decimal
    fee_type: str
    best_bid_depth: Decimal
    best_ask_depth: Decimal
    top5_bid_depth: Decimal
    top5_ask_depth: Decimal
    best_bid_depth_multiple: Decimal
    best_ask_depth_multiple: Decimal
    top5_bid_depth_multiple: Decimal
    top5_ask_depth_multiple: Decimal
    vol24h_base: Decimal
    vol24h_quote: Decimal
    reference_quote_size: Decimal
    issues: tuple[str, ...]

    @property
    def fee_ok(self) -> bool:
        return self.fee_available and self.maker_fee <= 0 and self.taker_fee <= 0


def build_market_observation(
    *,
    instrument: InstrumentMeta,
    book: BookSnapshot,
    ticker: dict[str, Decimal | str | int],
    fee: dict[str, Decimal | str] | None,
    reference_quote_size: Decimal,
    extra_issues: list[str] | tuple[str, ...] | None = None,
) -> MarketObservation:
    best_bid = book.best_bid.price if book.best_bid else Decimal("0")
    best_ask = book.best_ask.price if book.best_ask else Decimal("0")
    spread_ticks = Decimal("0")
    if instrument.tick_size > 0 and book.spread >= 0:
        spread_ticks = book.spread / instrument.tick_size

    best_bid_depth = book.best_bid.size if book.best_bid else Decimal("0")
    best_ask_depth = book.best_ask.size if book.best_ask else Decimal("0")
    top5_bid_depth = sum((level.size for level in book.bids), Decimal("0"))
    top5_ask_depth = sum((level.size for level in book.asks), Decimal("0"))

    if reference_quote_size > 0:
        best_bid_depth_multiple = best_bid_depth / reference_quote_size
        best_ask_depth_multiple = best_ask_depth / reference_quote_size
        top5_bid_depth_multiple = top5_bid_depth / reference_quote_size
        top5_ask_depth_multiple = top5_ask_depth / reference_quote_size
    else:
        best_bid_depth_multiple = Decimal("0")
        best_ask_depth_multiple = Decimal("0")
        top5_bid_depth_multiple = Decimal("0")
        top5_ask_depth_multiple = Decimal("0")

    fee_available = fee is not None
    maker_fee = Decimal(str(fee.get("maker") or "0")) if fee is not None else Decimal("0")
    taker_fee = Decimal(str(fee.get("taker") or "0")) if fee is not None else Decimal("0")
    issues: list[str] = []
    if str(instrument.state or "live") != "live":
        issues.append("instrument_not_live")
    if not fee_available:
        issues.append("fee_unavailable")
    elif maker_fee > 0 or taker_fee > 0:
        issues.append("fee_nonzero")
    if spread_ticks < 1:
        issues.append("spread_too_tight")
    if best_bid_depth_multiple < 1 or best_ask_depth_multiple < 1:
        issues.append("best_level_thin")
    if top5_bid_depth_multiple < 3 or top5_ask_depth_multiple < 3:
        issues.append("top5_thin")
    if extra_issues:
        issues.extend(extra_issues)
    issues = list(dict.fromkeys(issues))

    return MarketObservation(
        inst_id=instrument.inst_id,
        inst_state=instrument.state,
        tick_size=instrument.tick_size,
        best_bid=best_bid,
        best_ask=best_ask,
        spread_ticks=spread_ticks,
        fee_available=fee_available,
        maker_fee=maker_fee,
        taker_fee=taker_fee,
        fee_type=str(fee.get("feeType") or "") if fee is not None else "",
        best_bid_depth=best_bid_depth,
        best_ask_depth=best_ask_depth,
        top5_bid_depth=top5_bid_depth,
        top5_ask_depth=top5_ask_depth,
        best_bid_depth_multiple=best_bid_depth_multiple,
        best_ask_depth_multiple=best_ask_depth_multiple,
        top5_bid_depth_multiple=top5_bid_depth_multiple,
        top5_ask_depth_multiple=top5_ask_depth_multiple,
        vol24h_base=Decimal(str(ticker.get("vol24h") or "0")),
        vol24h_quote=Decimal(str(ticker.get("vol_ccy24h") or "0")),
        reference_quote_size=reference_quote_size,
        issues=tuple(issues),
    )


def render_market_observer_report(
    observations: list[MarketObservation],
    *,
    reference_quote_size: Decimal,
) -> str:
    lines = [
        "多市场观测",
        f"- 参考挂单金额(U)={decimal_to_str(reference_quote_size)}",
    ]
    if not observations:
        lines.append("- 未获取到市场观测结果")
        return "\n".join(lines)

    for observation in observations:
        issue_text = ",".join(observation.issues) if observation.issues else "ok"
        maker_text = decimal_to_str(observation.maker_fee) if observation.fee_available else "na"
        taker_text = decimal_to_str(observation.taker_fee) if observation.fee_available else "na"
        lines.extend(
            [
                f"- {observation.inst_id}: state={observation.inst_state} spread_ticks={decimal_to_str(observation.spread_ticks)} maker={maker_text} taker={taker_text} vol24h_quote={decimal_to_str(observation.vol24h_quote)}",
                (
                    f"  best_depth_x bid={decimal_to_str(observation.best_bid_depth_multiple)} "
                    f"ask={decimal_to_str(observation.best_ask_depth_multiple)} | "
                    f"top5_depth_x bid={decimal_to_str(observation.top5_bid_depth_multiple)} "
                    f"ask={decimal_to_str(observation.top5_ask_depth_multiple)} | "
                    f"issues={issue_text}"
                ),
            ]
        )
    return "\n".join(lines)


async def collect_market_observations(
    *,
    config: BotConfig,
    inst_ids: list[str] | tuple[str, ...] | None = None,
    reference_quote_size: Decimal | None = None,
    depth: int = 5,
) -> list[MarketObservation]:
    observed_inst_ids = list(inst_ids or DEFAULT_OBSERVED_MARKETS)
    reference_size = reference_quote_size if reference_quote_size is not None else config.trading.quote_size
    rest = BinanceRestClient(config.exchange) if config.exchange.name == "binance" else OKXRestClient(config.exchange)
    try:
        await rest.sync_time_offset()
        observations: list[MarketObservation] = []
        for inst_id in observed_inst_ids:
            instrument = await rest.fetch_instrument(inst_id, config.trading.inst_type)
            book = await rest.fetch_order_book(inst_id, depth)
            ticker = await rest.fetch_ticker(inst_id)
            fee: dict[str, Decimal | str] | None
            fee_issues: list[str] = []
            try:
                fee = await rest.fetch_trade_fee(config.trading.inst_type, inst_id)
            except ExchangeAPIError as exc:
                fee = None
                code = exc.code or "exchange_api_error"
                fee_issues.append(f"fee_fetch_failed:{code}")
                logger.warning("Market observer fee fetch failed for %s: %s", inst_id, exc)
            except Exception as exc:
                fee = None
                fee_issues.append(f"fee_fetch_failed:{type(exc).__name__}")
                logger.warning("Market observer fee fetch failed for %s: %s", inst_id, exc)
            observations.append(
                build_market_observation(
                    instrument=instrument,
                    book=book,
                    ticker=ticker,
                    fee=fee,
                    reference_quote_size=reference_size,
                    extra_issues=fee_issues,
                )
            )
        return observations
    finally:
        await rest.close()


async def render_market_observer(
    *,
    config: BotConfig,
    inst_ids: list[str] | tuple[str, ...] | None = None,
    reference_quote_size: Decimal | None = None,
    depth: int = 5,
) -> str:
    reference_size = reference_quote_size if reference_quote_size is not None else config.trading.quote_size
    observations = await collect_market_observations(
        config=config,
        inst_ids=inst_ids,
        reference_quote_size=reference_size,
        depth=depth,
    )
    return render_market_observer_report(observations, reference_quote_size=reference_size)
