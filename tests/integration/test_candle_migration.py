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
