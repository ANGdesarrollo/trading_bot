from __future__ import annotations

import logging

from domain.ports.clock_port import ClockPort
from domain.ports.session_cache_port import CachedSessionRecord, SessionCachePort
from infrastructure.capital.session import SessionTokens

_log = logging.getLogger(__name__)

_DEFAULT_POLL_SECONDS = 2.0
_DEFAULT_MAX_AGE_SECONDS = 600.0


class SharedCachedSession:
    """Read-only view over the shared Capital token in a SessionCachePort.

    A dedicated refresher process authenticates and writes the token on a
    fixed cadence; every other process (ingestion, operator, reconciler)
    uses this to READ that token. authenticate() never calls /session: it
    loads the cached token and, if it is missing or older than max_age,
    waits for the refresher rather than handing out a stale token.
    """

    def __init__(
        self,
        cache: SessionCachePort,
        clock: ClockPort,
        poll_seconds: float = _DEFAULT_POLL_SECONDS,
        max_age_seconds: float = _DEFAULT_MAX_AGE_SECONDS,
    ) -> None:
        self._cache = cache
        self._clock = clock
        self._poll_seconds = poll_seconds
        self._max_age_seconds = max_age_seconds
        self._record: CachedSessionRecord | None = None

    def authenticate(self) -> SessionTokens:
        while True:
            cached = self._cache.load()
            if cached is not None and self._is_usable(cached):
                self._record = cached
                return self.tokens()
            _log.info("no fresh shared token yet; waiting for refresher")
            self._clock.sleep(self._poll_seconds)

    def _is_usable(self, record: CachedSessionRecord) -> bool:
        age = (self._clock.utcnow() - record.authenticated_at).total_seconds()
        return age < self._max_age_seconds

    def tokens(self) -> SessionTokens:
        if self._record is None:
            raise RuntimeError("Not authenticated — call authenticate() first")
        return SessionTokens(
            cst=self._record.cst,
            security_token=self._record.security_token,
        )

    @property
    def streaming_host(self) -> str:
        if self._record is None:
            raise RuntimeError("Not authenticated — call authenticate() first")
        return self._record.streaming_host
