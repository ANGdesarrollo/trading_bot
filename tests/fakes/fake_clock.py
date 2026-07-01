from __future__ import annotations

from datetime import datetime, timedelta

from domain.ports.clock_port import ClockPort


class FakeClock(ClockPort):
    def __init__(self, seeded_time: datetime) -> None:
        self._time = seeded_time
        self.sleep_calls: list[float] = []

    def utcnow(self) -> datetime:
        return self._time

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self._time = self._time + timedelta(seconds=seconds)

    def advance(self, seconds: float) -> None:
        self._time = self._time + timedelta(seconds=seconds)
