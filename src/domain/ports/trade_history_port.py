from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from domain.entities.journal import ClosedTrade


class TradeHistoryPort(ABC):
    @abstractmethod
    def closed_trade(self, deal_id: str, opened_at: datetime) -> ClosedTrade | None: ...
