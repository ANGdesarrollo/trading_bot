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

_T1_ISO = "2023-11-14T22:13:20"
_T1_DT = datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
_T2_ISO = "2023-11-14T22:14:20"
_T2_DT = datetime(2023, 11, 14, 22, 14, 20, tzinfo=timezone.utc)
_T3_ISO = "2023-11-14T22:15:20"
_T3_DT = datetime(2023, 11, 14, 22, 15, 20, tzinfo=timezone.utc)
_T4_ISO = "2023-11-14T22:16:20"


class _FakeSession:
    def tokens(self) -> SessionTokens:
        return SessionTokens(cst="test-cst", security_token="test-xst")


def _price_item(snapshot_utc: str, bid: float = 1.1000, ask: float = 1.1010) -> dict:
    """Mirrors the real /prices record shape verified against Capital demo."""
    return {
        "snapshotTime": snapshot_utc,
        "snapshotTimeUTC": snapshot_utc,
        "openPrice": {"bid": bid, "ask": ask},
        "closePrice": {"bid": bid + 0.0005, "ask": ask + 0.0005},
        "highPrice": {"bid": bid + 0.001, "ask": ask + 0.001},
        "lowPrice": {"bid": bid - 0.001, "ask": ask - 0.001},
        "lastTradedVolume": 42,
    }


def _prices_body(items: list[dict]) -> dict:
    return {
        "prices": items,
        "instrumentType": "CURRENCIES",
        "tickSize": 1e-05,
        "pipPosition": 4,
    }


def _make_adapter(responses: list[dict]) -> tuple[CapitalCandleHistory, FakeHttp]:
    canns = [CannedResponse(status_code=200, json_body=b) for b in responses]
    http = FakeHttp(canns)
    return CapitalCandleHistory(
        session=_FakeSession(),
        http=http,
        base_url=_BASE,
        epic_resolution_map={(_EPIC, _RESOLUTION): 60},
    ), http


def test_cold_backfill_calls_max_param_once_no_price_type():
    items = [_price_item(_T1_ISO), _price_item(_T2_ISO), _price_item(_T3_ISO), _price_item(_T4_ISO)]
    adapter, http = _make_adapter([_prices_body(items)])

    rows = adapter.fetch_history(epic=_EPIC, resolution=_RESOLUTION, count=3, since=None)

    assert len(rows) == 3
    assert len(http.calls) == 1
    _, url, _ = http.calls[0]
    assert "max=4" in url
    assert "resolution=MINUTE" in url
    assert "priceType" not in url


def test_cold_backfill_drops_last_in_formation_record():
    items = [_price_item(_T1_ISO), _price_item(_T2_ISO), _price_item(_T3_ISO)]
    adapter, _ = _make_adapter([_prices_body(items)])

    rows = adapter.fetch_history(epic=_EPIC, resolution=_RESOLUTION, count=2, since=None)

    assert len(rows) == 2
    assert rows[0].candle_start == _T1_DT
    assert rows[1].candle_start == _T2_DT


def test_cold_backfill_returns_candle_rows_with_correct_fields():
    bid, ask = 1.1000, 1.1010
    items = [_price_item(_T1_ISO, bid, ask), _price_item(_T2_ISO, bid, ask)]
    adapter, _ = _make_adapter([_prices_body(items)])

    rows = adapter.fetch_history(epic=_EPIC, resolution=_RESOLUTION, count=1, since=None)

    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, CandleRow)
    assert row.epic == _EPIC
    assert row.resolution == _RESOLUTION
    assert row.candle_start == _T1_DT
    assert row.open_bid == pytest.approx(bid)
    assert row.open_ask == pytest.approx(ask)
    assert row.close_bid == pytest.approx(bid + 0.0005)
    assert row.close_ask == pytest.approx(ask + 0.0005)
    assert row.high_bid == pytest.approx(bid + 0.001)
    assert row.low_ask == pytest.approx(ask - 0.001)


def test_gap_fill_calls_from_to_params_once():
    since = datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
    items = [_price_item(_T2_ISO)]
    adapter, http = _make_adapter([_prices_body(items)])

    adapter.fetch_history(epic=_EPIC, resolution=_RESOLUTION, count=5, since=since)

    assert len(http.calls) == 1
    _, url, _ = http.calls[0]
    assert "from=2023-11-14T22:13:20" in url
    assert "to=" in url
    assert "max=" not in url
    assert "priceType" not in url


def test_gap_fill_returns_rows_without_dropping_last():
    items = [_price_item(_T1_ISO), _price_item(_T2_ISO), _price_item(_T3_ISO)]
    adapter, _ = _make_adapter([_prices_body(items)])

    rows = adapter.fetch_history(epic=_EPIC, resolution=_RESOLUTION, count=10, since=_T1_DT)

    assert len(rows) == 3
    assert rows[2].candle_start == _T3_DT
