"""FadeStrategy — bridges the frozen research lib to StrategyPort.

Coupling note: this adapter intentionally imports from `research.lib.*` in the
backend project. That cross-project import is the anti-drift guarantee: the live
path calls the IDENTICAL code the backtest validated. The sys.path shim below
keeps this coupling isolated to one module; nothing else in capital_integration
should touch sys.path.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from math import isnan
from pathlib import Path

import numpy as np
import pandas as pd

_BACKEND_ROOT = Path(__file__).parents[4] / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.append(str(_BACKEND_ROOT))

from research.lib.fade_strategy import (
    ATR_PERIOD,
    RR,
    SL_ATR_MULT,
    _aggressive_episodes,
)
from research.lib.runs import compute_atr

from domain.entities.candle import Candle
from domain.entities.direction import Direction
from domain.entities.signal import Signal
from domain.ports.strategy_port import StrategyPort

_REQUIRED_CANDLES = 128


class FadeStrategy(StrategyPort):
    @property
    def required_candles(self) -> int:
        return _REQUIRED_CANDLES

    def evaluate(self, candles: Sequence[Candle]) -> Signal | None:
        if len(candles) < _REQUIRED_CANDLES:
            return None

        o, h, l, c = _to_numpy_arrays(candles)

        # Episode detection runs over candles[0..n-2] (the run-endpoint slice),
        # exactly as the backtest sees the window at bar run_end. Candles[n-1] is
        # the entry bar — it is not fed to the episode detector to avoid ATR
        # divergence on the boundary bar.
        endpoint = len(candles) - 2
        o_ep, h_ep, l_ep, c_ep = o[: endpoint + 1], h[: endpoint + 1], l[: endpoint + 1], c[: endpoint + 1]
        df_ep = pd.DataFrame({"open": o_ep, "high": h_ep, "low": l_ep, "close": c_ep})
        atr_ep = compute_atr(h_ep, l_ep, c_ep, ATR_PERIOD)

        episodes = _aggressive_episodes(df_ep, o_ep, h_ep, l_ep, c_ep, atr_ep)
        matching = [ep for ep in episodes if ep.bar_idx == endpoint]
        if not matching:
            return None

        episode = matching[0]
        atr_e = float(atr_ep[endpoint])
        if atr_e <= 0 or isnan(atr_e):
            return None

        return _build_signal(episode, atr_e)


def _to_numpy_arrays(
    candles: Sequence[Candle],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    o = np.array([c.open for c in candles], dtype=float)
    h = np.array([c.high for c in candles], dtype=float)
    l = np.array([c.low for c in candles], dtype=float)
    c = np.array([c.close for c in candles], dtype=float)
    return o, h, l, c


def _build_signal(episode, atr_e: float) -> Signal:
    fade = -episode.direction
    sl_dist = SL_ATR_MULT * atr_e
    tp_dist = RR * sl_dist
    direction = Direction.BUY if fade == 1 else Direction.SELL
    return Signal(direction=direction, sl_distance=sl_dist, tp_distance=tp_dist)
