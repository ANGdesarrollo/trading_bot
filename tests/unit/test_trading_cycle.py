"""Unit tests for RunTradingCycleUseCase (T-12).

Scenarios:
  4.1 — position already open: no candle fetch, no evaluate, no placement
  4.2 — no signal: fetches candles, evaluates, no placement
  4.3 — signal present: open_position called exactly once, returns OrderResult
  freshness-1 — fresh candle on first try: no sleep, evaluate runs
  freshness-2 — stale then fresh: one sleep, evaluate runs
  freshness-3 — always stale: 3 sleeps, 4 fetches, WARNING, no order
"""

import logging
from collections.abc import Sequence
from datetime import datetime, timezone

import pytest

from application.trading_cycle import RunTradingCycleUseCase
from domain.entities.candle import Candle
from domain.entities.direction import Direction
from domain.entities.order import OrderResult
from domain.entities.signal import Signal
from domain.ports.broker_port import BrokerPort
from domain.ports.strategy_port import StrategyPort
from tests.fakes.fake_broker import FakeBroker
from tests.fakes.fake_clock import FakeClock
from tests.fakes.fake_journal import FakeJournalPort, RaisingJournalPort

_CLOCK_SEED = datetime(2024, 1, 1, 0, 15, 6, tzinfo=timezone.utc)
_EXPECTED_DECISION_TS = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_STALE_TS = datetime(2023, 12, 31, 23, 45, 0, tzinfo=timezone.utc)


class _NoSignalStrategy(StrategyPort):
    required_candles = 5

    def evaluate(self, candles):
        return None


class _FixedSignalStrategy(StrategyPort):
    required_candles = 5

    def __init__(self, signal: Signal) -> None:
        self._signal = signal

    def evaluate(self, candles):
        return self._signal


class _SequencedBroker(BrokerPort):
    """Returns a different candle list on each call, cycling through the sequence."""

    def __init__(self, candle_sequence: list[list[Candle]]) -> None:
        self._sequence = candle_sequence
        self._call_index = 0
        self.recent_candles_calls: list[tuple[str, int]] = []
        self.open_position_calls = []

    def has_open_position(self, symbol: str) -> bool:
        return False

    def recent_candles(self, symbol: str, count: int) -> Sequence[Candle]:
        self.recent_candles_calls.append((symbol, count))
        candles = self._sequence[min(self._call_index, len(self._sequence) - 1)]
        self._call_index += 1
        return candles

    def open_position(self, symbol: str, signal, size: float):
        self.open_position_calls.append((symbol, signal, size))
        raise RuntimeError("_SequencedBroker: open_position not expected")


def _make_fresh_candles(n: int) -> list[Candle]:
    return [Candle(timestamp=_EXPECTED_DECISION_TS, open=1.1, high=1.2, low=1.0, close=1.1)] * n


def _make_stale_candles(n: int) -> list[Candle]:
    return [Candle(timestamp=_STALE_TS, open=1.1, high=1.2, low=1.0, close=1.1)] * n


def _make_candles(n: int) -> list[Candle]:
    return _make_fresh_candles(n)


def _make_signal() -> Signal:
    return Signal(
        direction=Direction.BUY,
        sl_distance=0.0020,
        tp_distance=0.0020,
    )


def _make_use_case(
    broker,
    strategy,
    *,
    clock: FakeClock | None = None,
    poll_minutes: int = 15,
    freshness_max_retries: int = 3,
    freshness_retry_seconds: float = 2.0,
    journal=None,
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
        freshness_max_retries=freshness_max_retries,
        freshness_retry_seconds=freshness_retry_seconds,
        journal=journal,
    )


def test_position_open_skips_candle_fetch_and_evaluate_and_placement():
    broker = FakeBroker(has_open=True)
    strategy = _NoSignalStrategy()
    uc = _make_use_case(broker, strategy)

    result = uc.execute()

    assert result is None
    assert broker.recent_candles_calls == []
    assert broker.open_position_calls == []


def test_no_signal_does_not_place_order():
    candles = _make_candles(5)
    broker = FakeBroker(has_open=False, candles=candles)
    strategy = _NoSignalStrategy()
    uc = _make_use_case(broker, strategy)

    result = uc.execute()

    assert result is None
    assert broker.recent_candles_calls == [("EURUSD", 5)]
    assert broker.open_position_calls == []


def test_signal_places_exactly_one_order():
    candles = _make_candles(5)
    signal = _make_signal()
    order = OrderResult(order_id="deal-1", status="OPEN", filled_price=1.1001)
    broker = FakeBroker(has_open=False, candles=candles, order_result=order)
    strategy = _FixedSignalStrategy(signal)
    uc = _make_use_case(broker, strategy)

    result = uc.execute()

    assert result == order
    assert len(broker.open_position_calls) == 1
    sym, sig, size = broker.open_position_calls[0]
    assert sym == "EURUSD"
    assert sig == signal
    assert size == pytest.approx(0.01)


def test_fresh_candle_first_try_no_sleep():
    clock = FakeClock(_CLOCK_SEED)
    broker = FakeBroker(has_open=False, candles=_make_fresh_candles(5))
    strategy = _NoSignalStrategy()
    uc = _make_use_case(broker, strategy, clock=clock)

    result = uc.execute()

    assert clock.sleep_calls == []
    assert len(broker.recent_candles_calls) == 1
    assert result is None


def test_stale_then_fresh_retries_once():
    clock = FakeClock(_CLOCK_SEED)
    broker = _SequencedBroker([
        _make_stale_candles(5),
        _make_fresh_candles(5),
    ])
    strategy = _NoSignalStrategy()
    uc = _make_use_case(broker, strategy, clock=clock)

    result = uc.execute()

    assert clock.sleep_calls == [2.0]
    assert len(broker.recent_candles_calls) == 2
    assert result is None


def test_always_stale_skips_boundary(caplog):
    clock = FakeClock(_CLOCK_SEED)
    broker = FakeBroker(has_open=False, candles=_make_stale_candles(5))
    strategy = _NoSignalStrategy()
    uc = _make_use_case(broker, strategy, clock=clock)

    with caplog.at_level(logging.WARNING):
        result = uc.execute()

    assert result is None
    assert len(clock.sleep_calls) == 3
    assert len(broker.recent_candles_calls) == 4
    warning_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    expected_boundary_str = str(_EXPECTED_DECISION_TS)
    assert any(
        "stale" in m.lower() and "3" in m and expected_boundary_str in m
        for m in warning_messages
    )
    assert broker.open_position_calls == []


def test_journal_record_entry_called_after_successful_open():
    candles = _make_candles(5)
    signal = _make_signal()
    order = OrderResult(order_id="D1", status="OPEN", filled_price=1.1001)
    broker = FakeBroker(has_open=False, candles=candles, order_result=order)
    strategy = _FixedSignalStrategy(signal)
    journal = FakeJournalPort()
    uc = _make_use_case(broker, strategy, journal=journal)
    uc.execute()
    assert len(journal.entry_calls) == 1
    assert journal.entry_calls[0].deal_id == "D1"


def test_journal_not_called_when_no_signal():
    candles = _make_candles(5)
    broker = FakeBroker(has_open=False, candles=candles)
    strategy = _NoSignalStrategy()
    journal = FakeJournalPort()
    uc = _make_use_case(broker, strategy, journal=journal)
    uc.execute()
    assert journal.entry_calls == []


def test_journal_failure_does_not_crash_cycle():
    candles = _make_candles(5)
    signal = _make_signal()
    order = OrderResult(order_id="D1", status="OPEN", filled_price=1.1001)
    broker = FakeBroker(has_open=False, candles=candles, order_result=order)
    strategy = _FixedSignalStrategy(signal)
    journal = RaisingJournalPort()
    uc = _make_use_case(broker, strategy, journal=journal)
    result = uc.execute()
    assert result is not None
