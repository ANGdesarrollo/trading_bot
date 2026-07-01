from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from domain.entities.candle import Candle
from domain.entities.signal import Signal


class StrategyPort(ABC):
    @abstractmethod
    def evaluate(self, candles: Sequence[Candle]) -> Signal | None:
        """Return a Signal to act on the most recent closed candle, or None."""

    @property
    @abstractmethod
    def required_candles(self) -> int:
        """Minimum number of closed candles the strategy needs to decide."""
