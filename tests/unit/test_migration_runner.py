from __future__ import annotations

import tempfile
from pathlib import Path

from infrastructure.postgres.migration_runner import run_migrations


class _FakeCursor:
    def __init__(self, rows: list = ()) -> None:
        self._rows = list(rows)
        self.executed: list[str] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append(sql.strip())

    def fetchall(self) -> list:
        return self._rows

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        pass


class _FakeConn:
    def __init__(self, applied_rows: list[tuple[str]] = ()) -> None:
        self._cursor = _FakeCursor(rows=list(applied_rows))
        self.committed = 0

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.committed += 1

    def __enter__(self) -> _FakeConn:
        return self

    def __exit__(self, *args: object) -> None:
        pass


def _write_sql(directory: Path, filename: str, content: str) -> None:
    (directory / filename).write_text(content)


def test_runner_creates_schema_migrations_table_on_first_run():
    with tempfile.TemporaryDirectory() as tmp:
        migrations_dir = Path(tmp)
        _write_sql(migrations_dir, "001_test.sql", "CREATE TABLE foo (id SERIAL);")
        conn = _FakeConn(applied_rows=[])
        run_migrations(conn, migrations_dir=migrations_dir)
        assert any("CREATE TABLE" in s and "schema_migrations" in s for s in conn._cursor.executed)


def test_runner_applies_pending_sql_in_order():
    with tempfile.TemporaryDirectory() as tmp:
        migrations_dir = Path(tmp)
        _write_sql(migrations_dir, "001_first.sql", "CREATE TABLE a (id INT);")
        _write_sql(migrations_dir, "002_second.sql", "CREATE TABLE b (id INT);")
        conn = _FakeConn(applied_rows=[])
        run_migrations(conn, migrations_dir=migrations_dir)
        sql_executed = " ".join(conn._cursor.executed)
        assert "CREATE TABLE a" in sql_executed
        assert "CREATE TABLE b" in sql_executed


def test_runner_skips_already_applied_migration():
    with tempfile.TemporaryDirectory() as tmp:
        migrations_dir = Path(tmp)
        _write_sql(migrations_dir, "001_already.sql", "CREATE TABLE already_there (id INT);")
        conn = _FakeConn(applied_rows=[("001_already.sql",)])
        run_migrations(conn, migrations_dir=migrations_dir)
        sql_executed = " ".join(conn._cursor.executed)
        assert "CREATE TABLE already_there" not in sql_executed


def test_002_create_candles_sql_is_discovered_and_applied():
    from pathlib import Path
    real_migrations_dir = (
        Path(__file__).parent.parent.parent
        / "src" / "infrastructure" / "postgres" / "migrations"
    )
    conn = _FakeConn(applied_rows=[("001_create_trade_entries.sql",)])
    run_migrations(conn, migrations_dir=real_migrations_dir)
    sql_executed = " ".join(conn._cursor.executed)
    assert "candles" in sql_executed.lower()
    assert "idx_candles_recent" in sql_executed.lower()


def test_runner_applies_new_migration_when_first_already_applied():
    with tempfile.TemporaryDirectory() as tmp:
        migrations_dir = Path(tmp)
        _write_sql(migrations_dir, "001_done.sql", "CREATE TABLE done_table (id INT);")
        _write_sql(migrations_dir, "002_new.sql", "CREATE TABLE new_table (id INT);")
        conn = _FakeConn(applied_rows=[("001_done.sql",)])
        run_migrations(conn, migrations_dir=migrations_dir)
        sql_executed = " ".join(conn._cursor.executed)
        assert "CREATE TABLE done_table" not in sql_executed
        assert "CREATE TABLE new_table" in sql_executed
