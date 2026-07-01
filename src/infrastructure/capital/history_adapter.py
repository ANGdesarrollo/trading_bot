from __future__ import annotations

from datetime import datetime, timezone

from domain.entities.journal import ClosedTrade
from domain.ports.trade_history_port import TradeHistoryPort
from infrastructure.capital.session import CapitalSession


_ACTIVITY_SOURCE_TO_CLOSE_SOURCE: dict[str, str] = {
    "USER": "USER",
    "CLOSE_OUT": "CLOSE_OUT",
    # Capital.com "SYSTEM" covers both SL and TP; disambiguation happens in the
    # reconciler via derive_close_source, so the adapter passes the raw value through.
    "SYSTEM": "SYSTEM",
}

_CLOSE_SOURCE_FALLBACK = "USER"


def _map_close_source(activity_source: str) -> str:
    return _ACTIVITY_SOURCE_TO_CLOSE_SOURCE.get(activity_source, _CLOSE_SOURCE_FALLBACK)


def _to_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


class CapitalTradeHistory(TradeHistoryPort):
    def __init__(self, session: CapitalSession, http, base_url: str) -> None:
        self._session = session
        self._http = http
        self._base_url = base_url.rstrip("/")

    def closed_trade(self, deal_id: str, opened_at: datetime) -> ClosedTrade | None:
        tokens = self._session.tokens()
        auth_headers = {
            "CST": tokens.cst,
            "X-SECURITY-TOKEN": tokens.security_token,
        }
        now_iso = _to_iso(datetime.now(timezone.utc))
        from_iso = _to_iso(opened_at)

        activity_url = (
            f"{self._base_url}/history/activity"
            f"?dealId={deal_id}&detailed=true&from={from_iso}&to={now_iso}"
        )
        activity_resp = self._http.get(activity_url, headers=auth_headers)
        activity_resp.raise_for_status()
        activities = activity_resp.json().get("activities", [])

        match = next(
            (a for a in activities
             if a.get("dealId") == deal_id and a.get("type") == "POSITION_CLOSED"),
            None,
        )
        if match is None:
            return None

        tx_url = (
            f"{self._base_url}/history/transactions"
            f"?from={from_iso}&to={now_iso}"
        )
        tx_resp = self._http.get(tx_url, headers=auth_headers)
        tx_resp.raise_for_status()
        transactions = tx_resp.json().get("transactions", [])

        tx = next((t for t in transactions if t.get("reference") == deal_id), None)
        if tx is None:
            return None

        closed_at = datetime.fromisoformat(match["date"].replace("Z", "+00:00"))
        return ClosedTrade(
            deal_id=deal_id,
            closed_at=closed_at,
            close_price=float(match["level"]),
            close_source=_map_close_source(match.get("source", "")),
            realized_pnl=float(tx["profitAndLoss"]),
            fees=float(tx["commission"]),
        )
