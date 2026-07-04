"""Manual portfolio rebalance CLI for eToro.

One run = one rebalance cycle:
  1. Fetch account equity + open positions from eToro
  2. Compute equal-weight targets over the 8-asset basket
  3. Compute delta orders
  4. Print the full order plan
  5. Place orders only when --execute is passed (default is dry-run)

Sells execute before buys so cash is freed first.

Usage:
    cd operator
    uv run python scripts/rebalance_etoro.py                  # dry-run
    uv run python scripts/rebalance_etoro.py --execute        # live (demo or real per ETORO_MODE)
    uv run python scripts/rebalance_etoro.py --min-order 50   # skip orders below $50
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import requests
from dotenv import load_dotenv

from application.rebalance_portfolio import RunPortfolioRebalanceUseCase
from config import load_etoro_config
from infrastructure.etoro.adapter import EToroPortfolioBrokerAdapter
from infrastructure.etoro.client import EToroClient


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="place orders (default: dry-run, prints plan only)",
    )
    parser.add_argument(
        "--min-order",
        type=float,
        default=None,
        help="skip orders with |delta| below this USD threshold (default: 10.0)",
    )
    return parser.parse_args()


def _print_summary(summary) -> None:
    mode_label = "EXECUTED" if summary.executed else "DRY-RUN"
    print(f"\n[{mode_label}] Equity: ${summary.equity:,.2f}")
    print(f"{'SYMBOL':<8} {'CURRENT':>12} {'TARGET':>12} {'DELTA':>12}  ACTION")
    print("-" * 56)
    for o in sorted(summary.orders, key=lambda x: x.delta):
        print(
            f"{o.symbol:<8} {o.current_usd:>12,.2f} {o.target_usd:>12,.2f} {o.delta:>12,.2f}  {o.action}"
        )


def main() -> int:
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    args = _parse_args()
    min_order = args.min_order if args.min_order is not None else 10.0
    etoro_cfg = load_etoro_config(min_order_usd=min_order)

    session = requests.Session()
    client = EToroClient(
        session=session,
        api_key=etoro_cfg.api_key,
        user_key=etoro_cfg.user_key,
        mode=etoro_cfg.mode,
    )
    adapter = EToroPortfolioBrokerAdapter(
        client=client,
        symbol_to_etoro_ticker=etoro_cfg.symbol_to_etoro_ticker,
    )
    use_case = RunPortfolioRebalanceUseCase(
        broker=adapter,
        min_order_usd=etoro_cfg.min_order_usd,
    )

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    log = logging.getLogger("rebalance_etoro")
    log.info("mode=%s execute=%s min_order=%.2f", etoro_cfg.mode, args.execute, min_order)

    summary = use_case.execute(execute=args.execute)
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
