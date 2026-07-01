from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from domain.entities.candle import Candle
from domain.entities.direction import Direction
from domain.entities.order import OrderResult
from domain.entities.signal import Signal
from domain.ports.broker_port import BrokerPort
from infrastructure.capital.session import CapitalSession


class OrderRejectedError(Exception):
    """Raised when Capital.com rejects a deal placement."""


class UnknownSymbolError(Exception):
    """Raised when the symbol has no configured epic."""


class CapitalBrokerAdapter(BrokerPort):
    """Maps BrokerPort methods to Capital.com REST endpoints.

    Does not subclass CapitalSession — holds it as a dependency.
    Every method uses session.tokens() to build auth headers; the loop
    calls session.authenticate() before each cycle (eager re-auth strategy).
    """

    def __init__(
        self,
        session: CapitalSession,
        http,
        base_url: str,
        epics: dict[str, str],
        timeframe: str = "MINUTE_15",
    ) -> None:
        self._session = session
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._epics = epics
        self._timeframe = timeframe

    def recent_candles(self, symbol: str, count: int) -> Sequence[Candle]:
        epic = self._epic_for(symbol)
        tokens = self._session.tokens()
        url = (
            f"{self._base_url}/prices/{epic}"
            f"?resolution={self._timeframe}&max={count + 1}"
        )
        response = self._http.get(url, headers=self._auth_headers(tokens))
        response.raise_for_status()
        records = response.json()["prices"]
        closed_records = records[:-1]
        return [_parse_candle(r) for r in closed_records]

    def open_position(self, symbol: str, signal: Signal, size: float) -> OrderResult:
        epic = self._epic_for(symbol)
        tokens = self._session.tokens()
        direction = "BUY" if signal.direction is Direction.BUY else "SELL"

        post_response = self._http.post(
            f"{self._base_url}/positions",
            json={
                "epic": epic,
                "direction": direction,
                "size": size,
                "stopDistance": signal.sl_distance,
                "profitDistance": signal.tp_distance,
                "guaranteedStop": False,
            },
            headers=self._auth_headers(tokens),
        )
        post_response.raise_for_status()
        deal_reference = post_response.json()["dealReference"]

        confirm_response = self._http.get(
            f"{self._base_url}/confirms/{deal_reference}",
            headers=self._auth_headers(tokens),
        )
        confirm_response.raise_for_status()
        confirm = confirm_response.json()

        deal_status = confirm["dealStatus"]
        if deal_status not in ("ACCEPTED", "OPEN"):
            raise OrderRejectedError(
                f"Deal {deal_reference} rejected: dealStatus={deal_status}"
            )

        return OrderResult(
            order_id=confirm["dealId"],
            status=deal_status,
            filled_price=float(confirm["level"]),
        )

    def has_open_position(self, symbol: str) -> bool:
        epic = self._epic_for(symbol)
        tokens = self._session.tokens()
        response = self._http.get(
            f"{self._base_url}/positions",
            headers=self._auth_headers(tokens),
        )
        response.raise_for_status()
        positions = response.json().get("positions", [])
        return any(p["market"]["epic"] == epic for p in positions)

    def _epic_for(self, symbol: str) -> str:
        try:
            return self._epics[symbol]
        except KeyError:
            raise UnknownSymbolError(
                f"No epic configured for symbol '{symbol}'"
            ) from None

    @staticmethod
    def _auth_headers(tokens) -> dict[str, str]:
        return {"CST": tokens.cst, "X-SECURITY-TOKEN": tokens.security_token}


def _parse_candle(record: dict) -> Candle:
    ts = datetime.fromisoformat(
        record["snapshotTimeUTC"].replace("Z", "+00:00")
    ).replace(tzinfo=timezone.utc)
    return Candle(
        timestamp=ts,
        open=float(record["openPrice"]["bid"]),
        high=float(record["highPrice"]["bid"]),
        low=float(record["lowPrice"]["bid"]),
        close=float(record["closePrice"]["bid"]),
    )
