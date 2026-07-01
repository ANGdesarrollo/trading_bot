from __future__ import annotations

from dataclasses import dataclass


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
    ) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._identifier = identifier
        self._password = password
        self._tokens: SessionTokens | None = None

    def authenticate(self) -> SessionTokens:
        response = self._http.post(
            f"{self._base_url}/session",
            json={"identifier": self._identifier, "password": self._password},
            headers={"X-CAP-API-KEY": self._api_key},
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise AuthenticationError(
                f"Capital.com rejected authentication: HTTP {response.status_code}"
            )
        cst = response.headers.get("CST", "")
        security_token = response.headers.get("X-SECURITY-TOKEN", "")
        self._tokens = SessionTokens(cst=cst, security_token=security_token)
        return self._tokens

    def tokens(self) -> SessionTokens:
        if self._tokens is None:
            raise RuntimeError("Not authenticated — call authenticate() first")
        return self._tokens
