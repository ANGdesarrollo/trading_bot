"""Tests for __main__ loop utilities (T-21, REQ-15, REQ-16, REQ-17).

Scenarios:
  8.1 — seconds_until_next_boundary at 12:07:35 UTC -> 457 s
  8.2 — seconds_until_next_boundary exactly at 12:15:00 UTC -> 900 s
  8.3 — loop with a use case raising RuntimeError: logs exception, does NOT
        terminate, advances to next cycle
"""

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

import importlib.util
import sys
from pathlib import Path

_SRC = Path(__file__).parents[2] / "src" / "__main__.py"
_spec = importlib.util.spec_from_file_location("trading_engine_main", _SRC)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
seconds_until_next_boundary = _mod.seconds_until_next_boundary
run_forever = _mod.run_forever
build_use_case = _mod.build_use_case

from tests.fakes.fake_clock import FakeClock
from tests.fakes.fake_journal import FakeJournalPort


def test_boundary_at_12_07_35():
    now = datetime(2024, 1, 1, 12, 7, 35, tzinfo=timezone.utc)
    secs = seconds_until_next_boundary(now, period_minutes=15)
    # 12:15:00 - 12:07:35 = 7 min 25 sec = 445 s
    # (spec text says 457 but that is a typo — the target 12:15:00 is 445 s away)
    assert secs == pytest.approx(445.0)


def test_boundary_exactly_on_boundary_returns_full_period():
    now = datetime(2024, 1, 1, 12, 15, 0, tzinfo=timezone.utc)
    secs = seconds_until_next_boundary(now, period_minutes=15)
    assert secs == pytest.approx(900.0)


class _StopTest(BaseException):
    """Sentinel raised to break out of run_forever without being caught by its except Exception."""


def test_loop_continues_after_use_case_exception(caplog):
    seeded = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    clock = FakeClock(seeded)

    calls = [0]

    class _FailingUseCaseOnce:
        def execute(self):
            calls[0] += 1
            if calls[0] == 1:
                raise RuntimeError("API timeout")
            raise _StopTest("stop the test loop")

    session_mock = MagicMock()
    use_case = _FailingUseCaseOnce()

    config = MagicMock()
    config.poll_minutes = 15
    config.candle_settle_seconds = 0

    with caplog.at_level(logging.ERROR):
        with pytest.raises(_StopTest):
            run_forever(config, use_case, session_mock, clock)

    assert calls[0] == 2
    assert any("cycle failed" in r.message for r in caplog.records)


def _make_config(warmup_bars: int):
    config = MagicMock()
    config.warmup_bars = warmup_bars
    config.base_url = "https://demo-api-capital.backend-capital.com/api/v1"
    config.api_key = "key"
    config.identifier = "user@example.com"
    config.password = "pass"
    config.epics = {"EURUSD": "CS.D.EURUSD.MINI.IP"}
    config.timeframe = "MINUTE_15"
    config.symbol = "EURUSD"
    config.trade_size = 1000
    config.poll_minutes = 15
    config.freshness_max_retries = 3
    config.freshness_retry_seconds = 2.0
    return config


def test_build_use_case_rejects_warmup_below_strategy_minimum():
    config = _make_config(warmup_bars=64)
    http = MagicMock()
    clock = MagicMock()

    with pytest.raises(SystemExit) as exc_info:
        build_use_case(config, http, clock)

    msg = str(exc_info.value)
    assert "warmup_bars" in msg
    assert "64" in msg


def test_build_use_case_accepts_warmup_at_strategy_minimum():
    config = _make_config(warmup_bars=128)
    http = MagicMock()
    clock = MagicMock()

    use_case, session = build_use_case(config, http, clock, journal=FakeJournalPort())

    assert use_case is not None


def test_build_use_case_accepts_warmup_above_strategy_minimum():
    config = _make_config(warmup_bars=256)
    http = MagicMock()
    clock = MagicMock()

    use_case, session = build_use_case(config, http, clock, journal=FakeJournalPort())

    assert use_case is not None
