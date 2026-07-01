from __future__ import annotations

from datetime import datetime, timezone

from infrastructure.capital.session import SessionTokens
from infrastructure.capital.session_refresher import SessionTokenRefresher
from tests.fakes.fake_clock import FakeClock
from tests.fakes.fake_session_cache import FakeSessionCache

_SEED = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


class _SpySession:
    def __init__(self) -> None:
        self.auth_calls = 0
        self._tokens: SessionTokens | None = None

    def authenticate(self) -> SessionTokens:
        self.auth_calls += 1
        self._tokens = SessionTokens(
            cst=f"cst-{self.auth_calls}", security_token=f"xst-{self.auth_calls}")
        return self._tokens

    def tokens(self) -> SessionTokens:
        assert self._tokens is not None
        return self._tokens

    @property
    def streaming_host(self) -> str:
        return "wss://stream"


def test_refresh_once_authenticates_and_writes_cache():
    inner = _SpySession()
    cache = FakeSessionCache()
    refresher = SessionTokenRefresher(inner=inner, cache=cache, clock=FakeClock(_SEED))

    refresher.refresh_once()

    assert inner.auth_calls == 1
    stored = cache.load()
    assert stored.cst == "cst-1"
    assert stored.streaming_host == "wss://stream"
    assert stored.authenticated_at == _SEED


def test_refresh_once_always_reauthenticates():
    inner = _SpySession()
    cache = FakeSessionCache()
    refresher = SessionTokenRefresher(inner=inner, cache=cache, clock=FakeClock(_SEED))

    refresher.refresh_once()
    refresher.refresh_once()

    assert inner.auth_calls == 2
    assert cache.load().cst == "cst-2"
