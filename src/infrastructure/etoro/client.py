from __future__ import annotations

import time
import uuid

import requests

_BASE_URL = "https://public-api.etoro.com"
_RATE_LIMIT_DELAY_S = 0.05
_TIMEOUT_S = (5, 30)


def _headers(api_key: str, user_key: str) -> dict[str, str]:
    return {
        "x-request-id": str(uuid.uuid4()),
        "x-api-key": api_key,
        "x-user-key": user_key,
        "Content-Type": "application/json",
    }


class EToroClient:
    """Thin HTTP client for the eToro public API.

    Handles auth headers, unique request IDs, and URL construction for demo/real.
    Callers are responsible for business logic and response interpretation.
    """

    def __init__(
        self,
        session: requests.Session,
        api_key: str,
        user_key: str,
        mode: str = "demo",
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._user_key = user_key
        self._env = "demo" if mode == "demo" else "real"

    def _v1(self, path: str) -> str:
        return f"{_BASE_URL}/api/v1/{path.lstrip('/')}"

    def _v2(self, path: str) -> str:
        return f"{_BASE_URL}/api/v2/{path.lstrip('/')}"

    def _get(self, url: str, **kwargs) -> dict:
        resp = self._session.get(
            url, headers=_headers(self._api_key, self._user_key), timeout=_TIMEOUT_S, **kwargs
        )
        resp.raise_for_status()
        time.sleep(_RATE_LIMIT_DELAY_S)
        return resp.json()

    def _post(self, url: str, body: dict) -> dict:
        resp = self._session.post(
            url,
            headers=_headers(self._api_key, self._user_key),
            json=body,
            timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        time.sleep(_RATE_LIMIT_DELAY_S)
        return resp.json()

    def get_portfolio(self) -> dict:
        url = self._v1(f"trading/info/{self._env}/pnl")
        return self._get(url)

    def search_instrument(self, ticker: str) -> dict:
        url = self._v1("market-data/search")
        data = self._get(url, params={"internalSymbolFull": ticker})
        ticker_upper = ticker.upper()
        match = next(
            (
                item
                for item in data.get("items", [])
                if item.get("internalSymbolFull", "").upper() == ticker_upper
                and not item.get("isHiddenFromClient", True)
            ),
            None,
        )
        if match is None:
            raise ValueError(f"eToro instrument not found for ticker: {ticker!r}")
        return match

    def create_order(
        self,
        instrument_id: int,
        action: str,
        transaction: str,
        amount_usd: float,
    ) -> dict:
        url = self._v2(f"trading/execution/{self._env}/orders")
        body = {
            "action": action,
            "transaction": transaction,
            "instrumentId": instrument_id,
            "settlementType": "real",
            "orderType": "mkt",
            "leverage": 1,
            "amount": amount_usd,
        }
        return self._post(url, body)

    def close_position(
        self,
        position_id: int,
        instrument_id: int,
        units_to_deduct: float | None = None,
    ) -> dict:
        url = self._v1(
            f"trading/execution/{self._env}/market-close-orders/positions/{position_id}"
        )
        body: dict = {"InstrumentID": instrument_id}
        if units_to_deduct is not None:
            body["UnitsToDeduct"] = units_to_deduct
        return self._post(url, body)
