from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, call

from infrastructure.capital._pair_buffer import PairBuffer

_EPIC = "EURUSD"
_RES = "MINUTE"
_T_MS = 1_700_000_000_000
_T_DT = datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)

_PERIOD_MS = 60_000


def _bid_event(t_ms: int = _T_MS, epic: str = _EPIC) -> dict:
    return {
        "destination": "ohlc.event",
        "payload": {
            "epic": epic,
            "resolution": _RES,
            "t": t_ms,
            "o": 1.1000,
            "h": 1.1010,
            "l": 1.0990,
            "c": 1.1005,
            "priceType": "bid",
        },
    }


def _ask_event(t_ms: int = _T_MS, epic: str = _EPIC) -> dict:
    return {
        "destination": "ohlc.event",
        "payload": {
            "epic": epic,
            "resolution": _RES,
            "t": t_ms,
            "o": 1.1010,
            "h": 1.1020,
            "l": 1.1000,
            "c": 1.1015,
            "priceType": "ask",
        },
    }


def test_bid_only_does_not_call_upsert():
    upsert = MagicMock()
    buf = PairBuffer(period_ms_map={(_EPIC, _RES): _PERIOD_MS})

    buf.on_event(_bid_event(), upsert)

    upsert.assert_not_called()


def test_ask_only_does_not_call_upsert():
    upsert = MagicMock()
    buf = PairBuffer(period_ms_map={(_EPIC, _RES): _PERIOD_MS})

    buf.on_event(_ask_event(), upsert)

    upsert.assert_not_called()


def test_bid_then_ask_calls_upsert_once_with_correct_row():
    upsert = MagicMock()
    buf = PairBuffer(period_ms_map={(_EPIC, _RES): _PERIOD_MS})

    buf.on_event(_bid_event(), upsert)
    buf.on_event(_ask_event(), upsert)

    upsert.assert_called_once()
    row = upsert.call_args[0][0]
    assert row.epic == _EPIC
    assert row.resolution == _RES
    assert row.candle_start == _T_DT
    assert row.open_bid == 1.1000
    assert row.open_ask == 1.1010


def test_ask_then_bid_calls_upsert_once():
    upsert = MagicMock()
    buf = PairBuffer(period_ms_map={(_EPIC, _RES): _PERIOD_MS})

    buf.on_event(_ask_event(), upsert)
    buf.on_event(_bid_event(), upsert)

    upsert.assert_called_once()
    row = upsert.call_args[0][0]
    assert row.open_bid == 1.1000
    assert row.open_ask == 1.1010


def test_pair_evicted_after_both_sides_received():
    upsert = MagicMock()
    buf = PairBuffer(period_ms_map={(_EPIC, _RES): _PERIOD_MS})

    buf.on_event(_bid_event(), upsert)
    buf.on_event(_ask_event(), upsert)
    # second ask for the same key should NOT trigger another upsert
    buf.on_event(_ask_event(), upsert)

    assert upsert.call_count == 1


def test_two_epics_buffered_independently_only_matched_writes():
    upsert = MagicMock()
    buf = PairBuffer(period_ms_map={
        (_EPIC, _RES): _PERIOD_MS,
        ("GBPUSD", _RES): _PERIOD_MS,
    })

    buf.on_event(_bid_event(epic=_EPIC), upsert)
    buf.on_event(_bid_event(epic="GBPUSD"), upsert)

    upsert.assert_not_called()

    buf.on_event(_ask_event(epic=_EPIC), upsert)

    upsert.assert_called_once()
    row = upsert.call_args[0][0]
    assert row.epic == _EPIC


def test_epoch_ms_conversion():
    upsert = MagicMock()
    buf = PairBuffer(period_ms_map={(_EPIC, _RES): _PERIOD_MS})

    buf.on_event(_bid_event(t_ms=_T_MS), upsert)
    buf.on_event(_ask_event(t_ms=_T_MS), upsert)

    row = upsert.call_args[0][0]
    assert row.candle_start == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)


def test_staleness_eviction_drops_partial_before_upsert():
    upsert = MagicMock()
    buf = PairBuffer(period_ms_map={(_EPIC, _RES): _PERIOD_MS})

    old_t = _T_MS
    new_t = _T_MS + 5 * _PERIOD_MS  # 5 periods ahead > 4*period staleness threshold

    buf.on_event(_bid_event(t_ms=old_t), upsert)

    # new event advances the newest_t; old partial should be evicted
    buf.on_event(_bid_event(t_ms=new_t), upsert)

    # now completing the old_t ask should NOT emit (already evicted)
    buf.on_event(_ask_event(t_ms=old_t), upsert)

    upsert.assert_not_called()


def test_non_stale_partial_not_evicted():
    upsert = MagicMock()
    buf = PairBuffer(period_ms_map={(_EPIC, _RES): _PERIOD_MS})

    t1 = _T_MS
    t2 = _T_MS + 2 * _PERIOD_MS  # only 2 periods ahead, within staleness window

    buf.on_event(_bid_event(t_ms=t1), upsert)
    buf.on_event(_bid_event(t_ms=t2), upsert)
    buf.on_event(_ask_event(t_ms=t1), upsert)

    upsert.assert_called_once()
    row = upsert.call_args[0][0]
    assert row.candle_start == datetime.fromtimestamp(t1 / 1000, tz=timezone.utc)


def test_provider_defaults_to_capital_on_emitted_row():
    upsert = MagicMock()
    buf = PairBuffer(period_ms_map={(_EPIC, _RES): _PERIOD_MS})

    buf.on_event(_bid_event(), upsert)
    buf.on_event(_ask_event(), upsert)

    row = upsert.call_args[0][0]
    assert row.provider == "capital"


def test_provider_stamped_from_constructor():
    upsert = MagicMock()
    buf = PairBuffer(period_ms_map={(_EPIC, _RES): _PERIOD_MS}, provider="ic_markets")

    buf.on_event(_bid_event(), upsert)
    buf.on_event(_ask_event(), upsert)

    row = upsert.call_args[0][0]
    assert row.provider == "ic_markets"
