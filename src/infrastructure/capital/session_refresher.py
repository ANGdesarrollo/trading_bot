from __future__ import annotations

import logging

from domain.ports.clock_port import ClockPort
from domain.ports.session_cache_port import CachedSessionRecord, SessionCachePort

_log = logging.getLogger(__name__)


class SessionTokenRefresher:
    """Authenticates against Capital and writes the token to the shared cache.

    Run as a standalone service on a fixed cadence shorter than the token's
    ~10 min lifetime. It is the single writer of the shared session token;
    all other processes read it via SharedCachedSession.
    """

    def __init__(self, inner, cache: SessionCachePort, clock: ClockPort) -> None:
        self._inner = inner
        self._cache = cache
        self._clock = clock

    def refresh_once(self) -> None:
        self._inner.authenticate()
        record = CachedSessionRecord(
            cst=self._inner.tokens().cst,
            security_token=self._inner.tokens().security_token,
            streaming_host=self._inner.streaming_host,
            authenticated_at=self._clock.utcnow(),
        )
        self._cache.store(record)
        _log.info("shared session token refreshed")

    def run_forever(self, interval_seconds: float) -> None:
        while True:
            try:
                self.refresh_once()
            except Exception:
                _log.exception("token refresh failed; retrying next interval")
            self._clock.sleep(interval_seconds)
