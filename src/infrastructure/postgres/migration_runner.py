from __future__ import annotations

from pathlib import Path

_DEFAULT_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_CREATE_SCHEMA_MIGRATIONS = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

_SELECT_APPLIED = "SELECT version FROM schema_migrations"
_INSERT_APPLIED = "INSERT INTO schema_migrations (version) VALUES (%s)"


def run_migrations(conn, migrations_dir: Path = _DEFAULT_MIGRATIONS_DIR) -> None:
    with conn.cursor() as cur:
        cur.execute(_CREATE_SCHEMA_MIGRATIONS)
        conn.commit()
        cur.execute(_SELECT_APPLIED)
        applied = {row[0] for row in cur.fetchall()}

    sql_files = sorted(migrations_dir.glob("*.sql"), key=lambda p: p.name)
    for sql_file in sql_files:
        if sql_file.name in applied:
            continue
        sql = sql_file.read_text()
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(_INSERT_APPLIED, (sql_file.name,))
        conn.commit()
