"""Tests for CapitalSession (T-15, REQ-09, REQ-10).

Scenarios:
  5.1 — successful auth stores CST and X-SECURITY-TOKEN from headers
  5.2 — re-auth replaces old tokens
  5.3 — non-2xx raises AuthenticationError, no tokens stored
"""

from datetime import datetime, timezone

import pytest

from infrastructure.capital.session import AuthenticationError, CapitalSession
from tests.fakes.fake_clock import FakeClock
from tests.fakes.fake_http import CannedResponse, FakeHttp


def _make_session(
    responses: list[CannedResponse],
    clock: FakeClock | None = None,
    max_auth_retries: int = 0,
) -> tuple[CapitalSession, FakeHttp]:
    http = FakeHttp(responses)
    session = CapitalSession(
        http=http,
        base_url="https://demo-api-capital.backend-capital.com/api/v1",
        api_key="test-key",
        identifier="user@example.com",
        password="secret",
        clock=clock,
        max_auth_retries=max_auth_retries,
    )
    return session, http


def _ok(cst: str = "cst", xst: str = "xst") -> CannedResponse:
    return CannedResponse(
        status_code=200,
        headers={"CST": cst, "X-SECURITY-TOKEN": xst},
        json_body={},
    )


def _rate_limited() -> CannedResponse:
    return CannedResponse(status_code=429, headers={}, json_body={})


def _seeded_clock() -> FakeClock:
    return FakeClock(datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc))


def test_successful_auth_stores_cst_and_security_token():
    response = CannedResponse(
        status_code=200,
        headers={"CST": "cst-value-123", "X-SECURITY-TOKEN": "xst-value-456"},
        json_body={"accountType": "SPREADBET"},
    )
    session, _ = _make_session([response])

    tokens = session.authenticate()

    assert tokens.cst == "cst-value-123"
    assert tokens.security_token == "xst-value-456"


def test_tokens_returns_last_authenticated_tokens():
    response = CannedResponse(
        status_code=200,
        headers={"CST": "cst-abc", "X-SECURITY-TOKEN": "xst-def"},
        json_body={},
    )
    session, _ = _make_session([response])
    session.authenticate()

    tokens = session.tokens()

    assert tokens.cst == "cst-abc"
    assert tokens.security_token == "xst-def"


def test_re_auth_replaces_old_tokens():
    first = CannedResponse(
        status_code=200,
        headers={"CST": "old-cst", "X-SECURITY-TOKEN": "old-xst"},
        json_body={},
    )
    second = CannedResponse(
        status_code=200,
        headers={"CST": "new-cst", "X-SECURITY-TOKEN": "new-xst"},
        json_body={},
    )
    session, _ = _make_session([first, second])

    session.authenticate()
    session.authenticate()

    tokens = session.tokens()
    assert tokens.cst == "new-cst"
    assert tokens.security_token == "new-xst"


def test_non_2xx_raises_authentication_error():
    response = CannedResponse(
        status_code=401,
        headers={},
        json_body={"errorCode": "error.invalid.credentials"},
    )
    session, _ = _make_session([response])

    with pytest.raises(AuthenticationError):
        session.authenticate()


def test_no_tokens_stored_after_failed_auth():
    bad = CannedResponse(status_code=401, headers={}, json_body={})
    session, _ = _make_session([bad])

    with pytest.raises(AuthenticationError):
        session.authenticate()

    with pytest.raises(RuntimeError):
        session.tokens()


def test_streaming_host_raises_before_authenticate():
    session, _ = _make_session([])

    with pytest.raises(RuntimeError):
        _ = session.streaming_host


def test_streaming_host_available_after_authenticate():
    response = CannedResponse(
        status_code=200,
        headers={"CST": "cst-value-123", "X-SECURITY-TOKEN": "xst-value-456"},
        json_body={"streamingHost": "wss://api-streaming-capital.backend-capital.com"},
    )
    session, _ = _make_session([response])

    session.authenticate()

    assert session.streaming_host == "wss://api-streaming-capital.backend-capital.com"


def test_streaming_host_strips_trailing_slash():
    response = CannedResponse(
        status_code=200,
        headers={"CST": "cst-value-123", "X-SECURITY-TOKEN": "xst-value-456"},
        json_body={"streamingHost": "wss://api-streaming-capital.backend-capital.com/"},
    )
    session, _ = _make_session([response])

    session.authenticate()

    assert session.streaming_host == "wss://api-streaming-capital.backend-capital.com"


def test_authenticate_still_returns_session_tokens_with_streaming_host():
    response = CannedResponse(
        status_code=200,
        headers={"CST": "cst-s2", "X-SECURITY-TOKEN": "xst-s2"},
        json_body={"streamingHost": "wss://streaming.example.com"},
    )
    session, _ = _make_session([response])

    tokens = session.authenticate()

    assert tokens.cst == "cst-s2"
    assert tokens.security_token == "xst-s2"


def test_tokens_still_works_after_streaming_host_captured():
    response = CannedResponse(
        status_code=200,
        headers={"CST": "cst-t", "X-SECURITY-TOKEN": "xst-t"},
        json_body={"streamingHost": "wss://streaming.example.com"},
    )
    session, _ = _make_session([response])
    session.authenticate()

    tokens = session.tokens()

    assert tokens.cst == "cst-t"
    assert tokens.security_token == "xst-t"


def test_retries_on_429_then_succeeds():
    clock = _seeded_clock()
    session, http = _make_session(
        [_rate_limited(), _ok("cst-final", "xst-final")],
        clock=clock,
        max_auth_retries=3,
    )

    tokens = session.authenticate()

    assert tokens.cst == "cst-final"
    assert len(http.calls) == 2
    assert len(clock.sleep_calls) == 1


def test_gives_up_after_max_retries_on_persistent_429():
    clock = _seeded_clock()
    session, http = _make_session(
        [_rate_limited(), _rate_limited(), _rate_limited()],
        clock=clock,
        max_auth_retries=2,
    )

    with pytest.raises(AuthenticationError):
        session.authenticate()

    assert len(http.calls) == 3


def test_does_not_retry_on_401():
    clock = _seeded_clock()
    session, http = _make_session(
        [CannedResponse(status_code=401, headers={}, json_body={})],
        clock=clock,
        max_auth_retries=3,
    )

    with pytest.raises(AuthenticationError):
        session.authenticate()

    assert len(http.calls) == 1
    assert clock.sleep_calls == []


def test_no_retry_by_default_preserves_existing_behavior():
    session, http = _make_session([_rate_limited()])

    with pytest.raises(AuthenticationError):
        session.authenticate()

    assert len(http.calls) == 1
