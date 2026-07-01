from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

_UTC = timezone.utc
_T1 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=_UTC)
_T2 = datetime(2024, 1, 1, 12, 15, 0, tzinfo=_UTC)
_T3 = datetime(2024, 1, 1, 12, 30, 0, tzinfo=_UTC)


def _decimal_row(ts, open_bid, open_ask, high_bid=None, high_ask=None,
                 low_bid=None, low_ask=None, close_bid=None, close_ask=None):
    return (
        ts,
        Decimal(str(open_bid)), Decimal(str(high_bid or open_bid)),
        Decimal(str(low_bid or open_bid)), Decimal(str(close_bid or open_bid)),
        Decimal(str(open_ask)), Decimal(str(high_ask or open_ask)),
        Decimal(str(low_ask or open_ask)), Decimal(str(close_ask or open_ask)),
    )


class _FakeCursor:
    def __init__(self, rows: list = ()) -> None:
        self._rows = list(rows)
        self.executed: list[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql.strip(), params))

    def fetchall(self) -> list:
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _FakeConn:
    def __init__(self, rows: list = ()) -> None:
        self._cursor = _FakeCursor(rows=rows)
        self.committed = 0

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.committed += 1


def test_upsert_uses_on_conflict_do_update():
    from domain.entities.candle_row import CandleRow
    from infrastructure.postgres.candle_store import PostgresCandleStore

    row = CandleRow(
        epic="EURUSD", resolution="MINUTE_15", candle_start=_T1,
        open_bid=1.08, high_bid=1.09, low_bid=1.07, close_bid=1.085,
        open_ask=1.081, high_ask=1.091, low_ask=1.071, close_ask=1.086,
    )
    conn = _FakeConn()
    store = PostgresCandleStore(conn)
    store.upsert_candle(row)
    sqls = [s for s, _ in conn._cursor.executed]
    assert any("ON CONFLICT" in s and "DO UPDATE" in s for s in sqls)
    assert conn.committed >= 1


def test_recent_candles_mid_derivation_from_decimal_rows():
    from infrastructure.postgres.candle_store import PostgresCandleStore

    rows = [
        _decimal_row(_T3, open_bid=1.00, open_ask=1.20,
                     high_bid=1.02, high_ask=1.22,
                     low_bid=0.98, low_ask=1.18,
                     close_bid=1.01, close_ask=1.21),
        _decimal_row(_T2, open_bid=1.00, open_ask=1.20,
                     high_bid=1.02, high_ask=1.22,
                     low_bid=0.98, low_ask=1.18,
                     close_bid=1.01, close_ask=1.21),
        _decimal_row(_T1, open_bid=1.00, open_ask=1.20,
                     high_bid=1.02, high_ask=1.22,
                     low_bid=0.98, low_ask=1.18,
                     close_bid=1.01, close_ask=1.21),
    ]
    conn = _FakeConn(rows=rows)
    store = PostgresCandleStore(conn)
    candles = store.recent_candles(symbol="EURUSD", resolution="MINUTE_15", count=3)
    assert len(candles) == 3
    assert candles[0].open == pytest.approx(1.10)
    assert candles[0].high == pytest.approx(1.12)
    assert candles[0].low == pytest.approx(1.08)
    assert candles[0].close == pytest.approx(1.11)


def test_decimal_to_float_cast_probe():
    """Probe (c): psycopg v3 returns Decimal for NUMERIC — cast must produce float, not Decimal."""
    from infrastructure.postgres.candle_store import PostgresCandleStore

    rows = [_decimal_row(_T1, open_bid="1.0", open_ask="1.2")]
    conn = _FakeConn(rows=rows)
    store = PostgresCandleStore(conn)
    candles = store.recent_candles(symbol="EURUSD", resolution="MINUTE_15", count=1)
    assert len(candles) == 1
    assert type(candles[0].open) is float
    assert type(candles[0].high) is float
    assert type(candles[0].low) is float
    assert type(candles[0].close) is float


def test_recent_candles_ordering_oldest_first():
    from infrastructure.postgres.candle_store import PostgresCandleStore

    rows = [
        _decimal_row(_T3, open_bid=1.0, open_ask=1.2),
        _decimal_row(_T2, open_bid=1.0, open_ask=1.2),
        _decimal_row(_T1, open_bid=1.0, open_ask=1.2),
    ]
    conn = _FakeConn(rows=rows)
    store = PostgresCandleStore(conn)
    candles = store.recent_candles(symbol="EURUSD", resolution="MINUTE_15", count=3)
    timestamps = [c.timestamp for c in candles]
    assert timestamps == sorted(timestamps)


def test_recent_candles_filters_by_resolution():
    from infrastructure.postgres.candle_store import PostgresCandleStore

    conn = _FakeConn(rows=[_decimal_row(_T1, open_bid=1.0, open_ask=1.2)])
    store = PostgresCandleStore(conn)
    store.recent_candles(symbol="EURUSD", resolution="HOUR", count=3)

    sql, params = conn._cursor.executed[0]
    assert "resolution = %s" in sql
    assert params == ("capital", "EURUSD", "HOUR", 3)


def test_recent_candles_filters_by_provider():
    from infrastructure.postgres.candle_store import PostgresCandleStore

    conn = _FakeConn(rows=[_decimal_row(_T1, open_bid=1.0, open_ask=1.2)])
    store = PostgresCandleStore(conn)
    store.recent_candles(provider="ic_markets", symbol="EURUSD", resolution="HOUR", count=3)

    sql, params = conn._cursor.executed[0]
    assert "provider = %s" in sql
    assert params[0] == "ic_markets"


def test_last_candle_start_returns_none_when_no_rows():
    from infrastructure.postgres.candle_store import PostgresCandleStore

    conn = _FakeConn(rows=[None])
    store = PostgresCandleStore(conn)

    class _NoneConn:
        class _NullCursor:
            def execute(self, *a, **kw): pass
            def fetchone(self): return None
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def cursor(self): return self._NullCursor()
        def commit(self): pass

    store2 = PostgresCandleStore(_NoneConn())
    result = store2.last_candle_start(symbol="EURUSD", resolution="MINUTE_15")
    assert result is None
