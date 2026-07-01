from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest

DATABASE_URL = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")

_T1 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_T2 = datetime(2024, 1, 1, 12, 15, 0, tzinfo=timezone.utc)
_T3 = datetime(2024, 1, 1, 12, 30, 0, tzinfo=timezone.utc)
_T4 = datetime(2024, 1, 1, 12, 45, 0, tzinfo=timezone.utc)
_T5 = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def pg_conn():
    import psycopg
    from infrastructure.postgres.migration_runner import run_migrations

    conn = psycopg.connect(DATABASE_URL)
    run_migrations(conn)
    conn.execute("SAVEPOINT test_start")
    yield conn
    conn.execute("ROLLBACK TO SAVEPOINT test_start")
    conn.close()


def _make_row(candle_start, *, open_bid=1.08, high_bid=1.09, low_bid=1.07, close_bid=1.085,
              open_ask=1.081, high_ask=1.091, low_ask=1.071, close_ask=1.086,
              epic="EURUSD", resolution="MINUTE_15"):
    from domain.entities.candle_row import CandleRow
    return CandleRow(
        epic=epic, resolution=resolution, candle_start=candle_start,
        open_bid=open_bid, high_bid=high_bid, low_bid=low_bid, close_bid=close_bid,
        open_ask=open_ask, high_ask=high_ask, low_ask=low_ask, close_ask=close_ask,
    )


def test_upsert_twice_same_key_second_call_wins(pg_conn):
    from infrastructure.postgres.candle_store import PostgresCandleStore
    store = PostgresCandleStore(pg_conn)
    row1 = _make_row(_T1, open_bid=1.00)
    row2 = _make_row(_T1, open_bid=2.00)
    store.upsert_candle(row1)
    store.upsert_candle(row2)
    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*), AVG(open_bid) FROM candles WHERE epic='EURUSD' AND candle_start=%s", (_T1,))
        count, avg = cur.fetchone()
    assert count == 1
    assert float(avg) == pytest.approx(2.00)


def test_recent_candles_returns_three_oldest_first_mid_derived(pg_conn):
    from infrastructure.postgres.candle_store import PostgresCandleStore
    store = PostgresCandleStore(pg_conn)
    for ts in [_T1, _T2, _T3, _T4, _T5]:
        store.upsert_candle(_make_row(ts, open_bid=1.00, open_ask=1.20))
    candles = store.recent_candles("EURUSD", 3)
    assert len(candles) == 3
    assert candles[0].timestamp == _T3
    assert candles[1].timestamp == _T4
    assert candles[2].timestamp == _T5
    assert candles[0].open == pytest.approx(1.10)


def test_recent_candles_respects_count_cap(pg_conn):
    from infrastructure.postgres.candle_store import PostgresCandleStore
    store = PostgresCandleStore(pg_conn)
    for i in range(10):
        ts = datetime(2024, 1, 1, 10, i * 15, 0, tzinfo=timezone.utc)
        store.upsert_candle(_make_row(ts))
    candles = store.recent_candles("EURUSD", 3)
    assert len(candles) == 3


def test_recent_candles_empty_table_returns_empty(pg_conn):
    from infrastructure.postgres.candle_store import PostgresCandleStore
    store = PostgresCandleStore(pg_conn)
    candles = store.recent_candles("EURUSD", 10)
    assert list(candles) == []


def test_last_candle_start_empty_table_returns_none(pg_conn):
    from infrastructure.postgres.candle_store import PostgresCandleStore
    store = PostgresCandleStore(pg_conn)
    result = store.last_candle_start("EURUSD", "MINUTE_15")
    assert result is None


def test_last_candle_start_returns_newest(pg_conn):
    from infrastructure.postgres.candle_store import PostgresCandleStore
    store = PostgresCandleStore(pg_conn)
    for ts in [_T1, _T2, _T3]:
        store.upsert_candle(_make_row(ts))
    result = store.last_candle_start("EURUSD", "MINUTE_15")
    assert result == _T3
    assert result.tzinfo is not None
