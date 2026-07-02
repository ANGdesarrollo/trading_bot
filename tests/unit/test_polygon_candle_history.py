from __future__ import annotations

from datetime import datetime, timezone

from infrastructure.polygon.candle_history import PolygonCandleHistory
from tests.fakes.fake_http import CannedResponse, FakeHttp

_BASE = "https://api.massive.com"
_T1_MS = 1782949500000  # 2026-07-01 23:45:00 UTC
_T2_MS = 1782948600000  # 2026-07-01 23:30:00 UTC


def _bar(t_ms: int, o=1.1000, h=1.1010, l=1.0990, c=1.1005) -> dict:
    return {"v": 90, "vw": c, "o": o, "h": h, "l": l, "c": c, "t": t_ms, "n": 90}


def _body(bars: list[dict]) -> dict:
    return {
        "ticker": "C:EURUSD",
        "queryCount": 1440,
        "resultsCount": len(bars),
        "adjusted": True,
        "status": "OK",
        "results": bars,
    }


def _make(bars: list[dict]) -> tuple[PolygonCandleHistory, FakeHttp]:
    http = FakeHttp([CannedResponse(status_code=200, json_body=_body(bars))])
    adapter = PolygonCandleHistory(http=http, base_url=_BASE, api_key="test-key")
    return adapter, http


def test_maps_bars_to_candle_rows():
    adapter, _ = _make([_bar(_T2_MS), _bar(_T1_MS)])

    rows = adapter.fetch_history(
        provider="polygon", epic="EURUSD", resolution="MINUTE_15", count=5, since=None)

    assert len(rows) == 2
    r = rows[0]
    assert r.provider == "polygon"
    assert r.epic == "EURUSD"
    assert r.resolution == "MINUTE_15"
    assert r.candle_start.tzinfo is not None


def test_single_ohlc_maps_to_equal_bid_and_ask():
    adapter, _ = _make([_bar(_T1_MS, o=1.2, h=1.3, l=1.1, c=1.25)])

    rows = adapter.fetch_history(
        provider="polygon", epic="EURUSD", resolution="MINUTE_15", count=1, since=None)

    r = rows[0]
    # Polygon gives one OHLC; bid==ask so mid=(bid+ask)/2 == polygon price
    assert r.open_bid == r.open_ask == 1.2
    assert r.high_bid == r.high_ask == 1.3
    assert r.low_bid == r.low_ask == 1.1
    assert r.close_bid == r.close_ask == 1.25


def test_timestamp_converted_to_utc():
    adapter, _ = _make([_bar(_T1_MS)])

    rows = adapter.fetch_history(
        provider="polygon", epic="EURUSD", resolution="MINUTE_15", count=1, since=None)

    assert rows[0].candle_start == datetime(2026, 7, 1, 23, 45, 0, tzinfo=timezone.utc)


def test_request_uses_massive_ticker_resolution_and_high_limit():
    adapter, http = _make([_bar(_T1_MS)])

    adapter.fetch_history(
        provider="polygon", epic="EURUSD", resolution="MINUTE_15", count=5, since=None)

    _method, url, kwargs = http.calls[0]
    assert "/v2/aggs/ticker/C:EURUSD/range/15/minute/" in url
    params = kwargs.get("params", {})
    assert str(params.get("limit")) == "5000"
    assert params.get("apiKey") == "test-key"


def test_empty_results_returns_empty():
    adapter, _ = _make([])

    rows = adapter.fetch_history(
        provider="polygon", epic="EURUSD", resolution="MINUTE_15", count=5, since=None)

    assert list(rows) == []
