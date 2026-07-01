from __future__ import annotations

from datetime import datetime, timezone

from infrastructure.capital.cached_session import CachedSession
from infrastructure.capital.session import SessionTokens
from tests.fakes.fake_clock import FakeClock

_SEED = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


class _SpySession:
    def __init__(self) -> None:
        self.auth_calls = 0
        self._tokens: SessionTokens | None = None

    def authenticate(self) -> SessionTokens:
        self.auth_calls += 1
        self._tokens = SessionTokens(
            cst=f"cst-{self.auth_calls}",
            security_token=f"xst-{self.auth_calls}",
        )
        return self._tokens

    def tokens(self) -> SessionTokens:
        if self._tokens is None:
            raise RuntimeError("not authenticated")
        return self._tokens


def _make(ttl=540.0):
    clock = FakeClock(_SEED)
    inner = _SpySession()
    cached = CachedSession(inner=inner, clock=clock, refresh_ttl_seconds=ttl)
    return cached, inner, clock


def test_first_authenticate_hits_inner_eagerly():
    cached, inner, _ = _make()
    cached.authenticate()
    assert inner.auth_calls == 1


def test_repeated_authenticate_within_ttl_does_not_reauth():
    cached, inner, clock = _make(ttl=540.0)
    cached.authenticate()
    clock.advance(500.0)
    cached.authenticate()
    cached.authenticate()
    assert inner.auth_calls == 1


def test_authenticate_after_ttl_reauths():
    cached, inner, clock = _make(ttl=540.0)
    cached.authenticate()
    clock.advance(541.0)
    cached.authenticate()
    assert inner.auth_calls == 2


def test_tokens_returns_cached_inner_tokens():
    cached, _, _ = _make()
    cached.authenticate()
    assert cached.tokens() == SessionTokens(cst="cst-1", security_token="xst-1")


def test_tokens_before_authenticate_raises():
    cached, _, _ = _make()
    try:
        cached.tokens()
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError before authenticate")


def test_refreshed_tokens_are_the_new_ones():
    cached, _, clock = _make(ttl=540.0)
    cached.authenticate()
    clock.advance(541.0)
    cached.authenticate()
    assert cached.tokens() == SessionTokens(cst="cst-2", security_token="xst-2")
