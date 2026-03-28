from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.order_reason_attribution import analyze_reason_attribution
from src.utils import decimal_to_str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze PnL / turnover / markout by order reason bucket")
    parser.add_argument("--journal", type=str, required=True, help="journal.sim.jsonl or journal.live.jsonl path")
    parser.add_argument("--state", type=str, default=None, help="state snapshot path for markout-by-reason summary")
    parser.add_argument("--run-id", type=str, default=None, help="optional run_id override")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_id, summaries = analyze_reason_attribution(
        journal_path=args.journal,
        state_path=args.state,
        run_id=args.run_id,
    )
    print("Order Reason Attribution")
    print(f"- run_id={run_id or '-'}")
    if not summaries:
        print("- no data")
        return
    for item in summaries:
        print(
            "- "
            f"{item.bucket}: fills={item.fill_count} "
            f"turnover={decimal_to_str(item.turnover_quote)} "
            f"realized={decimal_to_str(item.realized_pnl_quote)} "
            f"per10k={decimal_to_str(item.realized_per_10k_turnover) if item.realized_per_10k_turnover is not None else 'na'} "
            f"markout300={decimal_to_str(item.avg_adverse_ticks_300ms) if item.avg_adverse_ticks_300ms is not None else 'na'} "
            f"markout1000={decimal_to_str(item.avg_adverse_ticks_1000ms) if item.avg_adverse_ticks_1000ms is not None else 'na'} "
            f"markout2000={decimal_to_str(item.avg_adverse_ticks_2000ms) if item.avg_adverse_ticks_2000ms is not None else 'na'}"
        )


if __name__ == "__main__":
    main()
