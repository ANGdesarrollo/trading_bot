from __future__ import annotations

from domain.ports.session_cache_port import CachedSessionRecord, SessionCachePort


class FakeSessionCache(SessionCachePort):
    def __init__(self, initial: CachedSessionRecord | None = None) -> None:
        self._record = initial
        self.store_calls = 0

    def load(self) -> CachedSessionRecord | None:
        return self._record

    def store(self, record: CachedSessionRecord) -> None:
        self._record = record
        self.store_calls += 1
