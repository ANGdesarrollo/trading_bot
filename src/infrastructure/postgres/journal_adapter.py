from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from domain.entities.journal import JournalEntry, JournalResult
from domain.ports.trade_journal_port import TradeJournalPort

_INSERT_ENTRY = """
INSERT INTO trade_entries (
    deal_id, symbol, direction, opened_at, decision_candle_ts,
    filled_price, sl_distance, tp_distance, atr_at_entry, position_size,
    bid_at_decision, ask_at_decision, provider
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (deal_id) DO NOTHING
"""

_UPDATE_RESULT = """
UPDATE trade_entries
SET closed_at = %s,
    close_price = %s,
    close_source = %s,
    realized_pnl = %s,
    fees = %s,
    realized_r = %s,
    reconciled_at = now()
WHERE deal_id = %s
  AND reconciled_at IS NULL
"""

_SELECT_OPEN = """
SELECT deal_id, symbol, direction, opened_at, decision_candle_ts,
       filled_price, sl_distance, tp_distance, atr_at_entry, position_size,
       bid_at_decision, ask_at_decision, provider
FROM trade_entries
WHERE reconciled_at IS NULL
"""


def _row_to_entry(row: tuple) -> JournalEntry:
    (
        deal_id, symbol, direction, opened_at, decision_candle_ts,
        filled_price, sl_distance, tp_distance, atr_at_entry, position_size,
        bid_at_decision, ask_at_decision, provider,
    ) = row
    return JournalEntry(
        deal_id=deal_id,
        symbol=symbol,
        direction=direction,
        opened_at=opened_at,
        decision_candle_ts=decision_candle_ts,
        filled_price=filled_price,
        sl_distance=sl_distance,
        tp_distance=tp_distance,
        atr_at_entry=atr_at_entry,
        position_size=position_size,
        bid_at_decision=bid_at_decision,
        ask_at_decision=ask_at_decision,
        provider=provider,
    )


class PostgresTradeJournal(TradeJournalPort):
    def __init__(self, conn) -> None:
        self._conn = conn

    def record_entry(self, entry: JournalEntry) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_INSERT_ENTRY, (
                entry.deal_id, entry.symbol, entry.direction,
                entry.opened_at, entry.decision_candle_ts,
                entry.filled_price, entry.sl_distance, entry.tp_distance,
                entry.atr_at_entry, entry.position_size,
                entry.bid_at_decision, entry.ask_at_decision,
                entry.provider,
            ))
        self._conn.commit()

    def record_result(self, result: JournalResult) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_UPDATE_RESULT, (
                result.closed_at, result.close_price, result.close_source,
                result.realized_pnl, result.fees, result.realized_r,
                result.deal_id,
            ))
        self._conn.commit()

    def open_entries(self) -> Sequence[JournalEntry]:
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_OPEN)
            rows = cur.fetchall()
        return [_row_to_entry(row) for row in rows]
