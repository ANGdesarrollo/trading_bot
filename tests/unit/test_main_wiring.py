"""Tests for build_use_cases wiring — Slice 3: CandleStorePort injection.

AC-TC-4 (constructor): RunTradingCycleUseCase receives candle_store, not broker candles.
No freshness_* params passed anywhere.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SRC = Path(__file__).parents[2] / "src" / "__main__.py"
_spec = importlib.util.spec_from_file_location("trading_engine_main", _SRC)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
build_use_cases = _mod.build_use_cases

from tests.fakes.fake_candle_store import FakeCandleStore
from tests.fakes.fake_journal import FakeJournalPort


def _make_config():
    config = MagicMock()
    config.warmup_bars = 128
    config.base_url = "https://demo-api-capital.backend-capital.com/api/v1"
    config.api_key = "key"
    config.identifier = "user@example.com"
    config.password = "pass"
    config.epics = {"EURUSD": "CS.D.EURUSD.MINI.IP"}
    config.timeframe = "MINUTE_15"
    config.poll_minutes = 15
    config.candle_settle_seconds = 0
    config.symbols = [MagicMock(symbol="EURUSD", epic="CS.D.EURUSD.MINI.IP", size=1000.0)]
    return config


def test_use_case_receives_candle_store_not_broker_candles():
    config = _make_config()
    http = MagicMock()
    clock = MagicMock()
    journal = FakeJournalPort()

    store = FakeCandleStore()
    use_cases, _ = build_use_cases(config, http, clock, journal=journal, candle_store=store)

    assert len(use_cases) == 1
    uc = use_cases[0]
    assert hasattr(uc, "_candle_store")
    assert uc._candle_store is store
    assert not hasattr(uc, "_freshness_max_retries")


def test_use_case_has_no_freshness_params():
    import inspect
    from application.trading_cycle import RunTradingCycleUseCase

    sig = inspect.signature(RunTradingCycleUseCase.__init__)
    params = sig.parameters
    assert "freshness_max_retries" not in params
    assert "freshness_retry_seconds" not in params
