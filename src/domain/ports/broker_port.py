from __future__ import annotations

from abc import ABC, abstractmethod

from domain.entities.order import OrderResult
from domain.entities.signal import Signal


class BrokerPort(ABC):
    @abstractmethod
    def open_position(self, symbol: str, signal: Signal, size: float) -> OrderResult:
        """Open a market position with stop loss and take profit attached."""

    @abstractmethod
    def has_open_position(self, symbol: str) -> bool:
        """Whether a position for `symbol` is already open (avoid stacking)."""
