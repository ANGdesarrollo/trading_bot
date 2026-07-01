"""Unit tests for FadeStrategy (T-09).

Scenarios:
  3.1 — fewer than 128 candles -> None, no helpers called
  3.2 — 128 candles where bar n-2 is NOT aggressive -> None
  3.3 — 128 candles where bar n-2 IS aggressive -> valid Signal
  4.5 — zero/NaN ATR at the episode bar -> None
"""

import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

_BACKEND_ROOT = Path(__file__).parents[3] / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.append(str(_BACKEND_ROOT))

from domain.adapters.fade_strategy import FadeStrategy
from domain.entities.candle import Candle
from domain.entities.direction import Direction
from research.lib.fade_strategy import (
    ATR_PERIOD,
    MIN_DISP_ATR,
    MIN_STRAIGHTNESS,
    RR,
    SL_ATR_MULT,
    _aggressive_episodes,
    simulate_fades,
)
from research.lib.runs import compute_atr


def _make_candles(opens, highs, lows, closes) -> list[Candle]:
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        Candle(timestamp=ts, open=o, high=h, low=l, close=c)
        for o, h, l, c in zip(opens, highs, lows, closes)
    ]


def _flat_candles(n: int, price: float = 1.1000) -> list[Candle]:
    return _make_candles(
        opens=[price] * n,
        highs=[price + 0.0010] * n,
        lows=[price - 0.0010] * n,
        closes=[price] * n,
    )


def test_required_candles_is_128():
    assert FadeStrategy().required_candles == 128


def test_too_few_candles_returns_none():
    strategy = FadeStrategy()
    candles = _flat_candles(63)
    assert strategy.evaluate(candles) is None


def test_too_few_candles_does_not_call_helpers():
    strategy = FadeStrategy()
    candles = _flat_candles(63)
    with patch("domain.adapters.fade_strategy._aggressive_episodes") as mock_eps:
        with patch("domain.adapters.fade_strategy.compute_atr") as mock_atr:
            strategy.evaluate(candles)
            mock_eps.assert_not_called()
            mock_atr.assert_not_called()


def test_non_aggressive_bar_returns_none():
    strategy = FadeStrategy()
    candles = _flat_candles(128)
    result = strategy.evaluate(candles)
    assert result is None


def _build_aggressive_window():
    """Build 128 candles whose bar n-2 (index 126) is an aggressive down-run endpoint.

    Loads a known slice from the real EURUSD fixture where simulate_fades produces a
    trade, then takes the 128-candle live window (127-bar causal prefix + entry bar).
    Returns (candles, expected_direction, atr_at_endpoint, trade).
    """
    import pandas as pd

    csv_path = (
        Path(__file__).parents[3]
        / "backend"
        / "research"
        / "data"
        / "eurusd_15m.csv"
    )
    df = pd.read_csv(csv_path, parse_dates=["datetime"])
    df = df.rename(columns={"datetime": "datetime"})
    df = df.set_index("datetime").sort_index()
    df = df[["open", "high", "low", "close"]].dropna()

    trades = simulate_fades(df, cost_pct=0.0)
    if not trades:
        pytest.skip("No trades found in fixture — cannot build aggressive window")

    trade = next(
        (t for t in trades if t.run_end_idx - 126 >= 0),
        None,
    )
    if trade is None:
        pytest.skip("No trade has enough bars before it for a 128-candle window")

    run_end = trade.run_end_idx
    entry_i = trade.entry_idx
    assert entry_i == run_end + 1

    start = run_end - 126
    slice_df = df.iloc[start : run_end + 1]
    assert len(slice_df) == 127, f"Expected 127 rows but got {len(slice_df)}"

    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [
        Candle(
            timestamp=ts,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for _, row in slice_df.iterrows()
    ]

    entry_row = df.iloc[entry_i]
    entry_candle = Candle(
        timestamp=ts,
        open=float(entry_row["open"]),
        high=float(entry_row["high"]),
        low=float(entry_row["low"]),
        close=float(entry_row["close"]),
    )
    candles.append(entry_candle)
    assert len(candles) == 128

    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    atr = compute_atr(h, l, c, ATR_PERIOD)
    atr_at_endpoint = float(atr[run_end])

    return candles, trade.direction, atr_at_endpoint, trade


def test_aggressive_bar_produces_valid_signal():
    candles, bt_direction, _atr_e_full_series, trade = _build_aggressive_window()
    strategy = FadeStrategy()
    signal = strategy.evaluate(candles)

    assert signal is not None

    if bt_direction == 1:
        assert signal.direction is Direction.BUY
    else:
        assert signal.direction is Direction.SELL

    sl_dist = signal.sl_distance
    tp_dist = signal.tp_distance
    assert sl_dist > 0
    assert abs(tp_dist - RR * sl_dist) < 1e-9


def test_build_signal_returns_relative_distances():
    candles, _bt_direction, _atr_e, _trade = _build_aggressive_window()
    strategy = FadeStrategy()
    signal = strategy.evaluate(candles)

    assert signal is not None

    o, h, l, c = (
        np.array([cn.open for cn in candles[:-1]], dtype=float),
        np.array([cn.high for cn in candles[:-1]], dtype=float),
        np.array([cn.low for cn in candles[:-1]], dtype=float),
        np.array([cn.close for cn in candles[:-1]], dtype=float),
    )
    atr = compute_atr(h, l, c, ATR_PERIOD)
    atr_e = float(atr[-1])

    assert signal.sl_distance == pytest.approx(SL_ATR_MULT * atr_e)
    assert signal.tp_distance == pytest.approx(RR * signal.sl_distance)


def test_zero_atr_returns_none(monkeypatch):
    """If atr at the episode bar is 0 or NaN, evaluate must return None."""
    import pandas as pd

    csv_path = (
        Path(__file__).parents[3]
        / "backend"
        / "research"
        / "data"
        / "eurusd_15m.csv"
    )
    df = pd.read_csv(csv_path, parse_dates=["datetime"])
    df = df.rename(columns={"datetime": "datetime"})
    df = df.set_index("datetime").sort_index()
    df = df[["open", "high", "low", "close"]].dropna()
    trades = simulate_fades(df, cost_pct=0.0)
    if not trades:
        pytest.skip("No trades")

    trade = next((t for t in trades if t.run_end_idx - 126 >= 0), None)
    if trade is None:
        pytest.skip("Not enough bars")

    run_end = trade.run_end_idx
    start = run_end - 126
    slice_df = df.iloc[start : run_end + 2]
    ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = [
        Candle(
            timestamp=ts,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for _, row in slice_df.iterrows()
    ]
    assert len(candles) == 128

    zero_atr = np.zeros(128)

    import domain.adapters.fade_strategy as fs_mod

    monkeypatch.setattr(fs_mod, "compute_atr", lambda *a, **kw: zero_atr)
    strategy = FadeStrategy()
    assert strategy.evaluate(candles) is None
