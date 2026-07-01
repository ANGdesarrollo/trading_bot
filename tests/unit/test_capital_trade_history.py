from __future__ import annotations

from datetime import datetime, timezone

import pytest

from infrastructure.capital.history_adapter import CapitalTradeHistory
from infrastructure.capital.session import SessionTokens
from tests.fakes.fake_http import CannedResponse, FakeHttp

_BASE = "https://demo-api-capital.backend-capital.com/api/v1"
_OPENED_AT = datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc)


class _FakeSession:
    def tokens(self) -> SessionTokens:
        return SessionTokens(cst="test-cst", security_token="test-token")


def _make_adapter(responses: list[CannedResponse]) -> CapitalTradeHistory:
    return CapitalTradeHistory(
        session=_FakeSession(),
        http=FakeHttp(responses),
        base_url=_BASE,
    )


def test_closed_trade_returns_none_when_activity_empty():
    responses = [
        CannedResponse(status_code=200, json_body={"activities": []}),
    ]
    adapter = _make_adapter(responses)
    result = adapter.closed_trade("D1", opened_at=_OPENED_AT)
    assert result is None


def test_closed_trade_returns_none_when_no_matching_deal_id():
    responses = [
        CannedResponse(status_code=200, json_body={
            "activities": [
                {"dealId": "OTHER", "type": "POSITION_CLOSED",
                 "date": "2024-01-01T10:00:00Z", "level": "1.1019"}
            ]
        }),
    ]
    adapter = _make_adapter(responses)
    result = adapter.closed_trade("D1", opened_at=_OPENED_AT)
    assert result is None


def test_closed_trade_returns_closed_trade_on_hit():
    responses = [
        CannedResponse(status_code=200, json_body={
            "activities": [
                {"dealId": "D1", "type": "POSITION_CLOSED", "source": "USER",
                 "date": "2024-01-01T10:00:00Z", "level": "1.1019"}
            ]
        }),
        CannedResponse(status_code=200, json_body={
            "transactions": [
                {"reference": "D1", "profitAndLoss": "19.0", "commission": "1.0"}
            ]
        }),
    ]
    adapter = _make_adapter(responses)
    result = adapter.closed_trade("D1", opened_at=_OPENED_AT)
    assert result is not None
    assert result.deal_id == "D1"
    assert result.realized_pnl == pytest.approx(19.0)
    assert result.fees == pytest.approx(1.0)
    assert result.close_source == "USER"


def test_closed_trade_returns_raw_system_source():
    responses = [
        CannedResponse(status_code=200, json_body={
            "activities": [
                {"dealId": "D1", "type": "POSITION_CLOSED", "source": "SYSTEM",
                 "date": "2024-01-01T10:00:00Z", "level": "1.0980"}
            ]
        }),
        CannedResponse(status_code=200, json_body={
            "transactions": [
                {"reference": "D1", "profitAndLoss": "-20.0", "commission": "1.0"}
            ]
        }),
    ]
    adapter = _make_adapter(responses)
    result = adapter.closed_trade("D1", opened_at=_OPENED_AT)
    assert result is not None
    assert result.close_source == "SYSTEM"


def test_closed_trade_maps_close_out_source():
    responses = [
        CannedResponse(status_code=200, json_body={
            "activities": [
                {"dealId": "D1", "type": "POSITION_CLOSED", "source": "CLOSE_OUT",
                 "date": "2024-01-01T10:00:00Z", "level": "1.0950"}
            ]
        }),
        CannedResponse(status_code=200, json_body={
            "transactions": [
                {"reference": "D1", "profitAndLoss": "-50.0", "commission": "1.0"}
            ]
        }),
    ]
    adapter = _make_adapter(responses)
    result = adapter.closed_trade("D1", opened_at=_OPENED_AT)
    assert result is not None
    assert result.close_source == "CLOSE_OUT"


def test_closed_trade_returns_none_when_transaction_not_found():
    responses = [
        CannedResponse(status_code=200, json_body={
            "activities": [
                {"dealId": "D1", "type": "POSITION_CLOSED",
                 "date": "2024-01-01T10:00:00Z", "level": "1.1019"}
            ]
        }),
        CannedResponse(status_code=200, json_body={"transactions": []}),
    ]
    adapter = _make_adapter(responses)
    result = adapter.closed_trade("D1", opened_at=_OPENED_AT)
    assert result is None
