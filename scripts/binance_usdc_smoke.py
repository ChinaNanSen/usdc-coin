from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import sys
import uuid
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.binance_private_stream import BinancePrivateUserStream
from src.binance_rest import BinanceRestClient
from src.config import load_config
from src.utils import quantize_down

logger = logging.getLogger("binance_usdc_smoke")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Binance USDC/USDT smoke test")
    parser.add_argument(
        "--config",
        type=str,
        default=str(ROOT / "config" / "config.binance.usdc.testnet.yaml"),
        help="Binance config path",
    )
    parser.add_argument(
        "--quote-size",
        type=str,
        default="10",
        help="Target quote notional for test order",
    )
    parser.add_argument(
        "--sell-price",
        type=str,
        default="1.0500",
        help="Far-away post-only sell price to avoid fills during smoke test",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=6.0,
        help="How long to wait for user stream callbacks",
    )
    return parser.parse_args()


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def main() -> None:
    args = parse_args()
    setup_logging()
    config = load_config(args.config)
    if config.exchange.name != "binance":
        raise SystemExit(f"Config is not a Binance config: {args.config}")

    rest = BinanceRestClient(config.exchange)
    user_events: list[tuple[str, dict]] = []

    async def on_order(payload: dict) -> None:
        user_events.append(("order", payload))

    async def on_account(payload: dict) -> None:
        user_events.append(("account", payload))

    async def on_reconnect(_stream: str) -> None:
        return None

    async def on_status(_stream: str, _connected: bool) -> None:
        return None

    async def on_error(stream: str, exc: Exception) -> None:
        logger.warning("private stream error | %s | %s", stream, exc)

    stream = BinancePrivateUserStream(
        url=config.exchange.private_ws_url,
        rest=rest,
        inst_id=config.trading.inst_id,
        on_order=on_order,
        on_account=on_account,
        on_reconnect=on_reconnect,
        on_status=on_status,
        on_error=on_error,
    )

    placed_order = None
    canceled_order = None
    try:
        await rest.sync_time_offset()
        instrument = await rest.fetch_instrument(config.trading.inst_id, config.trading.inst_type)
        ticker = await rest.fetch_ticker(config.trading.inst_id)
        balances = await rest.fetch_balances([config.trading.base_ccy, config.trading.quote_ccy])
        open_orders_before = await rest.list_pending_orders(config.trading.inst_id, config.trading.inst_type)
        fee = await rest.fetch_trade_fee(config.trading.inst_type, config.trading.inst_id)

        print("=== REST CHECK ===")
        print(json.dumps(
            {
                "exchange": config.exchange.name,
                "env": config.exchange.binance_env,
                "inst_id": config.trading.inst_id,
                "tick_size": str(instrument.tick_size),
                "lot_size": str(instrument.lot_size),
                "min_size": str(instrument.min_size),
                "bid_px": str(ticker["bid_px"]),
                "ask_px": str(ticker["ask_px"]),
                "fee": {"maker": str(fee["maker"]), "taker": str(fee["taker"])},
                "balances": {ccy: {"total": str(b.total), "available": str(b.available)} for ccy, b in balances.items()},
                "open_orders_before": len(open_orders_before),
            },
            ensure_ascii=False,
            indent=2,
        ))

        await stream.start()
        for _ in range(40):
            if stream.trade_ready():
                break
            await asyncio.sleep(0.25)
        if not stream.trade_ready():
            raise RuntimeError("Binance private user stream did not become ready")

        base_available = balances.get(config.trading.base_ccy)
        quote_available = balances.get(config.trading.quote_ccy)
        sell_price = Decimal(args.sell_price)
        buy_price = Decimal("0.9500")
        quote_size = Decimal(args.quote_size)
        sell_size = quantize_down(quote_size / sell_price, instrument.lot_size)
        buy_size = quantize_down(quote_size / buy_price, instrument.lot_size)

        selected_order = None
        if base_available and base_available.available >= max(sell_size, instrument.min_size):
            selected_order = {
                "side": "sell",
                "price": sell_price,
                "size": max(sell_size, instrument.min_size),
            }
        elif quote_available and quote_available.available >= quote_size:
            selected_order = {
                "side": "buy",
                "price": buy_price,
                "size": max(buy_size, instrument.min_size),
            }

        if selected_order is None:
            print("=== ORDER TEST SKIPPED ===")
            print("No sufficient USDC or USDT balance for a harmless post-only test order.")
        else:
            client_order_id = f"smoke{uuid.uuid4().hex[:18]}"
            placed_order = await rest.place_limit_order(
                inst_id=config.trading.inst_id,
                side=selected_order["side"],
                price=selected_order["price"],
                size=selected_order["size"],
                cl_ord_id=client_order_id,
                post_only=True,
            )
            print("=== PLACE OK ===")
            print(json.dumps(placed_order, ensure_ascii=False, indent=2))

            await asyncio.sleep(args.wait_seconds)

            canceled_order = await rest.cancel_order(
                inst_id=config.trading.inst_id,
                ord_id=str(placed_order.get("orderId") or "") or None,
                cl_ord_id=client_order_id,
            )
            print("=== CANCEL OK ===")
            print(json.dumps(canceled_order, ensure_ascii=False, indent=2))

            await asyncio.sleep(args.wait_seconds)

        print("=== USER STREAM EVENTS ===")
        print(json.dumps(user_events, ensure_ascii=False, indent=2))
    finally:
        with contextlib.suppress(Exception):
            if placed_order and not canceled_order:
                await rest.cancel_order(
                    inst_id=config.trading.inst_id,
                    ord_id=str(placed_order.get("orderId") or "") or None,
                    cl_ord_id=str(placed_order.get("clientOrderId") or "") or None,
                )
        with contextlib.suppress(Exception):
            await stream.stop()
        await rest.close()


if __name__ == "__main__":
    asyncio.run(main())
