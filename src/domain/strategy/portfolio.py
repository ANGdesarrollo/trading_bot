# VENDORED FROM: backend/scripts/rebalance_portfolio.py @ 49f356e (2026-07-03)
# Frozen strategy — DO NOT EDIT. Re-vendor via SYNC.md when parent research changes.
# CLI entry point (argparse main) stripped; pure domain logic only.
"""Equal-weight rebalance logic for the 8-asset investable basket (H28/H34).

Pure 1/N — the H34 comparison showed no risk-based challenger beats equal weight
(inverse-vol alpha t=+0.80, cap-1 vol-target t=+0.51, both below the 1.5 bar).
"""
from __future__ import annotations

BASKET = ("SPY", "QQQ", "IWM", "EEM", "EFA", "TLT", "XAUUSD", "BTCUSD")


def target_allocations(equity: float) -> dict[str, float]:
    if equity <= 0:
        raise ValueError(f"equity must be positive, got {equity}")
    per_asset = equity / len(BASKET)
    return {symbol: per_asset for symbol in BASKET}


def rebalance_orders(positions: dict[str, float], cash: float = 0.0) -> dict[str, float]:
    unknown = sorted(set(positions) - set(BASKET))
    if unknown:
        raise ValueError(f"symbols outside the basket: {', '.join(unknown)}")
    equity = sum(positions.values()) + cash
    targets = target_allocations(equity)
    return {symbol: targets[symbol] - positions.get(symbol, 0.0) for symbol in BASKET}


def parse_positions(raw: str) -> dict[str, float]:
    positions = {}
    for entry in raw.split(","):
        symbol, sep, value = entry.partition("=")
        if not sep:
            raise ValueError(f"expected SYMBOL=VALUE, got {entry!r}")
        positions[symbol.strip().upper()] = float(value)
    return positions
