from __future__ import annotations

from datetime import datetime
from typing import Protocol

from domain.ports.clock_port import ClockPort
from infrastructure.capital.session import SessionTokens

_DEFAULT_REFRESH_TTL_SECONDS = 540.0


class _Authenticatable(Protocol):
    def authenticate(self) -> SessionTokens: ...
    def tokens(self) -> SessionTokens: ...


class CachedSession:
    """Caches Capital session tokens and refreshes only near expiry.

    Capital tokens live ~10 min and POST /session is rate-limited per account.
    Re-authenticating every cycle across operator + reconciler triggers HTTP 429,
    so authenticate() is a no-op while the cached token is within its TTL.
    """

    def __init__(
        self,
        inner: _Authenticatable,
        clock: ClockPort,
        refresh_ttl_seconds: float = _DEFAULT_REFRESH_TTL_SECONDS,
    ) -> None:
        self._inner = inner
        self._clock = clock
        self._refresh_ttl_seconds = refresh_ttl_seconds
        self._authenticated_at: datetime | None = None

    def authenticate(self) -> SessionTokens:
        if not self._is_fresh():
            self._inner.authenticate()
            self._authenticated_at = self._clock.utcnow()
        return self._inner.tokens()

    def tokens(self) -> SessionTokens:
        return self._inner.tokens()

    def _is_fresh(self) -> bool:
        if self._authenticated_at is None:
            return False
        age = (self._clock.utcnow() - self._authenticated_at).total_seconds()
        return age <= self._refresh_ttl_seconds
