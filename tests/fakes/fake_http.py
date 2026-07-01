"""FakeHttp — a requests.Session drop-in for unit tests.

Configured with a queue of canned responses (each specifying status_code,
headers, and a JSON body). Calls to get/post consume from the queue in order
and record the call so tests can assert on them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CannedResponse:
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    json_body: Any = None

    def json(self) -> Any:
        return self.json_body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise _FakeHttpError(self.status_code)


class _FakeHttpError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.response = self
        super().__init__(f"HTTP {status_code}")


class FakeHttp:
    """Minimal requests.Session stand-in returning pre-configured responses."""

    def __init__(self, responses: list[CannedResponse]) -> None:
        self._queue = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    def _next(self, method: str, url: str, **kwargs) -> CannedResponse:
        self.calls.append((method, url, kwargs))
        if not self._queue:
            raise RuntimeError(
                f"FakeHttp: no more canned responses for {method} {url}"
            )
        return self._queue.pop(0)

    def get(self, url: str, **kwargs) -> CannedResponse:
        return self._next("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> CannedResponse:
        return self._next("POST", url, **kwargs)
