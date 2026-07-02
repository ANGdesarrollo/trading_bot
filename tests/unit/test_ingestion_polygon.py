from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

from domain.entities.candle_row import CandleRow
from tests.fakes.fake_candle_store import FakeCandleStore

_SRC = Path(__file__).parents[2] / "src" / "ingestion_polygon.py"
_spec = importlib.util.spec_from_file_location("ingestion_polygon", _SRC)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
run_polygon_ingestion_forever = _mod.run_polygon_ingestion_forever

# Clock seeded a few seconds after a 15-min boundary; the just-closed candle
# opened one period earlier.
_SEED = datetime(2026, 7, 1, 22, 45, 4, tzinfo=timezone.utc)
_EXPECTED_START = datetime(2026, 7, 1, 22, 30, 0, tzinfo=timezone.utc)


class _StopLoop(BaseException):
    pass


class _FakeClock:
    def __init__(self, seeded):
        self._t = seeded
        self.sleep_calls = []

    def utcnow(self):
        return self._t

    def sleep(self, seconds):
        self.sleep_calls.append(seconds)
        self._t += timedelta(seconds=seconds)
        # stop once we've done one boundary pass (a long boundary sleep happened)
        if seconds > 100:
            raise _StopLoop


def _row(epic, start):
    return CandleRow(
        provider="polygon", epic=epic, resolution="MINUTE_15", candle_start=start,
        open_bid=1.1, high_bid=1.2, low_bid=1.0, close_bid=1.15,
        open_ask=1.1, high_ask=1.2, low_ask=1.0, close_ask=1.15,
    )


class _History:
    def __init__(self, rows_by_symbol):
        self._rows = rows_by_symbol
        self.calls = []

    def fetch_history(self, *, provider, epic, resolution, count, since):
        self.calls.append(epic)
        return self._rows.get(epic, [])


def test_ingests_expected_candle_for_each_symbol():
    history = _History({
        "EURUSD": [_row("EURUSD", _EXPECTED_START)],
        "USDJPY": [_row("USDJPY", _EXPECTED_START)],
    })
    store = FakeCandleStore()
    # seed just BEFORE a boundary so the first sleep is the long boundary wait
    clock = _FakeClock(datetime(2026, 7, 1, 22, 44, 50, tzinfo=timezone.utc))

    try:
        run_polygon_ingestion_forever(
            history=history, store=store, clock=clock,
            symbols=["EURUSD", "USDJPY"], resolution="MINUTE_15",
            period_minutes=15, required_candles=128, provider="polygon")
    except _StopLoop:
        pass

    assert len(store.upsert_calls) == 2
    assert {c.epic for c in store.upsert_calls} == {"EURUSD", "USDJPY"}


def test_forming_candle_is_discarded_only_closed_persisted():
    # Polygon returns the still-forming bar (start == boundary, not yet closed)
    # as the newest result. It must NOT be persisted; only the just-closed bar.
    forming_start = _EXPECTED_START + timedelta(minutes=15)  # current bar, not closed
    history = _History({
        "EURUSD": [
            _row("EURUSD", forming_start),      # rows[0] = forming, must be dropped
            _row("EURUSD", _EXPECTED_START),    # the closed one we want
        ],
    })
    store = FakeCandleStore()
    clock = _FakeClock(datetime(2026, 7, 1, 22, 44, 50, tzinfo=timezone.utc))

    try:
        run_polygon_ingestion_forever(
            history=history, store=store, clock=clock,
            symbols=["EURUSD"], resolution="MINUTE_15",
            period_minutes=15, required_candles=128, provider="polygon")
    except _StopLoop:
        pass

    starts = [c.candle_start for c in store.upsert_calls]
    assert forming_start not in starts       # forming bar NOT persisted
    assert _EXPECTED_START in starts          # closed bar persisted


def test_retries_until_candle_is_published():
    class _LateHistory(_History):
        def __init__(self):
            super().__init__({})
            self._n = 0

        def fetch_history(self, *, provider, epic, resolution, count, since):
            self.calls.append(epic)
            self._n += 1
            # not published for the first 2 tries, then appears
            if self._n >= 3:
                return [_row(epic, _EXPECTED_START)]
            return [_row(epic, _EXPECTED_START - timedelta(minutes=15))]  # stale

    history = _LateHistory()
    store = FakeCandleStore()
    clock = _FakeClock(datetime(2026, 7, 1, 22, 44, 50, tzinfo=timezone.utc))

    try:
        run_polygon_ingestion_forever(
            history=history, store=store, clock=clock,
            symbols=["EURUSD"], resolution="MINUTE_15",
            period_minutes=15, required_candles=128, provider="polygon")
    except _StopLoop:
        pass

    # got the candle on the 3rd fetch, after retrying
    assert len(store.upsert_calls) == 1
    assert store.upsert_calls[0].candle_start == _EXPECTED_START
    assert history.calls.count("EURUSD") == 3
