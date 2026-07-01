# VENDORED FROM: backend/research/lib/runs.py @ 67077c0271af0efd9cd167a1791f20d50c68bb2c (2026-07-01)
# Frozen strategy — DO NOT EDIT. Re-vendor via SYNC.md when parent research changes constants.
"""Shared run-detection primitives for H13 research and API consumption."""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
import pandas as pd

EURUSD_PIP = 0.0001


class RunRecord(NamedTuple):
    bar_idx: int
    direction: int            # +1 up / -1 down
    run_length: int
    directionality: float
    displacement_pip: float
    displacement_atr: float
    # First bar against the run after signal bar; NaN if none found within 48 bars
    counter_bar_idx: float


def compute_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1))),
    )
    tr[0] = high[0] - low[0]
    atr = np.full(len(close), np.nan)
    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, len(close)):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def identify_runs(
    df: pd.DataFrame,
    close: np.ndarray,
    atr: np.ndarray,
    L: int,
    dir_threshold: float,
    pip: float = EURUSD_PIP,
) -> list[RunRecord]:
    """
    Identify directional runs of exactly L bars at each bar i (strictly causal, no lookahead).

    A run of length L ending at bar i:
    - window = close[i-L .. i], L bar-returns
    - direction = sign of net displacement
    - directionality = fraction of bar-returns in the direction
    - qualifies when directionality >= dir_threshold

    One record per qualifying bar (sliding window, not event-based deduplication).
    """
    n = len(close)
    burn = max(L, 14)
    records: list[RunRecord] = []

    bar_returns = np.diff(close)

    for i in range(burn, n):
        window_ret = np.diff(close[i - L: i + 1])
        net_disp = close[i] - close[i - L]
        direction = int(np.sign(net_disp))
        if direction == 0:
            continue

        dir_frac = np.sum(np.sign(window_ret) == direction) / L
        if dir_frac < dir_threshold:
            continue

        if atr[i] <= 0 or np.isnan(atr[i]):
            continue

        disp_pip = abs(net_disp) / pip
        disp_atr = abs(net_disp) / atr[i]

        counter_idx = np.nan
        for k in range(i + 1, min(i + 49, n - 1)):
            if int(np.sign(bar_returns[k])) == -direction:
                counter_idx = float(k)
                break

        records.append(RunRecord(
            bar_idx=i,
            direction=direction,
            run_length=L,
            directionality=dir_frac,
            displacement_pip=disp_pip,
            displacement_atr=disp_atr,
            counter_bar_idx=counter_idx,
        ))

    return records
