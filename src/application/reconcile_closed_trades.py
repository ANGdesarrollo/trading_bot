from __future__ import annotations

import logging
from datetime import datetime, timezone

from domain.entities.journal import JournalResult
from domain.ports.trade_history_port import TradeHistoryPort
from domain.ports.trade_journal_port import TradeJournalPort

logger = logging.getLogger(__name__)


def compute_realized_r(pnl: float, fees: float, sl_distance: float, position_size: float) -> float:
    risk_currency = sl_distance * position_size
    return (pnl - fees) / risk_currency


class ReconcileClosedTradesUseCase:
    def __init__(self, journal: TradeJournalPort, history: TradeHistoryPort) -> None:
        self._journal = journal
        self._history = history

    def execute(self) -> None:
        for entry in self._journal.open_entries():
            try:
                closed = self._history.closed_trade(entry.deal_id, entry.opened_at)
                if closed is None:
                    continue
                realized_r = compute_realized_r(
                    closed.realized_pnl, closed.fees,
                    entry.sl_distance, entry.position_size,
                )
                self._journal.record_result(JournalResult(
                    deal_id=entry.deal_id,
                    closed_at=closed.closed_at,
                    close_price=closed.close_price,
                    close_source=closed.close_source,
                    realized_pnl=closed.realized_pnl,
                    fees=closed.fees,
                    realized_r=realized_r,
                    reconciled_at=datetime.now(timezone.utc),
                ))
            except Exception:
                logger.exception("reconcile failed for deal_id=%s", entry.deal_id)
