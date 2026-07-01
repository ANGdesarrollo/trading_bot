from __future__ import annotations

import logging

from domain.ports.clock_port import ClockPort
from domain.ports.session_cache_port import CachedSessionRecord, SessionCachePort
from infrastructure.capital.session import SessionTokens

_log = logging.getLogger(__name__)

_DEFAULT_READER_POLL_SECONDS = 2.0
_DEFAULT_REFRESH_TTL_SECONDS = 540.0


class SharedCachedSession:
    """Shares one Capital session token across processes via a SessionCachePort.

    Exactly one process runs as `owner`: it re-authenticates against Capital
    only when the cached token is older than the refresh TTL, then overwrites
    the shared token. Any number of authenticate() calls within the TTL reuse
    the cached token without hitting /session, so a flapping WS reconnect loop
    never triggers rate limiting. Readers never call /session: they load
    whatever the owner last wrote, waiting only until the first token exists.
    """

    def __init__(
        self,
        inner,
        cache: SessionCachePort,
        clock: ClockPort,
        owner: bool = False,
        reader_poll_seconds: float = _DEFAULT_READER_POLL_SECONDS,
        refresh_ttl_seconds: float = _DEFAULT_REFRESH_TTL_SECONDS,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._clock = clock
        self._owner = owner
        self._reader_poll_seconds = reader_poll_seconds
        self._refresh_ttl_seconds = refresh_ttl_seconds
        self._record: CachedSessionRecord | None = None

    def authenticate(self) -> SessionTokens:
        if self._owner:
            return self._authenticate_as_owner()
        return self._authenticate_as_reader()

    def _authenticate_as_owner(self) -> SessionTokens:
        cached = self._cache.load()
        if cached is not None and self._is_fresh(cached):
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

    def _is_fresh(self, record: CachedSessionRecord) -> bool:
        age = (self._clock.utcnow() - record.authenticated_at).total_seconds()
        return age < self._refresh_ttl_seconds

    def _authenticate_as_reader(self) -> SessionTokens:
        while True:
            cached = self._cache.load()
            if cached is not None:
                self._record = cached
                return self.tokens()
            _log.info("no shared token yet; waiting for owner")
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
