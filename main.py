import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.audit_summary import render_audit_summary
from src.bot import TrendBot6
from src.config import load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trend Bot 6 - OKX USDC-USDT 做市机器人")
    default_config = Path(__file__).resolve().parent / "config" / "config.yaml"
    parser.add_argument("--config", type=str, default=str(default_config), help="配置文件路径")
    parser.add_argument("--mode", choices=["shadow", "live"], default=None, help="运行模式覆盖")
    parser.add_argument("--summary", action="store_true", help="输出中文运行摘要并退出")
    parser.add_argument("--run-id", type=str, default=None, help="配合 --summary 查看指定 run_id")
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
    config = load_config(args.config, mode_override=args.mode, validate_live_credentials=not args.summary)
    if args.summary:
        print(render_audit_summary(config, run_id=args.run_id))
        return
    bot = TrendBot6(config)
    await bot.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
