from __future__ import annotations

import time
from datetime import datetime, timezone

from domain.ports.clock_port import ClockPort


class SystemClock(ClockPort):
    def utcnow(self) -> datetime:
        return datetime.now(timezone.utc)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
