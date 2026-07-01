"""Tests for CapitalSession (T-15, REQ-09, REQ-10).

Scenarios:
  5.1 — successful auth stores CST and X-SECURITY-TOKEN from headers
  5.2 — re-auth replaces old tokens
  5.3 — non-2xx raises AuthenticationError, no tokens stored
"""

import pytest

from infrastructure.capital.session import AuthenticationError, CapitalSession
from tests.fakes.fake_http import CannedResponse, FakeHttp


def _make_session(responses: list[CannedResponse]) -> tuple[CapitalSession, FakeHttp]:
    http = FakeHttp(responses)
    session = CapitalSession(
        http=http,
        base_url="https://demo-api-capital.backend-capital.com/api/v1",
        api_key="test-key",
        identifier="user@example.com",
        password="secret",
    )
    return session, http


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
