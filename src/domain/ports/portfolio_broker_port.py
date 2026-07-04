from __future__ import annotations

from abc import ABC, abstractmethod


class PortfolioBrokerPort(ABC):
    @abstractmethod
    def available_cash(self) -> float:
        """Available cash in USD ready for new positions."""

    @abstractmethod
    def positions(self) -> dict[str, float]:
        """Current market value in USD per basket symbol (domain symbols)."""

    @abstractmethod
    def buy(self, symbol: str, amount_usd: float) -> str:
        """Open or increase a position by amount_usd. Returns order/position id."""

    @abstractmethod
    def sell(self, symbol: str, amount_usd: float) -> str:
        """Close or reduce a position by amount_usd. Returns order/position id."""
