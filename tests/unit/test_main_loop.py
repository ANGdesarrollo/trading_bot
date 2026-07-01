"""Tests for __main__ loop utilities (T-21, REQ-15, REQ-16, REQ-17)."""

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock, call

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
build_use_cases = _mod.build_use_cases

from tests.fakes.fake_clock import FakeClock
from tests.fakes.fake_journal import FakeJournalPort


# ---------------------------------------------------------------------------
# seconds_until_next_boundary
# ---------------------------------------------------------------------------

def test_boundary_at_12_07_35():
    now = datetime(2024, 1, 1, 12, 7, 35, tzinfo=timezone.utc)
    secs = seconds_until_next_boundary(now, period_minutes=15)
    assert secs == pytest.approx(445.0)


def test_boundary_exactly_on_boundary_returns_full_period():
    now = datetime(2024, 1, 1, 12, 15, 0, tzinfo=timezone.utc)
    secs = seconds_until_next_boundary(now, period_minutes=15)
    assert secs == pytest.approx(900.0)


# ---------------------------------------------------------------------------
# run_forever — single-use-case backward compat (existing tests)
# ---------------------------------------------------------------------------

class _StopTest(BaseException):
    """Sentinel raised to break out of run_forever without being caught by its except Exception."""


def _make_config(warmup_bars: int):
    config = MagicMock()
    config.warmup_bars = warmup_bars
    config.base_url = "https://demo-api-capital.backend-capital.com/api/v1"
    config.api_key = "key"
    config.identifier = "user@example.com"
    config.password = "pass"
    config.epics = {"EURUSD": "CS.D.EURUSD.MINI.IP"}
    config.timeframe = "MINUTE_15"
    config.poll_minutes = 15
    config.candle_settle_seconds = 0
    config.freshness_max_retries = 3
    config.freshness_retry_seconds = 2.0
    config.symbols = [MagicMock(symbol="EURUSD", epic="CS.D.EURUSD.MINI.IP", size=1000.0)]
    return config


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
            run_forever(config, [use_case], session_mock, clock)

    assert calls[0] == 2
    assert any("cycle failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# build_use_cases — Phase 3 RED tests
# ---------------------------------------------------------------------------

def test_build_use_cases_returns_one_per_symbol():
    config = _make_config(warmup_bars=128)
    from config import SymbolConfig
    config.symbols = [
        SymbolConfig(symbol="EURUSD", epic="CS.D.EURUSD.MINI.IP", size=1000.0),
        SymbolConfig(symbol="USDJPY", epic="CS.D.USDJPY.MINI.IP", size=1000.0),
    ]
    config.epics = {"EURUSD": "CS.D.EURUSD.MINI.IP", "USDJPY": "CS.D.USDJPY.MINI.IP"}
    http = MagicMock()
    clock = MagicMock()
    journal = FakeJournalPort()

    use_cases, session = build_use_cases(config, http, clock, journal=journal)

    assert len(use_cases) == 2


def test_build_use_cases_rejects_warmup_below_strategy_minimum():
    config = _make_config(warmup_bars=64)
    http = MagicMock()
    clock = MagicMock()

    with pytest.raises(SystemExit) as exc_info:
        build_use_cases(config, http, clock)

    msg = str(exc_info.value)
    assert "warmup_bars" in msg
    assert "64" in msg


def test_build_use_cases_accepts_warmup_at_strategy_minimum():
    config = _make_config(warmup_bars=128)
    http = MagicMock()
    clock = MagicMock()

    use_cases, session = build_use_cases(config, http, clock, journal=FakeJournalPort())

    assert use_cases is not None


# ---------------------------------------------------------------------------
# run_forever — multi-symbol Phase 3 RED tests
# ---------------------------------------------------------------------------

def test_run_forever_authenticates_once_per_boundary_with_two_symbols(caplog):
    seeded = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    boundaries_slept = [0]

    class _TwoBoundaryClock(FakeClock):
        def sleep(self, seconds: float) -> None:
            boundaries_slept[0] += 1
            if boundaries_slept[0] > 2:
                raise _StopTest("two boundaries done")
            super().sleep(seconds)

    clock = _TwoBoundaryClock(seeded)

    executions: list[str] = []

    class _RecordingUseCase:
        def __init__(self, symbol: str):
            self.symbol = symbol

        def execute(self):
            executions.append(self.symbol)

    session_mock = MagicMock()
    config = MagicMock()
    config.poll_minutes = 15
    config.candle_settle_seconds = 0

    with pytest.raises(_StopTest):
        run_forever(config, [_RecordingUseCase("EURUSD"), _RecordingUseCase("USDJPY")], session_mock, clock)

    assert session_mock.authenticate.call_count == 2
    assert executions.count("EURUSD") == 2
    assert executions.count("USDJPY") == 2


def test_run_forever_continues_remaining_symbols_after_one_raises(caplog):
    seeded = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    clock = FakeClock(seeded)

    executed = []

    class _FailFirst:
        def execute(self):
            executed.append("fail")
            raise RuntimeError("symbol error")

    class _StopSecond:
        def execute(self):
            executed.append("second")
            raise _StopTest("done after second executes")

    session_mock = MagicMock()
    config = MagicMock()
    config.poll_minutes = 15
    config.candle_settle_seconds = 0

    with caplog.at_level(logging.ERROR):
        with pytest.raises(_StopTest):
            run_forever(config, [_FailFirst(), _StopSecond()], session_mock, clock)

    assert "fail" in executed
    assert "second" in executed
    assert any("cycle failed" in r.message for r in caplog.records)


def test_run_forever_survives_all_symbols_raising(caplog):
    seeded = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    boundaries = [0]

    class _AlwaysFails:
        def execute(self):
            raise RuntimeError("always fails")

    class _StoppingClock(FakeClock):
        def sleep(self, seconds: float) -> None:
            boundaries[0] += 1
            if boundaries[0] >= 2:
                raise _StopTest("two boundaries done")
            super().sleep(seconds)

    clock = _StoppingClock(seeded)
    session_mock = MagicMock()
    config = MagicMock()
    config.poll_minutes = 15
    config.candle_settle_seconds = 0

    with caplog.at_level(logging.ERROR):
        with pytest.raises(_StopTest):
            run_forever(config, [_AlwaysFails(), _AlwaysFails()], session_mock, clock)

    assert any("cycle failed" in r.message for r in caplog.records)
