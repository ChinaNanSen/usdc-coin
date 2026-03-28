from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize OKX vs Binance USDC/USDT read-only arb scan JSONL")
    parser.add_argument("--jsonl", type=str, default="data/arb/okx_binance_usdc_scan.jsonl")
    parser.add_argument("--positive-threshold-bp", type=str, default="0")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = Path(args.jsonl)
    threshold = Decimal(args.positive_threshold_bp)
    if not path.exists():
        raise SystemExit(f"JSONL file not found: {path}")

    total = 0
    positive = 0
    longest_positive_streak = 0
    current_streak = 0
    max_notional = Decimal("0")
    best_edge = None
    latest = None

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except Exception:
                continue
            total += 1
            latest = record
            opportunities = record.get("opportunities") or []
            max_edge_this_round = max((Decimal(str(item.get("net_edge_bp") or "0")) for item in opportunities), default=Decimal("0"))
            max_notional_this_round = max((Decimal(str(item.get("max_quote_notional") or "0")) for item in opportunities), default=Decimal("0"))
            if best_edge is None or max_edge_this_round > best_edge:
                best_edge = max_edge_this_round
            if max_notional_this_round > max_notional:
                max_notional = max_notional_this_round
            if max_edge_this_round > threshold:
                positive += 1
                current_streak += 1
                longest_positive_streak = max(longest_positive_streak, current_streak)
            else:
                current_streak = 0

    print("OKX vs Binance USDC/USDT Arb Summary")
    print(f"- samples={total}")
    print(f"- positive_samples={positive}")
    print(f"- positive_ratio={Decimal(positive) / Decimal(total) if total else Decimal('0')}")
    print(f"- longest_positive_streak={longest_positive_streak}")
    print(f"- max_positive_net_edge_bp={best_edge if best_edge is not None else Decimal('0')}")
    print(f"- max_quote_notional={max_notional}")
    if latest is not None:
        print(f"- latest_ts_ms={latest.get('ts_ms')}")


if __name__ == "__main__":
    main()
