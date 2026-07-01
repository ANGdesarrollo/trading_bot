"""Unit tests for RunTradingCycleUseCase — Slice 3 cutover to CandleStorePort.

Scenarios:
  AC-TC-5 — position already open: candle_store.recent_candles NOT called
  AC-TC-1 — short store (< required_candles): returns None, broker not called
  AC-TC-2 — stale store (newest ts != expected): returns None, single warning, no sleep
  AC-TC-3 — fresh+full store, signal present: evaluate called, open_position called once
  AC-TC-4 — no retry params in constructor
  journal  — record_entry called on successful open, not called on no-signal
  journal  — journal failure does not crash cycle
"""

import inspect
import logging
from datetime import datetime, timezone

import pytest

from application.trading_cycle import RunTradingCycleUseCase
from domain.entities.direction import Direction
from domain.entities.order import OrderResult
from domain.entities.signal import Signal
from domain.ports.strategy_port import StrategyPort
from tests.fakes.fake_broker import FakeBroker
from tests.fakes.fake_candle_store import FakeCandleStore
from tests.fakes.fake_clock import FakeClock
from tests.fakes.fake_journal import FakeJournalPort, RaisingJournalPort

_CLOCK_SEED = datetime(2024, 1, 1, 0, 15, 6, tzinfo=timezone.utc)
_EXPECTED_DECISION_TS = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_STALE_TS = datetime(2023, 12, 31, 23, 45, 0, tzinfo=timezone.utc)

_REQUIRED = 5


class _NoSignalStrategy(StrategyPort):
    required_candles = _REQUIRED

    def evaluate(self, candles):
        return None


class _FixedSignalStrategy(StrategyPort):
    required_candles = _REQUIRED

    def __init__(self, signal: Signal) -> None:
        self._signal = signal

    def evaluate(self, candles):
        return self._signal


def _fresh_candle():
    from domain.entities.candle import Candle
    return Candle(timestamp=_EXPECTED_DECISION_TS, open=1.1, high=1.2, low=1.0, close=1.1)


def _stale_candle():
    from domain.entities.candle import Candle
    return Candle(timestamp=_STALE_TS, open=1.1, high=1.2, low=1.0, close=1.1)


def _make_signal() -> Signal:
    return Signal(direction=Direction.BUY, sl_distance=0.0020, tp_distance=0.0020)


def _make_use_case(
    broker: FakeBroker,
    strategy: StrategyPort,
    candle_store: FakeCandleStore,
    *,
    clock: FakeClock | None = None,
    poll_minutes: int = 15,
    journal=None,
    provider: str = "capital",
) -> RunTradingCycleUseCase:
    if clock is None:
        clock = FakeClock(_CLOCK_SEED)
    if journal is None:
        journal = FakeJournalPort()
    return RunTradingCycleUseCase(
        broker=broker,
        strategy=strategy,
        symbol="EURUSD",
        size=0.01,
        logger=logging.getLogger("test"),
        clock=clock,
        poll_minutes=poll_minutes,
        candle_store=candle_store,
        resolution="MINUTE_15",
        journal=journal,
        provider=provider,
    )


# AC-TC-5
def test_open_position_skips_candle_store():
    broker = FakeBroker(has_open=True)
    store = FakeCandleStore()
    uc = _make_use_case(broker, _NoSignalStrategy(), store)

    result = uc.execute()

    assert result is None
    assert store.recent_candles_calls == []
    assert broker.open_position_calls == []


# AC-TC-1
def test_short_store_returns_none():
    broker = FakeBroker(has_open=False)
    store = FakeCandleStore(candles=[_fresh_candle()] * 2)
    strategy = _NoSignalStrategy()
    uc = _make_use_case(broker, strategy, store)

    result = uc.execute()

    assert result is None
    assert broker.open_position_calls == []


# AC-TC-2
def test_stale_store_returns_none_no_retry(caplog):
    clock = FakeClock(_CLOCK_SEED)
    broker = FakeBroker(has_open=False)
    store = FakeCandleStore(candles=[_stale_candle()] * _REQUIRED)
    strategy = _NoSignalStrategy()
    uc = _make_use_case(broker, strategy, store, clock=clock)

    with caplog.at_level(logging.WARNING):
        result = uc.execute()

    assert result is None
    assert clock.sleep_calls == []
    assert len(store.recent_candles_calls) == 1
    provider, _sym, _res, _count = store.recent_candles_calls[0]
    assert provider == "capital"
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("stale" in m.lower() for m in warnings)
    assert broker.open_position_calls == []


# AC-TC-3
def test_fresh_full_store_calls_strategy_and_broker():
    signal = _make_signal()
    order = OrderResult(order_id="deal-1", status="OPEN", filled_price=1.1001)
    broker = FakeBroker(has_open=False, order_result=order)
    store = FakeCandleStore(candles=[_fresh_candle()] * _REQUIRED)
    strategy = _FixedSignalStrategy(signal)
    uc = _make_use_case(broker, strategy, store)

    result = uc.execute()

    assert result == order
    assert len(broker.open_position_calls) == 1
    sym, sig, size = broker.open_position_calls[0]
    assert sym == "EURUSD"
    assert sig == signal
    assert size == pytest.approx(0.01)


# AC-TC-4
def test_no_retry_params_in_constructor():
    sig = inspect.signature(RunTradingCycleUseCase.__init__)
    params = sig.parameters
    assert "freshness_max_retries" not in params
    assert "freshness_retry_seconds" not in params


def test_no_signal_does_not_place_order():
    broker = FakeBroker(has_open=False)
    store = FakeCandleStore(candles=[_fresh_candle()] * _REQUIRED)
    strategy = _NoSignalStrategy()
    uc = _make_use_case(broker, strategy, store)

    result = uc.execute()

    assert result is None
    assert broker.open_position_calls == []


def test_journal_record_entry_called_after_successful_open():
    signal = _make_signal()
    order = OrderResult(order_id="D1", status="OPEN", filled_price=1.1001)
    broker = FakeBroker(has_open=False, order_result=order)
    store = FakeCandleStore(candles=[_fresh_candle()] * _REQUIRED)
    strategy = _FixedSignalStrategy(signal)
    journal = FakeJournalPort()
    uc = _make_use_case(broker, strategy, store, journal=journal)

    uc.execute()

    assert len(journal.entry_calls) == 1
    assert journal.entry_calls[0].deal_id == "D1"


def test_journal_not_called_when_no_signal():
    broker = FakeBroker(has_open=False)
    store = FakeCandleStore(candles=[_fresh_candle()] * _REQUIRED)
    strategy = _NoSignalStrategy()
    journal = FakeJournalPort()
    uc = _make_use_case(broker, strategy, store, journal=journal)

    uc.execute()

    assert journal.entry_calls == []


def test_journal_failure_does_not_crash_cycle():
    signal = _make_signal()
    order = OrderResult(order_id="D1", status="OPEN", filled_price=1.1001)
    broker = FakeBroker(has_open=False, order_result=order)
    store = FakeCandleStore(candles=[_fresh_candle()] * _REQUIRED)
    strategy = _FixedSignalStrategy(signal)
    uc = _make_use_case(broker, strategy, store, journal=RaisingJournalPort())

    result = uc.execute()

    assert result is not None


def test_configured_provider_flows_to_recent_candles():
    broker = FakeBroker(has_open=False)
    store = FakeCandleStore(candles=[_stale_candle()] * _REQUIRED)
    uc = _make_use_case(broker, _NoSignalStrategy(), store, provider="ic_markets")

    uc.execute()

    provider, _sym, _res, _count = store.recent_candles_calls[0]
    assert provider == "ic_markets"


def test_configured_provider_stamped_on_journal_entry():
    signal = _make_signal()
    order = OrderResult(order_id="D1", status="OPEN", filled_price=1.1001)
    broker = FakeBroker(has_open=False, order_result=order)
    store = FakeCandleStore(candles=[_fresh_candle()] * _REQUIRED)
    journal = FakeJournalPort()
    uc = _make_use_case(
        broker, _FixedSignalStrategy(signal), store, journal=journal, provider="ic_markets"
    )

    uc.execute()

    assert journal.entry_calls[0].provider == "ic_markets"
