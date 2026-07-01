from __future__ import annotations

from domain.ports.session_cache_port import CachedSessionRecord, SessionCachePort

_UPSERT = """
INSERT INTO capital_session (id, cst, security_token, streaming_host, authenticated_at)
VALUES (1, %s, %s, %s, %s)
ON CONFLICT (id) DO UPDATE SET
    cst              = EXCLUDED.cst,
    security_token   = EXCLUDED.security_token,
    streaming_host   = EXCLUDED.streaming_host,
    authenticated_at = EXCLUDED.authenticated_at
"""

_SELECT = """
SELECT cst, security_token, streaming_host, authenticated_at
FROM capital_session
WHERE id = 1
"""


class PostgresSessionCache(SessionCachePort):
    def __init__(self, conn) -> None:
        self._conn = conn

    def load(self) -> CachedSessionRecord | None:
        with self._conn.cursor() as cur:
            cur.execute(_SELECT)
            row = cur.fetchone()
        if row is None:
            return None
        cst, security_token, streaming_host, authenticated_at = row
        return CachedSessionRecord(
            cst=cst,
            security_token=security_token,
            streaming_host=streaming_host,
            authenticated_at=authenticated_at,
        )

    def store(self, record: CachedSessionRecord) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_UPSERT, (
                record.cst,
                record.security_token,
                record.streaming_host,
                record.authenticated_at,
            ))
        self._conn.commit()
