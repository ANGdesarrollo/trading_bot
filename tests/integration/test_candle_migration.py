from __future__ import annotations

import os

import pytest

DATABASE_URL = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")


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


def test_candles_table_exists_after_migration(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'candles'"
        )
        count = cur.fetchone()[0]
    assert count == 1


def test_candles_table_has_required_columns(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'candles' ORDER BY column_name"
        )
        columns = {row[0] for row in cur.fetchall()}
    required = {
        "epic", "resolution", "candle_start",
        "open_bid", "high_bid", "low_bid", "close_bid",
        "open_ask", "high_ask", "low_ask", "close_ask",
    }
    assert required.issubset(columns)


def test_migration_recorded_in_schema_migrations(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations")
        versions = {row[0] for row in cur.fetchall()}
    assert "002_create_candles.sql" in versions


def test_unique_constraint_exists(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'candles' AND c.contype = 'u'
            """
        )
        count = cur.fetchone()[0]
    assert count >= 1


# ---------------------------------------------------------------------------
# Migration 003: provider column on candles
# ---------------------------------------------------------------------------

def test_candles_has_provider_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'candles' AND column_name = 'provider'"
        )
        row = cur.fetchone()
    assert row is not None, "candles.provider column must exist after migration 003"


def test_candles_provider_column_defaults_to_capital(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'candles' AND column_name = 'provider'"
        )
        row = cur.fetchone()
    assert row is not None
    assert "capital" in (row[0] or ""), f"Expected default 'capital', got {row[0]!r}"


def test_candles_old_unique_constraint_absent(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM pg_constraint
            WHERE conname = 'candles_epic_resolution_candle_start_key'
            """
        )
        count = cur.fetchone()[0]
    assert count == 0, "Old constraint candles_epic_resolution_candle_start_key must be dropped"


def test_candles_new_unique_constraint_present(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM pg_constraint
            WHERE conname = 'candles_provider_epic_resolution_candle_start_key'
            """
        )
        count = cur.fetchone()[0]
    assert count == 1, "New constraint candles_provider_epic_resolution_candle_start_key must exist"


def test_idx_candles_recent_leads_with_provider(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_class ix ON ix.oid = i.indexrelid
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = i.indkey[0]
            WHERE c.relname = 'candles' AND ix.relname = 'idx_candles_recent'
            """
        )
        row = cur.fetchone()
    assert row is not None, "idx_candles_recent must exist"
    assert row[0] == "provider", f"First column of idx_candles_recent must be 'provider', got {row[0]!r}"


def test_candles_different_providers_coexist_on_same_key(pg_conn):
    from datetime import datetime, timezone
    ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO candles
                (provider, epic, resolution, candle_start,
                 open_bid, high_bid, low_bid, close_bid,
                 open_ask, high_ask, low_ask, close_ask)
            VALUES
                ('capital',    'EURUSD', 'MINUTE_15', %s, 1,1,1,1,1,1,1,1),
                ('ic_markets', 'EURUSD', 'MINUTE_15', %s, 2,2,2,2,2,2,2,2)
            """,
            (ts, ts),
        )
        cur.execute(
            "SELECT COUNT(*) FROM candles WHERE epic='EURUSD' AND candle_start=%s", (ts,)
        )
        count = cur.fetchone()[0]
    assert count == 2, "Two rows with different providers must coexist on same (epic,resolution,candle_start)"


# ---------------------------------------------------------------------------
# Migration 004: provider column on trade_entries
# ---------------------------------------------------------------------------

def test_trade_entries_has_provider_column(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'trade_entries' AND column_name = 'provider'"
        )
        row = cur.fetchone()
    assert row is not None, "trade_entries.provider column must exist after migration 004"


def test_trade_entries_provider_column_defaults_to_capital(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'trade_entries' AND column_name = 'provider'"
        )
        row = cur.fetchone()
    assert row is not None
    assert "capital" in (row[0] or ""), f"Expected default 'capital', got {row[0]!r}"


def test_trade_entries_deal_id_still_unique(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'trade_entries' AND c.contype IN ('u', 'p')
            """
        )
        count = cur.fetchone()[0]
    assert count >= 1, "trade_entries must still have a uniqueness/PK constraint on deal_id"
