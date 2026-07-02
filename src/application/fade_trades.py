from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from domain.entities.candle import Candle
from domain.strategy.fade import ATR_PERIOD, L_FROZEN, simulate_fades

_DEFAULT_COST_PCT = 0.0001
_MIN_CANDLES_FOR_STRATEGY = ATR_PERIOD + L_FROZEN

_COST_PCT_BY_SYMBOL: dict[str, float] = {
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "USDJPY": 0.0001,
    "AUDUSD": 0.0001,
    "USDCAD": 0.0001,
    "USDCHF": 0.0001,
}


def build_fade_trades_response(
    candles: Sequence[Candle], *, symbol: str, timeframe: str
) -> dict:
    if not candles:
        return {
            "meta": {
                "symbol": symbol,
                "timeframe": timeframe,
                "trades": 0,
                "win_rate": 0.0,
                "total_r": 0.0,
                "expectancy_r": 0.0,
                "cost_pct": _COST_PCT_BY_SYMBOL.get(symbol, _DEFAULT_COST_PCT),
            },
            "trades": [],
        }

    cost_pct = _COST_PCT_BY_SYMBOL.get(symbol, _DEFAULT_COST_PCT)

    if len(candles) < _MIN_CANDLES_FOR_STRATEGY:
        return {
            "meta": {
                "symbol": symbol,
                "timeframe": timeframe,
                "trades": 0,
                "win_rate": 0.0,
                "total_r": 0.0,
                "expectancy_r": 0.0,
                "cost_pct": cost_pct,
            },
            "trades": [],
        }

    df = pd.DataFrame(
        {"open": c.open, "high": c.high, "low": c.low, "close": c.close}
        for c in candles
    )

    raw_trades = simulate_fades(df, cost_pct)

    serialized = [
        {
            "entry_time": candles[t.entry_idx].timestamp.isoformat(),
            "exit_time": candles[t.exit_idx].timestamp.isoformat(),
            "direction": t.direction,
            "entry_price": t.entry_price,
            "sl_price": t.sl_price,
            "tp_price": t.tp_price,
            "exit_price": t.exit_price,
            "outcome": t.outcome,
            "r_multiple": round(t.r_multiple, 3),
        }
        for t in raw_trades
    ]

    n = len(raw_trades)
    total_r = sum(t.r_multiple for t in raw_trades)

    return {
        "meta": {
            "symbol": symbol,
            "timeframe": timeframe,
            "trades": n,
            "win_rate": sum(1 for t in raw_trades if t.outcome == "tp") / n if n else 0.0,
            "total_r": total_r,
            "expectancy_r": total_r / n if n else 0.0,
            "cost_pct": cost_pct,
        },
        "trades": serialized,
    }
