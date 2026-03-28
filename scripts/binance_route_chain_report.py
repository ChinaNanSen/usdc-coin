from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.binance_route_chain_report import render_binance_route_chain_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the USD1 route-chain report for Binance")
    parser.add_argument("--main-state", type=str, required=True)
    parser.add_argument("--main-journal", type=str, required=True)
    parser.add_argument("--release-state", type=str, required=True)
    parser.add_argument("--release-journal", type=str, required=True)
    parser.add_argument("--route-ledger", type=str, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(
        render_binance_route_chain_report(
            main_state_path=args.main_state,
            main_journal_path=args.main_journal,
            release_state_path=args.release_state,
            release_journal_path=args.release_journal,
            route_ledger_path=args.route_ledger,
        )
    )


if __name__ == "__main__":
    main()
