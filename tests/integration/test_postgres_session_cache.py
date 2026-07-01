from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

DATABASE_URL = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")

_AT = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_LATER = datetime(2024, 1, 1, 12, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def pg_conn():
    import psycopg
    from infrastructure.postgres.migration_runner import run_migrations

    conn = psycopg.connect(DATABASE_URL)
    run_migrations(conn)
    conn.execute("TRUNCATE capital_session")
    conn.commit()
    yield conn
    conn.execute("TRUNCATE capital_session")
    conn.commit()
    conn.close()


def _record(at, *, cst="cst-1", xst="xst-1", host="wss://stream"):
    from domain.ports.session_cache_port import CachedSessionRecord
    return CachedSessionRecord(
        cst=cst, security_token=xst, streaming_host=host, authenticated_at=at
    )


def test_load_empty_returns_none(pg_conn):
    from infrastructure.postgres.session_cache import PostgresSessionCache
    cache = PostgresSessionCache(pg_conn)
    assert cache.load() is None


def test_store_then_load_round_trip(pg_conn):
    from infrastructure.postgres.session_cache import PostgresSessionCache
    cache = PostgresSessionCache(pg_conn)
    cache.store(_record(_AT))

    loaded = cache.load()

    assert loaded is not None
    assert loaded.cst == "cst-1"
    assert loaded.security_token == "xst-1"
    assert loaded.streaming_host == "wss://stream"
    assert loaded.authenticated_at == _AT
    assert loaded.authenticated_at.tzinfo is not None


def test_store_overwrites_single_row(pg_conn):
    from infrastructure.postgres.session_cache import PostgresSessionCache
    cache = PostgresSessionCache(pg_conn)
    cache.store(_record(_AT, cst="old"))
    cache.store(_record(_LATER, cst="new"))

    loaded = cache.load()
    assert loaded.cst == "new"
    assert loaded.authenticated_at == _LATER

    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM capital_session")
        assert cur.fetchone()[0] == 1
