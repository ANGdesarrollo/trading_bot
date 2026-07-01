from __future__ import annotations

from datetime import datetime

from domain.entities.journal import ClosedTrade
from domain.ports.trade_history_port import TradeHistoryPort


class FakeTradeHistoryPort(TradeHistoryPort):
    def __init__(self, responses: dict[str, ClosedTrade | None | Exception] | None = None) -> None:
        self.responses: dict[str, ClosedTrade | None | Exception] = responses or {}

    def closed_trade(self, deal_id: str, opened_at: datetime) -> ClosedTrade | None:
        value = self.responses.get(deal_id)
        if isinstance(value, Exception):
            raise value
        return value
