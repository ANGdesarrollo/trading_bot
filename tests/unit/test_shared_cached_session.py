from __future__ import annotations

from datetime import datetime, timezone

from domain.ports.session_cache_port import CachedSessionRecord
from infrastructure.capital.session import SessionTokens
from infrastructure.capital.shared_cached_session import SharedCachedSession
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
            cst=f"cst-{self.auth_calls}",
            security_token=f"xst-{self.auth_calls}",
        )
        return self._tokens

    def tokens(self) -> SessionTokens:
        if self._tokens is None:
            raise RuntimeError("not authenticated")
        return self._tokens

    @property
    def streaming_host(self) -> str:
        return "wss://stream-from-inner"


def _record(at) -> CachedSessionRecord:
    return CachedSessionRecord(
        cst="cst-shared",
        security_token="xst-shared",
        streaming_host="wss://stream-shared",
        authenticated_at=at,
    )


def _owner(cache=None, clock=None):
    clock = clock or FakeClock(_SEED)
    cache = cache if cache is not None else FakeSessionCache()
    inner = _SpySession()
    session = SharedCachedSession(inner=inner, cache=cache, clock=clock, owner=True)
    return session, inner, cache, clock


def _reader(cache=None, clock=None):
    clock = clock or FakeClock(_SEED)
    cache = cache if cache is not None else FakeSessionCache()
    inner = _SpySession()
    session = SharedCachedSession(inner=inner, cache=cache, clock=clock, owner=False)
    return session, inner, cache, clock


def test_owner_authenticates_and_writes_cache():
    session, inner, cache, _ = _owner()

    session.authenticate()

    assert inner.auth_calls == 1
    assert cache.store_calls == 1
    stored = cache.load()
    assert stored.cst == "cst-1"
    assert stored.streaming_host == "wss://stream-from-inner"


def test_owner_reuses_fresh_cached_token_without_reauth():
    session, inner, cache, clock = _owner()

    session.authenticate()
    session.authenticate()
    session.authenticate()

    assert inner.auth_calls == 1
    assert cache.store_calls == 1


def test_owner_reauthenticates_after_ttl():
    clock = FakeClock(_SEED)
    session, inner, cache, _ = _owner(clock=clock)

    session.authenticate()
    clock.advance(541.0)
    session.authenticate()

    assert inner.auth_calls == 2
    assert cache.store_calls == 2


def test_owner_reuses_token_written_by_a_previous_owner_instance():
    # A fresh token already in the cache (e.g. written before a restart)
    # must be reused, not overwritten with a new /session call.
    cache = FakeSessionCache(_record(_SEED))
    clock = FakeClock(_SEED)
    session, inner, _, _ = _owner(cache=cache, clock=clock)

    session.authenticate()

    assert inner.auth_calls == 0
    assert session.tokens().cst == "cst-shared"


def test_reader_never_calls_inner_authenticate():
    cache = FakeSessionCache(_record(_SEED))
    session, inner, _, _ = _reader(cache=cache)

    session.authenticate()

    assert inner.auth_calls == 0


def test_reader_exposes_shared_tokens_and_host():
    cache = FakeSessionCache(_record(_SEED))
    session, _, _, _ = _reader(cache=cache)

    session.authenticate()

    assert session.tokens() == SessionTokens(cst="cst-shared", security_token="xst-shared")
    assert session.streaming_host == "wss://stream-shared"


def test_reader_rereads_latest_token_on_each_call():
    cache = FakeSessionCache(_record(_SEED))
    session, _, _, _ = _reader(cache=cache)
    session.authenticate()

    cache.store(CachedSessionRecord(
        cst="cst-new", security_token="xst-new",
        streaming_host="wss://stream-shared", authenticated_at=_SEED,
    ))
    session.authenticate()

    assert session.tokens().cst == "cst-new"


def test_reader_waits_silently_until_token_appears():
    cache = FakeSessionCache(None)
    clock = FakeClock(_SEED)
    session, inner, _, _ = _reader(cache=cache, clock=clock)

    calls = {"n": 0}

    def load_then_populate():
        calls["n"] += 1
        if calls["n"] >= 3:
            cache._record = _record(clock.utcnow())
        return cache._record

    cache.load = load_then_populate

    session.authenticate()

    assert inner.auth_calls == 0
    assert len(clock.sleep_calls) == 2
    assert session.tokens() == SessionTokens(cst="cst-shared", security_token="xst-shared")
