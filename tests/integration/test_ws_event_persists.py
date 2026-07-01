from __future__ import annotations

import os

import pytest

DATABASE_URL = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")

_T_MS = 1782940500000  # 2026-07-01 21:30:00 UTC, as seen in the real WS logs


@pytest.fixture
def pg_conn():
    import psycopg
    from infrastructure.postgres.migration_runner import run_migrations

    conn = psycopg.connect(DATABASE_URL)
    run_migrations(conn)
    conn.execute("DELETE FROM candles WHERE epic = 'WSTEST'")
    conn.commit()
    yield conn
    conn.execute("DELETE FROM candles WHERE epic = 'WSTEST'")
    conn.commit()
    conn.close()


def _event(price_type: str) -> dict:
    return {
        "status": "OK",
        "destination": "ohlc.event",
        "payload": {
            "resolution": "MINUTE_15",
            "epic": "WSTEST",
            "type": "classic",
            "priceType": price_type,
            "t": _T_MS,
            "o": 1.1000 if price_type == "bid" else 1.1002,
            "h": 1.1010 if price_type == "bid" else 1.1012,
            "l": 1.0990 if price_type == "bid" else 1.0992,
            "c": 1.1005 if price_type == "bid" else 1.1007,
            "lastTradedVolume": 90,
        },
    }


def test_ws_bid_ask_pair_persists_to_db(pg_conn):
    from infrastructure.capital._pair_buffer import PairBuffer
    from infrastructure.postgres.candle_store import PostgresCandleStore

    store = PostgresCandleStore(pg_conn)
    buffer = PairBuffer(period_ms_map={("WSTEST", "MINUTE_15"): 900_000})

    buffer.on_event(_event("bid"), store.upsert_candle)
    buffer.on_event(_event("ask"), store.upsert_candle)

    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM candles WHERE epic = 'WSTEST' AND resolution = 'MINUTE_15'"
        )
        assert cur.fetchone()[0] == 1


def test_pair_split_across_buffer_reset_is_lost(pg_conn):
    """Reproduces the real bug: WS drops between bid and ask, so a NEW
    PairBuffer is created on reconnect and the buffered bid is lost."""
    from infrastructure.capital._pair_buffer import PairBuffer
    from infrastructure.postgres.candle_store import PostgresCandleStore

    store = PostgresCandleStore(pg_conn)

    buffer_before_drop = PairBuffer(period_ms_map={("WSTEST", "MINUTE_15"): 900_000})
    buffer_before_drop.on_event(_event("bid"), store.upsert_candle)

    # WS dropped -> _process_events restarts -> brand new buffer
    buffer_after_reconnect = PairBuffer(period_ms_map={("WSTEST", "MINUTE_15"): 900_000})
    buffer_after_reconnect.on_event(_event("ask"), store.upsert_candle)

    with pg_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM candles WHERE epic = 'WSTEST'")
        count = cur.fetchone()[0]

    # This documents the bug: the candle is NOT persisted (count == 0)
    assert count == 0
