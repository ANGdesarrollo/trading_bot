from __future__ import annotations

from datetime import datetime, timezone

import pytest

from infrastructure.capital.history_adapter import CapitalTradeHistory
from infrastructure.capital.session import SessionTokens
from tests.fakes.fake_http import CannedResponse, FakeHttp

_BASE = "https://demo-api-capital.backend-capital.com/api/v1"
_OPENED_AT = datetime(2026, 7, 1, 6, 30, 19, tzinfo=timezone.utc)
_DEAL = "00000000-54a1-644f-0481-70d90055311e"


class _FakeSession:
    def tokens(self) -> SessionTokens:
        return SessionTokens(cst="test-cst", security_token="test-token")


def _make_adapter(responses: list[CannedResponse]) -> CapitalTradeHistory:
    return CapitalTradeHistory(
        session=_FakeSession(),
        http=FakeHttp(responses),
        base_url=_BASE,
    )


def _open_activity(deal_id=_DEAL):
    return {
        "date": "2026-07-01T03:30:19.682",
        "epic": "AUDUSD",
        "dealId": deal_id,
        "source": "USER",
        "type": "POSITION",
        "details": {
            "marketName": "AUD/USD",
            "size": 1000.0,
            "direction": "BUY",
            "level": 0.68903,
        },
    }


def _close_activity(source="TP", close_level=0.68981, deal_id=_DEAL):
    return {
        "date": "2026-07-01T07:50:39.371",
        "epic": "AUDUSD",
        "dealId": deal_id,
        "source": source,
        "type": "POSITION",
        "details": {
            "marketName": "AUD/USD",
            "size": 1000.0,
            "direction": "SELL",
            "level": close_level,
            "openPrice": 0.68903,
        },
    }


def test_activity_request_omits_z_suffix_in_from():
    responses = [CannedResponse(status_code=200, json_body={"activities": []})]
    http = FakeHttp(responses)
    adapter = CapitalTradeHistory(session=_FakeSession(), http=http, base_url=_BASE)

    adapter.closed_trade(_DEAL, opened_at=_OPENED_AT)

    _, url, _ = http.calls[0]
    assert "from=2026-07-01T06:30:19" in url
    assert "Z" not in url


def test_closed_trade_returns_none_when_activity_empty():
    responses = [CannedResponse(status_code=200, json_body={"activities": []})]
    adapter = _make_adapter(responses)
    assert adapter.closed_trade(_DEAL, opened_at=_OPENED_AT) is None


def test_closed_trade_returns_none_when_only_open_activity_present():
    responses = [
        CannedResponse(status_code=200, json_body={"activities": [_open_activity()]}),
    ]
    adapter = _make_adapter(responses)
    assert adapter.closed_trade(_DEAL, opened_at=_OPENED_AT) is None


def test_closed_trade_returns_none_when_no_matching_deal_id():
    responses = [
        CannedResponse(status_code=200, json_body={
            "activities": [_close_activity(deal_id="OTHER")]
        }),
    ]
    adapter = _make_adapter(responses)
    assert adapter.closed_trade(_DEAL, opened_at=_OPENED_AT) is None


def test_closed_trade_computes_pnl_from_price_move_tp_winner():
    responses = [
        CannedResponse(status_code=200, json_body={
            "activities": [_close_activity(source="TP"), _open_activity()]
        }),
    ]
    adapter = _make_adapter(responses)
    result = adapter.closed_trade(_DEAL, opened_at=_OPENED_AT)

    assert result is not None
    assert result.deal_id == _DEAL
    assert result.close_price == pytest.approx(0.68981)
    assert result.realized_pnl == pytest.approx(0.78, abs=1e-9)
    assert result.fees == pytest.approx(0.0)
    assert result.close_source == "TP"


def test_closed_trade_pnl_sign_for_short_winner():
    # Short position (opened SELL) closed by a BUY at a lower price => profit.
    close = _close_activity(source="TP", close_level=0.68800)
    close["details"]["direction"] = "BUY"
    close["details"]["openPrice"] = 0.68900
    responses = [
        CannedResponse(status_code=200, json_body={"activities": [close]}),
    ]
    adapter = _make_adapter(responses)
    result = adapter.closed_trade(_DEAL, opened_at=_OPENED_AT)

    assert result is not None
    assert result.realized_pnl == pytest.approx((0.68900 - 0.68800) * 1000.0, abs=1e-9)


def test_closed_trade_passes_through_close_source():
    for source in ("TP", "SL", "CLOSE_OUT"):
        responses = [
            CannedResponse(status_code=200, json_body={
                "activities": [_close_activity(source=source)]
            }),
        ]
        adapter = _make_adapter(responses)
        result = adapter.closed_trade(_DEAL, opened_at=_OPENED_AT)
        assert result is not None
        assert result.close_source == source
