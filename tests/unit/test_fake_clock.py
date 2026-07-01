from datetime import datetime, timezone

from tests.fakes.fake_clock import FakeClock


def test_sleep_advances_time():
    clock = FakeClock(datetime(2024, 1, 1, 0, 15, 6, tzinfo=timezone.utc))
    clock.sleep(2.0)
    assert clock.utcnow() == datetime(2024, 1, 1, 0, 15, 8, tzinfo=timezone.utc)
