from __future__ import annotations

from datetime import datetime


def seconds_until_next_boundary(now: datetime, period_minutes: int) -> float:
    """Seconds until the next multiple-of-period-minutes UTC boundary.

    When `now` falls exactly on a boundary, returns a full period so the
    loop always moves forward rather than spinning.
    """
    period = period_minutes * 60
    epoch_secs = now.timestamp()
    remainder = epoch_secs % period
    wait = period - remainder
    return float(wait)
