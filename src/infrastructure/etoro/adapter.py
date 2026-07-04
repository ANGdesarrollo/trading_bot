from __future__ import annotations

import logging

from domain.ports.portfolio_broker_port import PortfolioBrokerPort
from infrastructure.etoro.client import EToroClient

_log = logging.getLogger(__name__)


class EToroPortfolioBrokerAdapter(PortfolioBrokerPort):
    """Implements PortfolioBrokerPort against the eToro public API.

    Symbol mapping: domain uses XAUUSD/BTCUSD; eToro uses GLD/BTC since we
    prefer real ETFs over CFDs for the gold leg. The symbol_to_etoro_ticker
    dict is the single source of truth for this mapping.

    Instrument ID resolution is done once at first use and cached in-process.
    Sells convert USD delta to units via the position's current amount/units ratio.
    """

    def __init__(
        self,
        client: EToroClient,
        symbol_to_etoro_ticker: dict[str, str],
    ) -> None:
        self._client = client
        self._symbol_to_etoro_ticker = symbol_to_etoro_ticker
        self._etoro_ticker_to_instrument_id: dict[str, int] = {}
        self._instrument_id_to_domain_symbol: dict[int, str] = {}
        self._instrument_id_to_position: dict[int, dict] = {}
        self._resolved = False

    def _resolve_instrument_map(self) -> None:
        if self._resolved:
            return
        for domain_symbol, etoro_ticker in self._symbol_to_etoro_ticker.items():
            if etoro_ticker in self._etoro_ticker_to_instrument_id:
                instrument_id = self._etoro_ticker_to_instrument_id[etoro_ticker]
            else:
                instrument = self._client.search_instrument(etoro_ticker)
                instrument_id = instrument["internalInstrumentId"]
                self._etoro_ticker_to_instrument_id[etoro_ticker] = instrument_id
                _log.info("resolved %s -> %s (id=%s)", domain_symbol, etoro_ticker, instrument_id)
            self._instrument_id_to_domain_symbol[instrument_id] = domain_symbol
        self._resolved = True

    def _refresh_portfolio(self) -> dict:
        portfolio = self._client.get_portfolio()
        positions = portfolio["clientPortfolio"].get("positions", [])
        self._instrument_id_to_position = {p["instrumentID"]: p for p in positions}
        return portfolio["clientPortfolio"]

    def available_cash(self) -> float:
        pf = self._refresh_portfolio()
        credit = float(pf["credit"])
        manual_orders_for_open = sum(
            float(o["amount"])
            for o in pf.get("ordersForOpen", [])
            if o.get("mirrorID", 0) == 0
        )
        pending_mit_orders = sum(float(o["amount"]) for o in pf.get("orders", []))
        return credit - manual_orders_for_open - pending_mit_orders

    def positions(self) -> dict[str, float]:
        if not self._resolved:
            self._resolve_instrument_map()
        self._refresh_portfolio()
        result: dict[str, float] = {}
        for instrument_id, position in self._instrument_id_to_position.items():
            domain_symbol = self._instrument_id_to_domain_symbol.get(instrument_id)
            if domain_symbol is not None:
                result[domain_symbol] = float(
                    position["unrealizedPnL"]["exposureInAccountCurrency"]
                )
        return result

    def buy(self, symbol: str, amount_usd: float) -> str:
        if not self._resolved:
            self._resolve_instrument_map()
        etoro_ticker = self._symbol_to_etoro_ticker[symbol]
        instrument_id = self._etoro_ticker_to_instrument_id[etoro_ticker]
        response = self._client.create_order(
            instrument_id=instrument_id,
            action="open",
            transaction="buy",
            amount_usd=amount_usd,
        )
        order_id = str(response["orderId"])
        _log.info("BUY %s %.2f -> orderId=%s", symbol, amount_usd, order_id)
        return order_id

    def sell(self, symbol: str, amount_usd: float) -> str:
        """Close a portion of an existing position by converting USD to units.

        eToro's close endpoint requires units, not USD amounts. We derive units
        proportionally from the position's current amount and unit count.
        """
        if not self._resolved:
            self._resolve_instrument_map()
        etoro_ticker = self._symbol_to_etoro_ticker[symbol]
        instrument_id = self._etoro_ticker_to_instrument_id[etoro_ticker]

        if not self._instrument_id_to_position:
            self._refresh_portfolio()

        position = self._instrument_id_to_position.get(instrument_id)
        if position is None:
            raise ValueError(f"no open position found for {symbol} (eToro: {etoro_ticker})")

        current_value_usd = float(position["unrealizedPnL"]["exposureInAccountCurrency"])
        position_units = float(position["units"])

        if current_value_usd <= 0:
            raise ValueError(f"position for {symbol} has zero exposure; cannot compute unit ratio")

        fraction = min(amount_usd / current_value_usd, 1.0)
        units_to_close = position_units * fraction

        response = self._client.close_position(
            position_id=int(position["positionID"]),
            instrument_id=instrument_id,
            units_to_deduct=units_to_close,
        )
        order_id = str(response.get("orderForClose", {}).get("orderID", ""))
        _log.info(
            "SELL %s %.2f (units=%.4f) -> orderID=%s",
            symbol, amount_usd, units_to_close, order_id,
        )
        return order_id
