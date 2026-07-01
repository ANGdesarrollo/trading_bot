from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest


_UTC_TS = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_row(**overrides):
    from domain.entities.candle_row import CandleRow
    defaults = dict(
        epic="EURUSD",
        resolution="MINUTE_15",
        candle_start=_UTC_TS,
        open_bid=1.08, high_bid=1.09, low_bid=1.07, close_bid=1.085,
        open_ask=1.081, high_ask=1.091, low_ask=1.071, close_ask=1.086,
    )
    return CandleRow(**{**defaults, **overrides})


def test_candle_row_has_all_twelve_fields():
    row = _make_row()
    assert row.provider == "capital"
    assert row.epic == "EURUSD"
    assert row.resolution == "MINUTE_15"
    assert row.candle_start == _UTC_TS
    assert row.open_bid == 1.08
    assert row.high_bid == 1.09
    assert row.low_bid == 1.07
    assert row.close_bid == 1.085
    assert row.open_ask == 1.081
    assert row.high_ask == 1.091
    assert row.low_ask == 1.071
    assert row.close_ask == 1.086


def test_candle_row_provider_defaults_to_capital():
    row = _make_row()
    assert row.provider == "capital"


def test_candle_row_provider_override():
    row = _make_row(provider="ic_markets")
    assert row.provider == "ic_markets"


def test_candle_row_provider_is_first_field():
    from domain.entities.candle_row import CandleRow
    fields = [f.name for f in dataclasses.fields(CandleRow)]
    assert fields[0] == "provider"


def test_candle_row_is_frozen():
    row = _make_row()
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        row.epic = "GBPUSD"  # type: ignore[misc]


def test_candle_row_candle_start_is_utc_aware():
    row = _make_row()
    assert row.candle_start.tzinfo is not None
    assert row.candle_start.tzinfo == timezone.utc


def test_candle_row_naive_datetime_raises():
    naive = datetime(2024, 1, 1, 12, 0, 0)
    with pytest.raises(ValueError, match="UTC"):
        _make_row(candle_start=naive)
