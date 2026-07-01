from __future__ import annotations

import logging
import random
from dataclasses import dataclass

_log = logging.getLogger(__name__)

_RATE_LIMITED = 429
_BACKOFF_BASE_S = 1.0
_BACKOFF_CAP_S = 60.0


def _full_jitter(attempt: int) -> float:
    ceiling = min(_BACKOFF_CAP_S, _BACKOFF_BASE_S * (2 ** attempt))
    return random.uniform(0, ceiling)


class AuthenticationError(Exception):
    """Raised when Capital.com rejects the session credentials."""


@dataclass(frozen=True)
class SessionTokens:
    cst: str
    security_token: str


class CapitalSession:
    """Authenticates with Capital.com and holds the resulting session tokens.

    Authentication is eager: call authenticate() at the start of every cycle.
    Capital.com sessions expire after ~10 minutes; on a 15-minute poll cadence
    tokens would be stale by the next cycle, so re-authenticating every cycle
    is the simplest correct approach.
    """

    def __init__(
        self,
        http,
        base_url: str,
        api_key: str,
        identifier: str,
        password: str,
        clock=None,
        max_auth_retries: int = 0,
    ) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._identifier = identifier
        self._password = password
        self._clock = clock
        self._max_auth_retries = max_auth_retries
        self._tokens: SessionTokens | None = None
        self._streaming_host: str | None = None

    def authenticate(self) -> SessionTokens:
        attempt = 0
        while True:
            response = self._http.post(
                f"{self._base_url}/session",
                json={"identifier": self._identifier, "password": self._password},
                headers={"X-CAP-API-KEY": self._api_key},
            )
            if response.status_code != _RATE_LIMITED:
                break
            if attempt >= self._max_auth_retries or self._clock is None:
                break
            delay = _full_jitter(attempt)
            _log.warning("auth rate-limited (429); retrying in %.1fs", delay)
            self._clock.sleep(delay)
            attempt += 1

        if response.status_code < 200 or response.status_code >= 300:
            raise AuthenticationError(
                f"Capital.com rejected authentication: HTTP {response.status_code}"
            )
        cst = response.headers.get("CST", "")
        security_token = response.headers.get("X-SECURITY-TOKEN", "")
        self._tokens = SessionTokens(cst=cst, security_token=security_token)
        body = response.json()
        streaming_host = body.get("streamingHost")
        self._streaming_host = streaming_host.rstrip("/") if streaming_host else streaming_host
        return self._tokens

    def tokens(self) -> SessionTokens:
        if self._tokens is None:
            raise RuntimeError("Not authenticated — call authenticate() first")
        return self._tokens

    @property
    def streaming_host(self) -> str:
        if self._streaming_host is None:
            raise RuntimeError("Not authenticated — call authenticate() first")
        return self._streaming_host
