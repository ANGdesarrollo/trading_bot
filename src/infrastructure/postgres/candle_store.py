from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from domain.entities.candle import Candle
from domain.entities.candle_row import CandleRow
from domain.ports.candle_store_port import CandleStorePort

_UPSERT = """
INSERT INTO candles (
    provider, epic, resolution, candle_start,
    open_bid, high_bid, low_bid, close_bid,
    open_ask, high_ask, low_ask, close_ask
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (provider, epic, resolution, candle_start) DO UPDATE SET
    open_bid  = EXCLUDED.open_bid,
    high_bid  = EXCLUDED.high_bid,
    low_bid   = EXCLUDED.low_bid,
    close_bid = EXCLUDED.close_bid,
    open_ask  = EXCLUDED.open_ask,
    high_ask  = EXCLUDED.high_ask,
    low_ask   = EXCLUDED.low_ask,
    close_ask = EXCLUDED.close_ask
"""

_SELECT_RECENT = """
SELECT candle_start,
       open_bid, high_bid, low_bid, close_bid,
       open_ask, high_ask, low_ask, close_ask
FROM candles
WHERE epic = %s AND resolution = %s
ORDER BY candle_start DESC
LIMIT %s
"""

_SELECT_LAST_START = """
SELECT candle_start
FROM candles
WHERE epic = %s AND resolution = %s
ORDER BY candle_start DESC
LIMIT 1
"""


def _row_to_candle(row: tuple) -> Candle:
    ts, ob, hb, lb, cb, oa, ha, la, ca = row
    return Candle(
        timestamp=ts,
        open=float((ob + oa) / 2),
        high=float((hb + ha) / 2),
        low=float((lb + la) / 2),
        close=float((cb + ca) / 2),
    )


class PostgresCandleStore(CandleStorePort):
    def __init__(self, conn) -> None:
        self._conn = conn

    def upsert_candle(self, row: CandleRow) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_UPSERT, (
                row.provider, row.epic, row.resolution, row.candle_start,
                row.open_bid, row.high_bid, row.low_bid, row.close_bid,
                row.open_ask, row.high_ask, row.low_ask, row.close_ask,
            ))
        self._conn.commit()

    def recent_candles(self, symbol: str, resolution: str, count: int) -> Sequence[Candle]:
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_RECENT, (symbol, resolution, count))
            rows = cur.fetchall()
        return [_row_to_candle(row) for row in reversed(rows)]

    def last_candle_start(self, symbol: str, resolution: str) -> datetime | None:
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_LAST_START, (symbol, resolution))
            row = cur.fetchone()
        if row is None:
            return None
        return row[0]
