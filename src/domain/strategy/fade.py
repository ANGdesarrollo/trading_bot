# VENDORED FROM: backend/research/lib/fade_strategy.py @ 67077c0271af0efd9cd167a1791f20d50c68bb2c (2026-07-01)
# Frozen strategy — DO NOT EDIT. Re-vendor via SYNC.md when parent research changes constants.
# Internal imports repointed research.lib.* -> domain.strategy.* (relative); no logic change.
"""Aggressive-exhaustion fade strategy — single source of truth.

This is the strategy validated in-sample on EURUSD (E[R] +0.13, 14/14 years
positive, beats random p95 at the 100th percentile). The SAME function powers
both the research backtest and the chart/API so the painted trades are exactly
the trades that were validated — no divergence between what we test and what we show.

Event: an AGGRESSIVE directional run (L bars, dir>=threshold, net displacement
and straightness above the aggressiveness gate). We FADE it: enter the next bar
open opposite to the run, SL at 2*ATR, TP at RR*SL, time-stop at TIME_STOP bars.
Pessimistic same-bar resolution: if SL and TP both touch in one bar -> SL.
"""
from __future__ import annotations

from typing import NamedTuple

import numpy as np

from .runs import compute_atr, identify_runs
from .trajectory import extract_trajectory_features

L_FROZEN = 32
DIR_THRESHOLD_FROZEN = 0.60
ATR_PERIOD = 14
MIN_DISP_ATR = 5.6
MIN_STRAIGHTNESS = 0.37
SL_ATR_MULT = 2.0
RR = 1.0
TIME_STOP_BARS = 48


class FadeTrade(NamedTuple):
    run_end_idx: int
    entry_idx: int
    exit_idx: int
    direction: int          # +1 long fade (faded a down-run), -1 short fade
    entry_price: float
    sl_price: float
    tp_price: float
    exit_price: float
    outcome: str            # "tp" | "sl" | "timeout"
    r_multiple: float       # net of cost


def _aggressive_episodes(df, o, h, l, c, atr):
    records = identify_runs(df, c, atr, L_FROZEN, DIR_THRESHOLD_FROZEN)
    aggressive = []
    for r in records:
        sl = atr[r.bar_idx]
        if sl <= 0 or np.isnan(sl):
            continue
        feats, _ = extract_trajectory_features(
            o, h, l, c, atr, r.bar_idx, r.direction, L_FROZEN, float(sl)
        )
        if feats is None:
            continue
        if feats["total_disp_atr"] >= MIN_DISP_ATR and feats["straightness"] >= MIN_STRAIGHTNESS:
            aggressive.append(r)

    episodes = []
    if aggressive:
        cur = aggressive[0]
        for r in aggressive[1:]:
            if r.direction == cur.direction and r.bar_idx == cur.bar_idx + 1:
                cur = r
            else:
                episodes.append(cur)
                cur = r
        episodes.append(cur)
    return episodes


def simulate_fades(df, cost_pct: float) -> list[FadeTrade]:
    """Run the fade strategy over df. cost_pct is round-trip fraction (e.g. 0.0001
    for ~1 pip EURUSD relative scale is handled by caller; here cost is fraction
    of entry price applied symmetrically as an R deduction)."""
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    n = len(c)
    atr = compute_atr(h, l, c, ATR_PERIOD)

    episodes = _aggressive_episodes(df, o, h, l, c, atr)

    trades: list[FadeTrade] = []
    last_exit = -1
    for r in episodes:
        entry_i = r.bar_idx + 1
        if entry_i <= last_exit or entry_i + 1 >= n:
            continue
        atr_e = atr[r.bar_idx]
        if atr_e <= 0 or np.isnan(atr_e):
            continue

        entry = o[entry_i]
        fade = -r.direction
        sl_dist = SL_ATR_MULT * atr_e
        tp_dist = RR * sl_dist
        cost_r = (cost_pct * entry) / sl_dist

        if fade == 1:
            sl_px, tp_px = entry - sl_dist, entry + tp_dist
        else:
            sl_px, tp_px = entry + sl_dist, entry - tp_dist

        outcome = "timeout"
        exit_i = min(entry_i + TIME_STOP_BARS, n - 1)
        r_mult = 0.0
        for j in range(entry_i + 1, min(entry_i + 1 + TIME_STOP_BARS, n)):
            hit_sl = (l[j] <= sl_px) if fade == 1 else (h[j] >= sl_px)
            hit_tp = (h[j] >= tp_px) if fade == 1 else (l[j] <= tp_px)
            if hit_sl:
                outcome, exit_i, r_mult = "sl", j, -1.0 - cost_r
                break
            if hit_tp:
                outcome, exit_i, r_mult = "tp", j, RR - cost_r
                break
        else:
            exit_px = c[exit_i]
            move = (exit_px - entry) if fade == 1 else (entry - exit_px)
            r_mult = move / sl_dist - cost_r

        exit_price = (
            sl_px if outcome == "sl" else tp_px if outcome == "tp" else c[exit_i]
        )
        trades.append(FadeTrade(
            run_end_idx=r.bar_idx, entry_idx=entry_i, exit_idx=exit_i,
            direction=fade, entry_price=float(entry),
            sl_price=float(sl_px), tp_price=float(tp_px),
            exit_price=float(exit_price), outcome=outcome,
            r_multiple=float(r_mult),
        ))
        last_exit = exit_i
    return trades
