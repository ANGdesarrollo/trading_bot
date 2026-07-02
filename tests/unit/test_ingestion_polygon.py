from __future__ import annotations

import sys
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from domain.entities.candle_row import CandleRow
from tests.fakes.fake_candle_store import FakeCandleStore

_SRC = Path(__file__).parents[2] / "src" / "ingestion_polygon.py"
_spec = importlib.util.spec_from_file_location("ingestion_polygon", _SRC)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
run_polygon_ingestion_forever = _mod.run_polygon_ingestion_forever

_T = datetime(2026, 7, 1, 23, 45, 0, tzinfo=timezone.utc)


class _StopLoop(BaseException):
    pass


class _FakeClock:
    def __init__(self):
        self.sleep_calls = []

    def sleep(self, seconds):
        self.sleep_calls.append(seconds)
        raise _StopLoop  # stop after one full pass


class _FakeHistory:
    def __init__(self, rows_by_symbol):
        self._rows = rows_by_symbol
        self.calls = []

    def fetch_history(self, *, provider, epic, resolution, count, since):
        self.calls.append((provider, epic, resolution, count))
        return self._rows.get(epic, [])


def _row(epic):
    return CandleRow(
        provider="polygon", epic=epic, resolution="MINUTE_15", candle_start=_T,
        open_bid=1.1, high_bid=1.2, low_bid=1.0, close_bid=1.15,
        open_ask=1.1, high_ask=1.2, low_ask=1.0, close_ask=1.15,
    )


def test_fetches_and_upserts_each_symbol():
    history = _FakeHistory({"EURUSD": [_row("EURUSD")], "USDJPY": [_row("USDJPY")]})
    store = FakeCandleStore()
    clock = _FakeClock()

    try:
        run_polygon_ingestion_forever(
            history=history, store=store, clock=clock,
            symbols=["EURUSD", "USDJPY"], resolution="MINUTE_15",
            required_candles=128, poll_seconds=60, provider="polygon")
    except _StopLoop:
        pass

    assert [c[1] for c in history.calls] == ["EURUSD", "USDJPY"]
    assert len(store.upsert_calls) == 2
    assert clock.sleep_calls == [60]


def test_one_symbol_failing_does_not_stop_others():
    class _PartialHistory(_FakeHistory):
        def fetch_history(self, *, provider, epic, resolution, count, since):
            self.calls.append((provider, epic, resolution, count))
            if epic == "EURUSD":
                raise RuntimeError("polygon down for EURUSD")
            return [_row(epic)]

    history = _PartialHistory({})
    store = FakeCandleStore()
    clock = _FakeClock()

    try:
        run_polygon_ingestion_forever(
            history=history, store=store, clock=clock,
            symbols=["EURUSD", "USDJPY"], resolution="MINUTE_15",
            required_candles=128, poll_seconds=60, provider="polygon")
    except _StopLoop:
        pass

    # EURUSD failed, USDJPY still persisted
    assert len(store.upsert_calls) == 1
    assert store.upsert_calls[0].epic == "USDJPY"
