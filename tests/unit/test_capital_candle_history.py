from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain.entities.candle_row import CandleRow
from infrastructure.capital.candle_history import CapitalCandleHistory
from infrastructure.capital.session import SessionTokens
from tests.fakes.fake_http import CannedResponse, FakeHttp

_BASE = "https://demo-api-capital.backend-capital.com/api/v1"
_EPIC = "EURUSD"
_RESOLUTION = "MINUTE"

_T1_MS = 1_700_000_000_000
_T1_DT = datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
_T2_MS = _T1_MS + 60_000
_T2_DT = datetime(2023, 11, 14, 22, 14, 20, tzinfo=timezone.utc)
_T3_MS = _T2_MS + 60_000
_T3_DT = datetime(2023, 11, 14, 22, 15, 20, tzinfo=timezone.utc)
_T4_MS = _T3_MS + 60_000
_T4_DT = datetime(2023, 11, 14, 22, 16, 20, tzinfo=timezone.utc)


class _FakeSession:
    def tokens(self) -> SessionTokens:
        return SessionTokens(cst="test-cst", security_token="test-xst")


def _price_item(t_ms: int, price: float = 1.1000) -> dict:
    return {
        "t": t_ms,
        "o": price,
        "h": price + 0.001,
        "l": price - 0.001,
        "c": price + 0.0005,
    }


def _prices_body(items: list[dict], price_type: str = "bid") -> dict:
    return {"prices": items, "priceType": price_type}


def _make_adapter(bid_responses: list[dict], ask_responses: list[dict]) -> tuple[CapitalCandleHistory, FakeHttp]:
    bid_canns = [CannedResponse(status_code=200, json_body=b) for b in bid_responses]
    ask_canns = [CannedResponse(status_code=200, json_body=a) for a in ask_responses]
    http = FakeHttp(bid_canns + ask_canns)
    return CapitalCandleHistory(
        session=_FakeSession(),
        http=http,
        base_url=_BASE,
        epic_resolution_map={(_EPIC, _RESOLUTION): 60},
    ), http


def test_cold_backfill_calls_max_param():
    # API is called with count+1 so the last in-formation record can be dropped.
    items = [_price_item(_T1_MS), _price_item(_T2_MS), _price_item(_T3_MS), _price_item(_T4_MS)]
    bid_body = _prices_body(items)
    ask_body = _prices_body([_price_item(i["t"], 1.1010) for i in items], "ask")
    adapter, http = _make_adapter([bid_body], [ask_body])

    rows = adapter.fetch_history(_EPIC, _RESOLUTION, count=3, since=None)

    assert len(rows) == 3
    bid_call = http.calls[0]
    ask_call = http.calls[1]
    assert "max=4" in bid_call[1]
    assert "max=4" in ask_call[1]
    assert "resolution=MINUTE" in bid_call[1]


def test_cold_backfill_drops_last_in_formation_record():
    items = [_price_item(_T1_MS), _price_item(_T2_MS), _price_item(_T3_MS)]
    bid_body = _prices_body(items)
    ask_body = _prices_body([_price_item(t["t"], 1.1010) for t in items], "ask")
    adapter, _ = _make_adapter([bid_body], [ask_body])

    rows = adapter.fetch_history(_EPIC, _RESOLUTION, count=2, since=None)

    assert len(rows) == 2
    assert rows[0].candle_start == _T1_DT
    assert rows[1].candle_start == _T2_DT


def test_cold_backfill_returns_candle_rows_with_correct_fields():
    bid_price = 1.1000
    ask_price = 1.1010
    # send count+1=2 records so the last (in-formation) is dropped and 1 remains
    items_bid = [_price_item(_T1_MS, bid_price), _price_item(_T2_MS, bid_price)]
    items_ask = [_price_item(_T1_MS, ask_price), _price_item(_T2_MS, ask_price)]
    bid_body = _prices_body(items_bid)
    ask_body = _prices_body(items_ask, "ask")
    adapter, _ = _make_adapter([bid_body], [ask_body])

    rows = adapter.fetch_history(_EPIC, _RESOLUTION, count=1, since=None)

    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, CandleRow)
    assert row.epic == _EPIC
    assert row.resolution == _RESOLUTION
    assert row.candle_start == _T1_DT
    assert row.open_bid == pytest.approx(bid_price)
    assert row.open_ask == pytest.approx(ask_price)


def test_gap_fill_calls_from_to_params():
    since = datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
    now_approx = "2023-11-14"
    items = [_price_item(_T2_MS)]
    bid_body = _prices_body(items)
    ask_body = _prices_body([_price_item(_T2_MS, 1.1010)], "ask")
    adapter, http = _make_adapter([bid_body], [ask_body])

    rows = adapter.fetch_history(_EPIC, _RESOLUTION, count=5, since=since)

    bid_call = http.calls[0]
    assert "from=2023-11-14T22:13:20" in bid_call[1]
    assert "to=" in bid_call[1]
    assert "max=" not in bid_call[1]


def test_gap_fill_returns_rows_without_dropping_last():
    items = [_price_item(_T1_MS), _price_item(_T2_MS), _price_item(_T3_MS)]
    bid_body = _prices_body(items)
    ask_body = _prices_body([_price_item(i["t"], 1.1010) for i in items], "ask")
    adapter, _ = _make_adapter([bid_body], [ask_body])

    since = _T1_DT
    rows = adapter.fetch_history(_EPIC, _RESOLUTION, count=10, since=since)

    assert len(rows) == 3
