"""Tests for CapitalBrokerAdapter (T-17, REQ-11, REQ-12).

Scenarios:
  6.1 — recent_candles: strips in-progress candle, returns N oldest-first
  6.2 — open_position: sends correct body, resolves confirms, returns OrderResult
        rejected dealStatus raises OrderRejectedError
  6.3 — has_open_position: True when epic matches, False when absent
"""

import pytest

from domain.entities.direction import Direction
from domain.entities.signal import Signal
from infrastructure.capital.broker import CapitalBrokerAdapter, OrderRejectedError
from infrastructure.capital.session import CapitalSession, SessionTokens
from tests.fakes.fake_http import CannedResponse, FakeHttp


def _make_candle_record(o=1.10, h=1.12, l=1.08, c=1.11):
    return {
        "snapshotTimeUTC": "2024-01-01T12:00:00",
        "openPrice": {"bid": o, "ask": o + 0.0001},
        "highPrice": {"bid": h, "ask": h + 0.0001},
        "lowPrice": {"bid": l, "ask": l + 0.0001},
        "closePrice": {"bid": c, "ask": c + 0.0001},
    }


def _make_session_with_tokens(http, tokens: SessionTokens) -> CapitalSession:
    session = CapitalSession.__new__(CapitalSession)
    session._http = http
    session._tokens = tokens
    return session


_BASE_URL = "https://demo-api-capital.backend-capital.com/api/v1"


def _make_broker(http):
    tokens = SessionTokens(cst="cst-1", security_token="xst-1")
    session = _make_session_with_tokens(http, tokens)
    return CapitalBrokerAdapter(
        session=session,
        http=http,
        base_url=_BASE_URL,
        epics={"EURUSD": "CS.D.EURUSD.MINI.IP"},
        timeframe="MINUTE_15",
    )


def test_recent_candles_strips_last_in_progress_candle():
    records = [_make_candle_record(c=1.10 + i * 0.001) for i in range(5)]
    response = CannedResponse(
        status_code=200,
        headers={},
        json_body={"prices": records},
    )
    http = FakeHttp([response])
    broker = _make_broker(http)

    candles = broker.recent_candles("EURUSD", 4)

    assert len(candles) == 4
    assert candles[-1].close == pytest.approx(records[-2]["closePrice"]["bid"], abs=1e-9)


def test_recent_candles_oldest_first():
    records = [_make_candle_record(c=1.10 + i * 0.001) for i in range(5)]
    response = CannedResponse(
        status_code=200,
        headers={},
        json_body={"prices": records},
    )
    http = FakeHttp([response])
    broker = _make_broker(http)

    candles = broker.recent_candles("EURUSD", 4)

    closes = [c.close for c in candles]
    assert closes == sorted(closes)


def test_recent_candles_requests_count_plus_one():
    records = [_make_candle_record() for _ in range(5)]
    response = CannedResponse(status_code=200, headers={}, json_body={"prices": records})
    http = FakeHttp([response])
    broker = _make_broker(http)

    broker.recent_candles("EURUSD", 4)

    _, url, kwargs = http.calls[0]
    assert "max=5" in url


def test_malformed_ohlc_raises_via_candle_invariant():
    bad_record = {
        "snapshotTimeUTC": "2024-01-01T12:00:00",
        "openPrice": {"bid": 1.20, "ask": 1.21},
        "highPrice": {"bid": 1.05, "ask": 1.06},
        "lowPrice": {"bid": 1.10, "ask": 1.11},
        "closePrice": {"bid": 1.15, "ask": 1.16},
    }
    good_records = [_make_candle_record() for _ in range(4)]
    records = [bad_record] + good_records
    response = CannedResponse(status_code=200, headers={}, json_body={"prices": records})
    http = FakeHttp([response])
    broker = _make_broker(http)

    with pytest.raises(ValueError):
        broker.recent_candles("EURUSD", 4)


def test_open_position_posts_correct_body():
    signal = Signal(
        direction=Direction.BUY,
        sl_distance=0.0020,
        tp_distance=0.0020,
    )
    post_resp = CannedResponse(
        status_code=200,
        headers={},
        json_body={"dealReference": "ref-123"},
    )
    confirm_resp = CannedResponse(
        status_code=200,
        headers={},
        json_body={"dealId": "deal-456", "dealStatus": "ACCEPTED", "level": 1.0851},
    )
    http = FakeHttp([post_resp, confirm_resp])
    broker = _make_broker(http)

    result = broker.open_position("EURUSD", signal, size=0.01)

    _, url, kwargs = http.calls[0]
    body = kwargs["json"]
    assert body["epic"] == "CS.D.EURUSD.MINI.IP"
    assert body["direction"] == "BUY"
    assert body["size"] == pytest.approx(0.01)
    assert body["stopDistance"] == pytest.approx(0.0020)
    assert body["profitDistance"] == pytest.approx(0.0020)


def test_open_position_returns_order_result_from_confirms():
    signal = Signal(
        direction=Direction.SELL,
        sl_distance=0.0020,
        tp_distance=0.0020,
    )
    post_resp = CannedResponse(
        status_code=200,
        headers={},
        json_body={"dealReference": "ref-999"},
    )
    confirm_resp = CannedResponse(
        status_code=200,
        headers={},
        json_body={"dealId": "deal-777", "dealStatus": "OPEN", "level": 1.0849},
    )
    http = FakeHttp([post_resp, confirm_resp])
    broker = _make_broker(http)

    result = broker.open_position("EURUSD", signal, size=0.05)

    assert result.order_id == "deal-777"
    assert result.status == "OPEN"
    assert result.filled_price == pytest.approx(1.0849)


def test_open_position_rejected_raises_order_rejected_error():
    signal = Signal(
        direction=Direction.BUY,
        sl_distance=0.0020,
        tp_distance=0.0020,
    )
    post_resp = CannedResponse(
        status_code=200,
        headers={},
        json_body={"dealReference": "ref-bad"},
    )
    confirm_resp = CannedResponse(
        status_code=200,
        headers={},
        json_body={"dealId": "deal-bad", "dealStatus": "REJECTED", "level": 0.0},
    )
    http = FakeHttp([post_resp, confirm_resp])
    broker = _make_broker(http)

    with pytest.raises(OrderRejectedError):
        broker.open_position("EURUSD", signal, size=0.01)


def test_open_position_sends_stop_distance_not_level():
    signal = Signal(
        direction=Direction.BUY,
        sl_distance=0.0020,
        tp_distance=0.0040,
    )
    post_resp = CannedResponse(
        status_code=200,
        headers={},
        json_body={"dealReference": "ref-dist"},
    )
    confirm_resp = CannedResponse(
        status_code=200,
        headers={},
        json_body={"dealId": "deal-dist", "dealStatus": "ACCEPTED", "level": 1.0851},
    )
    http = FakeHttp([post_resp, confirm_resp])
    broker = _make_broker(http)

    broker.open_position("EURUSD", signal, size=0.01)

    _, url, kwargs = http.calls[0]
    body = kwargs["json"]
    assert "stopDistance" in body
    assert "profitDistance" in body
    assert "stopLevel" not in body
    assert "profitLevel" not in body
    assert body["stopDistance"] == pytest.approx(0.0020)
    assert body["profitDistance"] == pytest.approx(0.0040)


def test_has_open_position_true_when_epic_matches():
    response = CannedResponse(
        status_code=200,
        headers={},
        json_body={
            "positions": [
                {"position": {"size": 0.01}, "market": {"epic": "CS.D.EURUSD.MINI.IP"}},
            ]
        },
    )
    http = FakeHttp([response])
    broker = _make_broker(http)

    assert broker.has_open_position("EURUSD") is True


def test_has_open_position_false_when_no_positions():
    response = CannedResponse(
        status_code=200,
        headers={},
        json_body={"positions": []},
    )
    http = FakeHttp([response])
    broker = _make_broker(http)

    assert broker.has_open_position("EURUSD") is False


def test_has_open_position_false_when_epic_does_not_match():
    response = CannedResponse(
        status_code=200,
        headers={},
        json_body={
            "positions": [
                {"position": {"size": 0.01}, "market": {"epic": "CS.D.GBPUSD.MINI.IP"}},
            ]
        },
    )
    http = FakeHttp([response])
    broker = _make_broker(http)

    assert broker.has_open_position("EURUSD") is False
