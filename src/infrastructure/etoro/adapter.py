from __future__ import annotations

import logging
from datetime import datetime, timezone

from domain.ports.portfolio_broker_port import PortfolioBrokerPort
from infrastructure.etoro.client import EToroClient

_log = logging.getLogger(__name__)

_DUST_THRESHOLD_USD = 0.01


def _position_open_time(position: dict) -> datetime:
    parsed = datetime.fromisoformat(position["openDateTime"].replace("Z", "+00:00"))
    # eToro timestamps are UTC; suffix-less strings parse naive and must not mix with aware
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class EToroPortfolioBrokerAdapter(PortfolioBrokerPort):
    """Implements PortfolioBrokerPort against the eToro public API.

    Symbol mapping: domain uses XAUUSD/BTCUSD; eToro uses GLD/BTC since we
    prefer real ETFs over CFDs for the gold leg. The symbol_to_etoro_ticker
    dict is the single source of truth for this mapping.

    Copy-trading positions (mirrorID != 0) are never counted or touched.
    eToro treats omitted UnitsToDeduct as a full position close.
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
        self._instrument_id_to_positions: dict[int, list[dict]] = {}
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
        grouped: dict[int, list[dict]] = {}
        for p in positions:
            if p.get("mirrorID", 0) != 0:
                continue
            grouped.setdefault(p["instrumentID"], []).append(p)
        self._instrument_id_to_positions = grouped
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
        for instrument_id, pos_list in self._instrument_id_to_positions.items():
            domain_symbol = self._instrument_id_to_domain_symbol.get(instrument_id)
            if domain_symbol is not None:
                total_exposure = sum(
                    float(p["unrealizedPnL"]["exposureInAccountCurrency"]) for p in pos_list
                )
                result[domain_symbol] = total_exposure
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

    def sell(self, symbol: str, amount_usd: float) -> list[str]:
        if not self._resolved:
            self._resolve_instrument_map()
        etoro_ticker = self._symbol_to_etoro_ticker[symbol]
        instrument_id = self._etoro_ticker_to_instrument_id[etoro_ticker]

        self._refresh_portfolio()

        pos_list = self._instrument_id_to_positions.get(instrument_id)
        if not pos_list:
            raise ValueError(f"no open position found for {symbol} (eToro: {etoro_ticker})")

        fifo_positions = sorted(pos_list, key=_position_open_time)

        remaining = amount_usd
        order_ids: list[str] = []

        for position in fifo_positions:
            exposure = float(position["unrealizedPnL"]["exposureInAccountCurrency"])
            if remaining < _DUST_THRESHOLD_USD or exposure <= 0:
                continue

            position_id = int(position["positionID"])
            units = float(position["units"])

            if remaining >= exposure:
                response = self._client.close_position(
                    position_id=position_id,
                    instrument_id=instrument_id,
                    units_to_deduct=None,
                )
                remaining -= exposure
            else:
                response = self._client.close_position(
                    position_id=position_id,
                    instrument_id=instrument_id,
                    units_to_deduct=units * (remaining / exposure),
                )
                remaining = 0.0

            order_id = str(response.get("orderForClose", {}).get("orderID", ""))
            order_ids.append(order_id)
            _log.info("SELL %s position=%s -> orderID=%s", symbol, position_id, order_id)

        if not order_ids:
            raise ValueError(f"no closeable positions found for {symbol} (eToro: {etoro_ticker})")

        if remaining >= _DUST_THRESHOLD_USD:
            _log.warning(
                "SELL %s shortfall: requested %.2f but only %.2f available across positions",
                symbol, amount_usd, amount_usd - remaining,
            )

        return order_ids
