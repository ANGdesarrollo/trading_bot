from __future__ import annotations

import logging

from domain.ports.clock_port import ClockPort
from domain.ports.session_cache_port import CachedSessionRecord, SessionCachePort
from infrastructure.capital.session import SessionTokens

_log = logging.getLogger(__name__)

_DEFAULT_REFRESH_TTL_SECONDS = 540.0
_DEFAULT_READER_POLL_SECONDS = 2.0


class SharedCachedSession:
    """Shares one Capital session token across processes via a SessionCachePort.

    Exactly one process runs as `owner`: it authenticates against Capital and
    writes the token to the shared cache. All other processes run as readers:
    they never call /session, they read the token the owner wrote. A reader with
    no fresh token waits silently rather than authenticating, because the system
    is not operable without the owner (the ingester) running anyway.
    """

    def __init__(
        self,
        inner,
        cache: SessionCachePort,
        clock: ClockPort,
        refresh_ttl_seconds: float = _DEFAULT_REFRESH_TTL_SECONDS,
        owner: bool = False,
        reader_poll_seconds: float = _DEFAULT_READER_POLL_SECONDS,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._clock = clock
        self._refresh_ttl_seconds = refresh_ttl_seconds
        self._owner = owner
        self._reader_poll_seconds = reader_poll_seconds
        self._record: CachedSessionRecord | None = None

    def authenticate(self) -> SessionTokens:
        if self._owner:
            return self._authenticate_as_owner()
        return self._authenticate_as_reader()

    def _authenticate_as_owner(self) -> SessionTokens:
        cached = self._cache.load()
        if self._is_fresh(cached):
            self._record = cached
            return self.tokens()

        self._inner.authenticate()
        self._record = CachedSessionRecord(
            cst=self._inner.tokens().cst,
            security_token=self._inner.tokens().security_token,
            streaming_host=self._inner.streaming_host,
            authenticated_at=self._clock.utcnow(),
        )
        self._cache.store(self._record)
        return self.tokens()

    def _authenticate_as_reader(self) -> SessionTokens:
        while True:
            cached = self._cache.load()
            if self._is_fresh(cached):
                self._record = cached
                return self.tokens()
            _log.info("no fresh shared token yet; waiting for owner")
            self._clock.sleep(self._reader_poll_seconds)

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

    def _is_fresh(self, record: CachedSessionRecord | None) -> bool:
        if record is None:
            return False
        age = (self._clock.utcnow() - record.authenticated_at).total_seconds()
        return age <= self._refresh_ttl_seconds
