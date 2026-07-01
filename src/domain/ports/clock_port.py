from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime


class ClockPort(ABC):
    @abstractmethod
    def utcnow(self) -> datetime:
        """Timezone-aware current UTC time."""

    @abstractmethod
    def sleep(self, seconds: float) -> None:
        """Block for `seconds`."""
