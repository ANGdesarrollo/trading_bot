"""Tests for CapitalBrokerAdapter (T-17, REQ-11, REQ-12).

Scenarios:
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
        json_body={
            "dealId": "order-456",
            "dealStatus": "ACCEPTED",
            "level": 1.0851,
            "affectedDeals": [{"dealId": "position-456", "status": "OPENED"}],
        },
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
        json_body={
            "dealId": "order-777",
            "dealStatus": "OPEN",
            "level": 1.0849,
            "affectedDeals": [{"dealId": "position-777", "status": "OPENED"}],
        },
    )
    http = FakeHttp([post_resp, confirm_resp])
    broker = _make_broker(http)

    result = broker.open_position("EURUSD", signal, size=0.05)

    assert result.order_id == "position-777"
    assert result.status == "OPEN"
    assert result.filled_price == pytest.approx(1.0849)


def test_open_position_order_id_is_opened_affected_deal_not_top_level():
    """order_id must be the POSITION dealId (affectedDeals OPENED), not the
    top-level working-order dealId. /history/activity filters by the position
    dealId; using the order id yields HTTP 400 and the entry never reconciles.
    """
    signal = Signal(
        direction=Direction.BUY,
        sl_distance=0.0020,
        tp_distance=0.0020,
    )
    post_resp = CannedResponse(
        status_code=200,
        headers={},
        json_body={"dealReference": "ref-affected"},
    )
    confirm_resp = CannedResponse(
        status_code=200,
        headers={},
        json_body={
            "dealId": "00000000-555b-1e6e-0481-70d90055311e",
            "dealStatus": "ACCEPTED",
            "level": 0.68925,
            "affectedDeals": [
                {"dealId": "00000000-555b-1e71-0481-70d90055311e", "status": "OPENED"},
            ],
        },
    )
    http = FakeHttp([post_resp, confirm_resp])
    broker = _make_broker(http)

    result = broker.open_position("EURUSD", signal, size=0.01)

    assert result.order_id == "00000000-555b-1e71-0481-70d90055311e"


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
        json_body={
            "dealId": "order-dist",
            "dealStatus": "ACCEPTED",
            "level": 1.0851,
            "affectedDeals": [{"dealId": "position-dist", "status": "OPENED"}],
        },
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
