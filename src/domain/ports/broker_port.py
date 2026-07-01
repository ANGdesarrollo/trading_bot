from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from domain.entities.candle import Candle
from domain.entities.order import OrderResult
from domain.entities.signal import Signal


class BrokerPort(ABC):
    @abstractmethod
    def recent_candles(self, symbol: str, count: int) -> Sequence[Candle]:
        """Return the last `count` CLOSED candles for `symbol`, oldest first."""

    @abstractmethod
    def open_position(self, symbol: str, signal: Signal, size: float) -> OrderResult:
        """Open a market position with stop loss and take profit attached."""

    @abstractmethod
    def has_open_position(self, symbol: str) -> bool:
        """Whether a position for `symbol` is already open (avoid stacking)."""
