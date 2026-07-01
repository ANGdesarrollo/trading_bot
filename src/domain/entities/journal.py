from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class JournalEntry:
    deal_id: str
    symbol: str
    direction: str
    opened_at: datetime
    decision_candle_ts: datetime
    filled_price: float
    sl_distance: float
    tp_distance: float
    atr_at_entry: float
    position_size: float
    bid_at_decision: float | None
    ask_at_decision: float | None
    provider: str = "capital"


@dataclass(frozen=True, slots=True)
class JournalResult:
    deal_id: str
    closed_at: datetime
    close_price: float
    close_source: str
    realized_pnl: float
    fees: float
    realized_r: float
    reconciled_at: datetime


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    deal_id: str
    closed_at: datetime
    close_price: float
    close_source: str
    realized_pnl: float
    fees: float
