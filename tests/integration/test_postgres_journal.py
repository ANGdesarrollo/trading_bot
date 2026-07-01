from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

DATABASE_URL = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")

_NOW = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)


def _make_entry(deal_id: str):
    from domain.entities.journal import JournalEntry
    return JournalEntry(
        deal_id=deal_id,
        symbol="EURUSD",
        direction="BUY",
        opened_at=_NOW,
        decision_candle_ts=_NOW,
        filled_price=1.10,
        sl_distance=0.0020,
        tp_distance=0.0020,
        atr_at_entry=0.0010,
        position_size=10000.0,
        bid_at_decision=None,
        ask_at_decision=None,
    )


def _make_result(deal_id: str):
    from domain.entities.journal import JournalResult
    return JournalResult(
        deal_id=deal_id,
        closed_at=_NOW,
        close_price=1.1019,
        close_source="TP",
        realized_pnl=19.0,
        fees=1.0,
        realized_r=0.9,
        reconciled_at=_NOW,
    )


@pytest.fixture
def pg_conn():
    import psycopg
    from infrastructure.postgres.migration_runner import run_migrations

    conn = psycopg.connect(DATABASE_URL)
    run_migrations(conn)
    conn.execute("SAVEPOINT test_start")
    yield conn
    try:
        conn.execute("ROLLBACK TO SAVEPOINT test_start")
    except Exception:
        conn.rollback()
        conn.execute("DELETE FROM trade_entries")
        conn.commit()
    conn.close()


def test_record_entry_then_open_entries_round_trip(pg_conn):
    from infrastructure.postgres.journal_adapter import PostgresTradeJournal
    adapter = PostgresTradeJournal(pg_conn)
    entry = _make_entry("D_INT_1")
    adapter.record_entry(entry)
    open_ = adapter.open_entries()
    assert any(e.deal_id == "D_INT_1" for e in open_)


def test_record_result_closes_entry_guard(pg_conn):
    from infrastructure.postgres.journal_adapter import PostgresTradeJournal
    adapter = PostgresTradeJournal(pg_conn)
    adapter.record_entry(_make_entry("D_INT_2"))
    adapter.record_result(_make_result("D_INT_2"))
    open_ = adapter.open_entries()
    assert not any(e.deal_id == "D_INT_2" for e in open_)


def test_double_reconcile_is_no_op(pg_conn):
    from infrastructure.postgres.journal_adapter import PostgresTradeJournal
    adapter = PostgresTradeJournal(pg_conn)
    adapter.record_entry(_make_entry("D_INT_3"))
    adapter.record_result(_make_result("D_INT_3"))
    adapter.record_result(_make_result("D_INT_3"))
    open_ = adapter.open_entries()
    assert not any(e.deal_id == "D_INT_3" for e in open_)
