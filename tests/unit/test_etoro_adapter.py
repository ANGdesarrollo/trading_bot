from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from infrastructure.etoro.client import EToroClient
from infrastructure.etoro.adapter import EToroPortfolioBrokerAdapter


def _make_position(
    position_id: int,
    instrument_id: int,
    amount: float,
    units: float,
    exposure: float,
    mirror_id: int = 0,
    open_dt: str = "2024-01-01T00:00:00",
) -> dict:
    return {
        "positionID": position_id,
        "instrumentID": instrument_id,
        "mirrorID": mirror_id,
        "openDateTime": open_dt,
        "amount": amount,
        "units": units,
        "unrealizedPnL": {"exposureInAccountCurrency": exposure},
    }


DEMO_PORTFOLIO_RESPONSE = {
    "clientPortfolio": {
        "credit": 10_000.0,
        "unrealizedPnL": 150.0,
        "ordersForOpen": [],
        "orders": [],
        "positions": [
            _make_position(1001, 201, 1_200.0, 5.2, 1_250.0),
            _make_position(1002, 202, 850.0, 3.1, 900.0),
        ],
    }
}

def _search_response(instrument_id: int, ticker: str) -> dict:
    return {
        "page": 1,
        "pageSize": 20,
        "totalItems": 1,
        "items": [
            {
                "internalInstrumentId": instrument_id,
                "internalSymbolFull": ticker,
                "isHiddenFromClient": False,
            }
        ],
    }

INSTRUMENT_SEARCH_SPY = _search_response(201, "SPY")
INSTRUMENT_SEARCH_QQQ = _search_response(202, "QQQ")


class FakeResponse:
    def __init__(self, data: dict, status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code

    def json(self) -> dict:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class TestEToroClientRequestBuilding:
    def test_get_portfolio_calls_correct_url_with_auth_headers(self):
        session = MagicMock()
        session.get.return_value = FakeResponse(DEMO_PORTFOLIO_RESPONSE)

        client = EToroClient(
            session=session,
            api_key="test-api-key",
            user_key="test-user-key",
            mode="demo",
        )
        result = client.get_portfolio()

        call_args = session.get.call_args
        url = call_args[0][0]
        headers = call_args[1]["headers"]

        assert "/trading/info/demo/pnl" in url
        assert headers["x-api-key"] == "test-api-key"
        assert headers["x-user-key"] == "test-user-key"
        assert "x-request-id" in headers

    def test_each_request_generates_a_unique_request_id(self):
        session = MagicMock()
        session.get.return_value = FakeResponse(DEMO_PORTFOLIO_RESPONSE)

        client = EToroClient(
            session=session,
            api_key="key",
            user_key="ukey",
            mode="demo",
        )
        client.get_portfolio()
        client.get_portfolio()

        calls = session.get.call_args_list
        id1 = calls[0][1]["headers"]["x-request-id"]
        id2 = calls[1][1]["headers"]["x-request-id"]
        assert id1 != id2

    def test_get_portfolio_parses_credit_and_positions(self):
        session = MagicMock()
        session.get.return_value = FakeResponse(DEMO_PORTFOLIO_RESPONSE)

        client = EToroClient(
            session=session,
            api_key="key",
            user_key="ukey",
            mode="demo",
        )
        portfolio = client.get_portfolio()

        assert portfolio["clientPortfolio"]["credit"] == 10_000.0
        assert len(portfolio["clientPortfolio"]["positions"]) == 2

    def test_search_instrument_builds_correct_query(self):
        session = MagicMock()
        session.get.return_value = FakeResponse(INSTRUMENT_SEARCH_SPY)

        client = EToroClient(session=session, api_key="k", user_key="u", mode="demo")
        result = client.search_instrument("SPY")

        call_args = session.get.call_args
        url = call_args[0][0]
        assert "market-data/search" in url
        assert result["internalInstrumentId"] == 201
        assert result["internalSymbolFull"] == "SPY"

    def test_search_instrument_raises_when_no_exact_match(self):
        partial_response = {
            "page": 1, "pageSize": 20, "totalItems": 2,
            "items": [
                {"internalInstrumentId": 999, "internalSymbolFull": "SPYG", "isHiddenFromClient": False},
                {"internalInstrumentId": 998, "internalSymbolFull": "SPY", "isHiddenFromClient": True},
            ],
        }
        session = MagicMock()
        session.get.return_value = FakeResponse(partial_response)

        client = EToroClient(session=session, api_key="k", user_key="u", mode="demo")
        with pytest.raises(ValueError, match="SPY"):
            client.search_instrument("SPY")

    def test_create_order_posts_to_correct_url(self):
        session = MagicMock()
        session.post.return_value = FakeResponse({"orderId": 999, "token": "tok"})

        client = EToroClient(session=session, api_key="k", user_key="u", mode="demo")
        client.create_order(
            instrument_id=201,
            action="open",
            transaction="buy",
            amount_usd=500.0,
        )

        call_args = session.post.call_args
        url = call_args[0][0]
        body = call_args[1]["json"]
        assert "/trading/execution/demo/orders" in url
        assert body["action"] == "open"
        assert body["transaction"] == "buy"
        assert body["amount"] == 500.0
        assert body["instrumentId"] == 201

    def test_close_position_posts_to_correct_url(self):
        session = MagicMock()
        session.post.return_value = FakeResponse({"orderForClose": {}, "token": "tok"})

        client = EToroClient(session=session, api_key="k", user_key="u", mode="demo")
        client.close_position(position_id=1001, instrument_id=201, units_to_deduct=2.5)

        call_args = session.post.call_args
        url = call_args[0][0]
        body = call_args[1]["json"]
        assert "/trading/execution/demo/market-close-orders/positions/1001" in url
        assert body["InstrumentID"] == 201
        assert body["UnitsToDeduct"] == pytest.approx(2.5)

    def test_real_mode_execution_urls_have_no_environment_segment(self):
        session = MagicMock()
        session.post.return_value = FakeResponse({"orderId": 999, "orderForClose": {}})

        client = EToroClient(session=session, api_key="k", user_key="u", mode="real")
        client.create_order(instrument_id=201, action="open", transaction="buy", amount_usd=500.0)
        client.close_position(position_id=1001, instrument_id=201, units_to_deduct=2.5)

        order_url = session.post.call_args_list[0][0][0]
        close_url = session.post.call_args_list[1][0][0]
        assert "/trading/execution/orders" in order_url
        assert "/real/" not in order_url
        assert "/trading/execution/market-close-orders/positions/1001" in close_url
        assert "/real/" not in close_url

    def test_real_mode_portfolio_url_keeps_environment_segment(self):
        session = MagicMock()
        session.get.return_value = FakeResponse(DEMO_PORTFOLIO_RESPONSE)

        client = EToroClient(session=session, api_key="k", user_key="u", mode="real")
        client.get_portfolio()

        url = session.get.call_args[0][0]
        assert "/trading/info/real/pnl" in url


class TestEToroPortfolioBrokerAdapter:
    def _make_adapter(self, instrument_map: dict[str, int], portfolio: dict) -> tuple:
        client = MagicMock()
        client.get_portfolio.return_value = portfolio
        client.search_instrument.side_effect = lambda ticker: {
            "internalInstrumentId": instrument_map[ticker],
            "internalSymbolFull": ticker,
            "isHiddenFromClient": False,
        }

        symbol_to_etoro = {
            "SPY": "SPY", "QQQ": "QQQ", "IWM": "IWM",
            "EEM": "EEM", "EFA": "EFA", "TLT": "TLT",
            "XAUUSD": "GLD", "BTCUSD": "BTC",
        }
        adapter = EToroPortfolioBrokerAdapter(
            client=client,
            symbol_to_etoro_ticker=symbol_to_etoro,
        )
        return adapter, client

    def test_available_cash_subtracts_pending_orders_from_credit(self):
        portfolio = {
            "clientPortfolio": {
                "credit": 10_000.0,
                "ordersForOpen": [{"amount": 500.0, "mirrorID": 0}],
                "orders": [{"amount": 200.0}],
                "positions": [],
            }
        }
        adapter, _ = self._make_adapter({}, portfolio)

        cash = adapter.available_cash()

        assert cash == pytest.approx(9_300.0)

    def test_available_cash_excludes_mirrored_orders_for_open(self):
        portfolio = {
            "clientPortfolio": {
                "credit": 10_000.0,
                "ordersForOpen": [
                    {"amount": 500.0, "mirrorID": 0},
                    {"amount": 300.0, "mirrorID": 42},
                ],
                "orders": [],
                "positions": [],
            }
        }
        adapter, _ = self._make_adapter({}, portfolio)

        cash = adapter.available_cash()

        assert cash == pytest.approx(9_500.0)

    def test_positions_maps_etoro_tickers_to_domain_symbols(self):
        portfolio = {
            "clientPortfolio": {
                "credit": 5_000.0,
                "ordersForOpen": [],
                "orders": [],
                "positions": [
                    _make_position(1001, 201, 1_200.0, 5.0, 1_250.0),
                    _make_position(1002, 202, 850.0, 3.0, 900.0),
                ],
            }
        }
        adapter, client = self._make_adapter(
            {"SPY": 201, "QQQ": 202, "IWM": 203, "EEM": 204, "EFA": 205, "TLT": 206, "GLD": 207, "BTC": 208},
            portfolio,
        )
        adapter._resolve_instrument_map()

        result = adapter.positions()

        assert result.get("SPY") == pytest.approx(1_250.0)
        assert result.get("QQQ") == pytest.approx(900.0)

    def test_buy_calls_create_order_with_correct_params(self):
        portfolio = {
            "clientPortfolio": {
                "credit": 10_000.0,
                "ordersForOpen": [],
                "orders": [],
                "positions": [],
            }
        }
        adapter, client = self._make_adapter(
            {"SPY": 201, "QQQ": 202, "IWM": 203, "EEM": 204, "EFA": 205, "TLT": 206, "GLD": 207, "BTC": 208},
            portfolio,
        )
        client.create_order.return_value = {"orderId": 999, "token": "tok"}
        adapter._resolve_instrument_map()

        order_id = adapter.buy("SPY", 500.0)

        client.create_order.assert_called_once()
        call_kwargs = client.create_order.call_args[1]
        assert call_kwargs["instrument_id"] == 201
        assert call_kwargs["transaction"] == "buy"
        assert call_kwargs["amount_usd"] == 500.0
        assert order_id == "999"

    def test_sell_partial_single_position_uses_proportional_units(self):
        portfolio = {
            "clientPortfolio": {
                "credit": 10_000.0,
                "ordersForOpen": [],
                "orders": [],
                "positions": [
                    _make_position(1001, 201, 950.0, 4.0, 1_000.0),
                ],
            }
        }
        adapter, client = self._make_adapter(
            {"SPY": 201, "QQQ": 202, "IWM": 203, "EEM": 204, "EFA": 205, "TLT": 206, "GLD": 207, "BTC": 208},
            portfolio,
        )
        client.close_position.return_value = {"orderForClose": {"orderID": 888}, "token": "t"}
        adapter._resolve_instrument_map()

        order_ids = adapter.sell("SPY", 500.0)

        client.close_position.assert_called_once()
        call_kwargs = client.close_position.call_args[1]
        assert call_kwargs["position_id"] == 1001
        assert call_kwargs["instrument_id"] == 201
        assert call_kwargs["units_to_deduct"] == pytest.approx(2.0)
        assert order_ids == ["888"]

    def test_positions_sums_exposure_across_multiple_positions_same_instrument(self):
        portfolio = {
            "clientPortfolio": {
                "credit": 5_000.0,
                "ordersForOpen": [],
                "orders": [],
                "positions": [
                    _make_position(2001, 201, 1_000.0, 4.0, 1_100.0, open_dt="2024-01-01T00:00:00"),
                    _make_position(2002, 201, 1_200.0, 5.0, 1_300.0, open_dt="2024-02-01T00:00:00"),
                ],
            }
        }
        adapter, _ = self._make_adapter(
            {"SPY": 201, "QQQ": 202, "IWM": 203, "EEM": 204, "EFA": 205, "TLT": 206, "GLD": 207, "BTC": 208},
            portfolio,
        )
        adapter._resolve_instrument_map()

        result = adapter.positions()

        assert result.get("SPY") == pytest.approx(2_400.0)

    def test_positions_excludes_mirror_positions(self):
        portfolio = {
            "clientPortfolio": {
                "credit": 5_000.0,
                "ordersForOpen": [],
                "orders": [],
                "positions": [
                    _make_position(3001, 201, 1_000.0, 4.0, 1_100.0, mirror_id=0),
                    _make_position(3002, 201, 500.0, 2.0, 600.0, mirror_id=99),
                ],
            }
        }
        adapter, _ = self._make_adapter(
            {"SPY": 201, "QQQ": 202, "IWM": 203, "EEM": 204, "EFA": 205, "TLT": 206, "GLD": 207, "BTC": 208},
            portfolio,
        )
        adapter._resolve_instrument_map()

        result = adapter.positions()

        assert result.get("SPY") == pytest.approx(1_100.0)

    def test_sell_spanning_two_positions_closes_oldest_fully_then_partial(self):
        # old position: $100 exposure, 4 units; new position: $50 exposure, 2 units
        # sell $120 -> full close of old (units_to_deduct=None) + partial of new
        portfolio = {
            "clientPortfolio": {
                "credit": 5_000.0,
                "ordersForOpen": [],
                "orders": [],
                "positions": [
                    _make_position(4002, 201, 48.0, 2.0, 50.0, open_dt="2024-06-01T00:00:00"),
                    _make_position(4001, 201, 96.0, 4.0, 100.0, open_dt="2024-01-01T00:00:00"),
                ],
            }
        }
        adapter, client = self._make_adapter(
            {"SPY": 201, "QQQ": 202, "IWM": 203, "EEM": 204, "EFA": 205, "TLT": 206, "GLD": 207, "BTC": 208},
            portfolio,
        )
        client.close_position.side_effect = [
            {"orderForClose": {"orderID": 701}, "token": "t"},
            {"orderForClose": {"orderID": 702}, "token": "t"},
        ]
        adapter._resolve_instrument_map()

        result = adapter.sell("SPY", 120.0)

        assert client.close_position.call_count == 2
        first_call = client.close_position.call_args_list[0][1]
        second_call = client.close_position.call_args_list[1][1]

        assert first_call["position_id"] == 4001
        assert first_call["units_to_deduct"] is None

        assert second_call["position_id"] == 4002
        remaining = 120.0 - 100.0
        expected_units = 2.0 * (remaining / 50.0)
        assert second_call["units_to_deduct"] == pytest.approx(expected_units)

        assert result == ["701", "702"]

    def test_sell_more_than_total_exposure_closes_all_positions_fully(self):
        portfolio = {
            "clientPortfolio": {
                "credit": 5_000.0,
                "ordersForOpen": [],
                "orders": [],
                "positions": [
                    _make_position(5001, 201, 90.0, 3.0, 100.0, open_dt="2024-01-01T00:00:00"),
                    _make_position(5002, 201, 140.0, 5.0, 150.0, open_dt="2024-03-01T00:00:00"),
                ],
            }
        }
        adapter, client = self._make_adapter(
            {"SPY": 201, "QQQ": 202, "IWM": 203, "EEM": 204, "EFA": 205, "TLT": 206, "GLD": 207, "BTC": 208},
            portfolio,
        )
        client.close_position.side_effect = [
            {"orderForClose": {"orderID": 801}, "token": "t"},
            {"orderForClose": {"orderID": 802}, "token": "t"},
        ]
        adapter._resolve_instrument_map()

        adapter.sell("SPY", 9_999.0)

        assert client.close_position.call_count == 2
        for call in client.close_position.call_args_list:
            assert call[1]["units_to_deduct"] is None

    def test_sell_fifo_respects_open_datetime_regardless_of_api_order(self):
        portfolio = {
            "clientPortfolio": {
                "credit": 5_000.0,
                "ordersForOpen": [],
                "orders": [],
                "positions": [
                    _make_position(6002, 201, 90.0, 3.0, 100.0, open_dt="2024-12-01T00:00:00"),
                    _make_position(6001, 201, 90.0, 3.0, 100.0, open_dt="2024-01-01T00:00:00"),
                ],
            }
        }
        adapter, client = self._make_adapter(
            {"SPY": 201, "QQQ": 202, "IWM": 203, "EEM": 204, "EFA": 205, "TLT": 206, "GLD": 207, "BTC": 208},
            portfolio,
        )
        client.close_position.return_value = {"orderForClose": {"orderID": 901}, "token": "t"}
        adapter._resolve_instrument_map()

        adapter.sell("SPY", 50.0)

        first_call = client.close_position.call_args_list[0][1]
        assert first_call["position_id"] == 6001

    def test_sell_fifo_handles_mixed_precision_and_z_suffix_timestamps(self):
        portfolio = {
            "clientPortfolio": {
                "credit": 5_000.0,
                "ordersForOpen": [],
                "orders": [],
                "positions": [
                    _make_position(9002, 201, 90.0, 3.0, 100.0, open_dt="2025-09-08T12:38:46.58Z"),
                    _make_position(9001, 201, 90.0, 3.0, 100.0, open_dt="2024-12-02T14:40:24.983Z"),
                ],
            }
        }
        adapter, client = self._make_adapter(
            {"SPY": 201, "QQQ": 202, "IWM": 203, "EEM": 204, "EFA": 205, "TLT": 206, "GLD": 207, "BTC": 208},
            portfolio,
        )
        client.close_position.return_value = {"orderForClose": {"orderID": 910}, "token": "t"}
        adapter._resolve_instrument_map()

        adapter.sell("SPY", 50.0)

        first_call = client.close_position.call_args_list[0][1]
        assert first_call["position_id"] == 9001

    def test_sell_fifo_handles_mixed_naive_and_aware_timestamps(self):
        portfolio = {
            "clientPortfolio": {
                "credit": 5_000.0,
                "ordersForOpen": [],
                "orders": [],
                "positions": [
                    _make_position(10003, 201, 90.0, 3.0, 100.0, open_dt="2024-06-01T00:00:00.583Z"),
                    _make_position(10001, 201, 90.0, 3.0, 100.0, open_dt="2024-01-01T00:00:00"),
                    _make_position(10002, 201, 90.0, 3.0, 100.0, open_dt="2024-03-01T00:00:00Z"),
                ],
            }
        }
        adapter, client = self._make_adapter(
            {"SPY": 201, "QQQ": 202, "IWM": 203, "EEM": 204, "EFA": 205, "TLT": 206, "GLD": 207, "BTC": 208},
            portfolio,
        )
        client.close_position.return_value = {"orderForClose": {"orderID": 920}, "token": "t"}
        adapter._resolve_instrument_map()

        adapter.sell("SPY", 50.0)

        first_call = client.close_position.call_args_list[0][1]
        assert first_call["position_id"] == 10001

    def test_sell_skips_dust_remainder_after_full_closes(self):
        portfolio = {
            "clientPortfolio": {
                "credit": 5_000.0,
                "ordersForOpen": [],
                "orders": [],
                "positions": [
                    _make_position(7001, 201, 90.0, 3.0, 100.0, open_dt="2024-01-01T00:00:00"),
                    _make_position(7002, 201, 90.0, 3.0, 100.0, open_dt="2024-03-01T00:00:00"),
                ],
            }
        }
        adapter, client = self._make_adapter(
            {"SPY": 201, "QQQ": 202, "IWM": 203, "EEM": 204, "EFA": 205, "TLT": 206, "GLD": 207, "BTC": 208},
            portfolio,
        )
        client.close_position.side_effect = [
            {"orderForClose": {"orderID": 1001}, "token": "t"},
            {"orderForClose": {"orderID": 1002}, "token": "t"},
        ]
        adapter._resolve_instrument_map()

        # $100.005 against a $100 position leaves $0.005 remainder — below dust threshold
        adapter.sell("SPY", 100.005)

        assert client.close_position.call_count == 1

    def test_sell_raises_when_no_close_placed_due_to_all_zero_exposure(self):
        portfolio = {
            "clientPortfolio": {
                "credit": 5_000.0,
                "ordersForOpen": [],
                "orders": [],
                "positions": [
                    _make_position(11001, 201, 0.0, 3.0, 0.0, open_dt="2024-01-01T00:00:00"),
                ],
            }
        }
        adapter, client = self._make_adapter(
            {"SPY": 201, "QQQ": 202, "IWM": 203, "EEM": 204, "EFA": 205, "TLT": 206, "GLD": 207, "BTC": 208},
            portfolio,
        )
        adapter._resolve_instrument_map()

        with pytest.raises(ValueError, match="SPY"):
            adapter.sell("SPY", 50.0)

    def test_sell_logs_warning_but_does_not_raise_when_shortfall_after_partial_closes(self, caplog):
        import logging
        portfolio = {
            "clientPortfolio": {
                "credit": 5_000.0,
                "ordersForOpen": [],
                "orders": [],
                "positions": [
                    _make_position(12001, 201, 90.0, 3.0, 100.0, open_dt="2024-01-01T00:00:00"),
                ],
            }
        }
        adapter, client = self._make_adapter(
            {"SPY": 201, "QQQ": 202, "IWM": 203, "EEM": 204, "EFA": 205, "TLT": 206, "GLD": 207, "BTC": 208},
            portfolio,
        )
        client.close_position.return_value = {"orderForClose": {"orderID": 1201}, "token": "t"}
        adapter._resolve_instrument_map()

        with caplog.at_level(logging.WARNING):
            result = adapter.sell("SPY", 9_999.0)

        assert result == ["1201"]
        assert any("shortfall" in r.message.lower() or "SPY" in r.message for r in caplog.records if r.levelno >= logging.WARNING)

    def test_sell_excludes_mirror_positions_from_sell(self):
        portfolio = {
            "clientPortfolio": {
                "credit": 5_000.0,
                "ordersForOpen": [],
                "orders": [],
                "positions": [
                    _make_position(8001, 201, 90.0, 3.0, 100.0, mirror_id=0, open_dt="2024-01-01T00:00:00"),
                    _make_position(8002, 201, 200.0, 7.0, 250.0, mirror_id=55, open_dt="2023-01-01T00:00:00"),
                ],
            }
        }
        adapter, client = self._make_adapter(
            {"SPY": 201, "QQQ": 202, "IWM": 203, "EEM": 204, "EFA": 205, "TLT": 206, "GLD": 207, "BTC": 208},
            portfolio,
        )
        client.close_position.return_value = {"orderForClose": {"orderID": 1101}, "token": "t"}
        adapter._resolve_instrument_map()

        adapter.sell("SPY", 50.0)

        assert client.close_position.call_count == 1
        call_kwargs = client.close_position.call_args[1]
        assert call_kwargs["position_id"] == 8001
