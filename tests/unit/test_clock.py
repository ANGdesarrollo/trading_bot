from datetime import datetime, timezone, timedelta

from domain.ports.clock_port import ClockPort
from infrastructure.capital.clock import SystemClock
from tests.fakes.fake_clock import FakeClock


def test_system_clock_returns_utc_aware():
    clock = SystemClock()
    now = clock.utcnow()
    assert now.tzinfo is not None
    assert now.tzinfo == timezone.utc or now.utcoffset() == timedelta(0)


def test_system_clock_within_two_seconds_of_wall_time():
    import time as _time
    wall_before = datetime.now(timezone.utc)
    clock = SystemClock()
    result = clock.utcnow()
    wall_after = datetime.now(timezone.utc)
    assert wall_before <= result <= wall_after + timedelta(seconds=2)


def test_fake_clock_returns_seeded_time():
    seeded = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    clock = FakeClock(seeded)
    assert clock.utcnow() == seeded


def test_fake_clock_result_is_timezone_aware():
    seeded = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    clock = FakeClock(seeded)
    assert clock.utcnow().tzinfo is not None


def test_fake_clock_records_sleep_calls():
    seeded = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    clock = FakeClock(seeded)
    clock.sleep(10.0)
    clock.sleep(5.5)
    assert clock.sleep_calls == [10.0, 5.5]


def test_clock_port_is_abstract():
    import inspect
    assert inspect.isabstract(ClockPort)
