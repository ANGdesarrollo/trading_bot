from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CachedSessionRecord:
    cst: str
    security_token: str
    streaming_host: str
    authenticated_at: datetime


class SessionCachePort(ABC):
    @abstractmethod
    def load(self) -> CachedSessionRecord | None:
        """Return the shared session record, or None if none has been stored yet."""

    @abstractmethod
    def store(self, record: CachedSessionRecord) -> None:
        """Write or overwrite the single shared session record."""
