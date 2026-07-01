from __future__ import annotations

from datetime import datetime, timezone

from domain.ports.session_cache_port import CachedSessionRecord
from infrastructure.capital.session import SessionTokens
from infrastructure.capital.shared_cached_session import SharedCachedSession
from tests.fakes.fake_clock import FakeClock
from tests.fakes.fake_session_cache import FakeSessionCache

_SEED = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
_MAX_AGE = 600.0


def _record(at, cst="cst-shared") -> CachedSessionRecord:
    return CachedSessionRecord(
        cst=cst,
        security_token="xst-shared",
        streaming_host="wss://stream-shared",
        authenticated_at=at,
    )


def _reader(cache=None, clock=None):
    clock = clock or FakeClock(_SEED)
    cache = cache if cache is not None else FakeSessionCache()
    session = SharedCachedSession(cache=cache, clock=clock, max_age_seconds=_MAX_AGE)
    return session, cache, clock


def test_reads_fresh_token_from_cache():
    cache = FakeSessionCache(_record(_SEED))
    session, _, _ = _reader(cache=cache)

    session.authenticate()

    assert session.tokens() == SessionTokens(cst="cst-shared", security_token="xst-shared")
    assert session.streaming_host == "wss://stream-shared"


def test_rereads_latest_token_on_each_call():
    cache = FakeSessionCache(_record(_SEED, cst="cst-old"))
    session, _, _ = _reader(cache=cache)
    session.authenticate()

    cache.store(_record(_SEED, cst="cst-new"))
    session.authenticate()

    assert session.tokens().cst == "cst-new"


def test_waits_until_a_token_appears():
    cache = FakeSessionCache(None)
    clock = FakeClock(_SEED)
    session, _, _ = _reader(cache=cache, clock=clock)

    calls = {"n": 0}

    def load_then_populate():
        calls["n"] += 1
        if calls["n"] >= 3:
            cache._record = _record(clock.utcnow())
        return cache._record

    cache.load = load_then_populate

    session.authenticate()

    assert len(clock.sleep_calls) == 2
    assert session.tokens().cst == "cst-shared"


def test_stale_token_is_not_used_waits_for_refresh():
    # A token older than max_age must NOT be handed out (this is the 401 bug):
    # wait for the refresher to write a fresh one instead.
    clock = FakeClock(_SEED)
    stale = _record(_SEED, cst="cst-stale")
    clock.advance(_MAX_AGE + 1.0)
    cache = FakeSessionCache(stale)
    session, _, _ = _reader(cache=cache, clock=clock)

    calls = {"n": 0}

    def load_then_fresh():
        calls["n"] += 1
        if calls["n"] >= 2:
            cache._record = _record(clock.utcnow(), cst="cst-fresh")
        return cache._record

    cache.load = load_then_fresh

    session.authenticate()

    assert len(clock.sleep_calls) == 1
    assert session.tokens().cst == "cst-fresh"
