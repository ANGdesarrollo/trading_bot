from __future__ import annotations

from datetime import datetime, timezone

from domain.entities.journal import ClosedTrade
from domain.ports.trade_history_port import TradeHistoryPort
from infrastructure.capital.session import CapitalSession

_OPEN_SOURCE = "USER"


def _to_iso(dt: datetime) -> str:
    # Capital's /history/activity rejects a trailing 'Z' with error.invalid.from;
    # it expects a naive-looking ISO timestamp in UTC.
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _direction_sign(direction: str) -> int:
    d = direction.strip().upper()
    if d == "BUY":
        return 1
    if d == "SELL":
        return -1
    raise ValueError(f"invalid direction: {direction!r}")


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
        from_iso = _to_iso(opened_at)

        activity_url = (
            f"{self._base_url}/history/activity"
            f"?dealId={deal_id}&detailed=true&from={from_iso}"
        )
        activity_resp = self._http.get(activity_url, headers=auth_headers)
        activity_resp.raise_for_status()
        activities = activity_resp.json().get("activities", [])

        close = next(
            (a for a in activities
             if a.get("dealId") == deal_id
             and a.get("type") == "POSITION"
             and a.get("source") != _OPEN_SOURCE
             and "openPrice" in a.get("details", {})),
            None,
        )
        if close is None:
            return None

        details = close["details"]
        open_price = float(details["openPrice"])
        close_price = float(details["level"])
        size = float(details["size"])
        # details.direction is the CLOSING side (opposite of the position);
        # the position's P&L uses the opening side, so invert it.
        opening_sign = -_direction_sign(details["direction"])
        realized_pnl = (close_price - open_price) * size * opening_sign

        closed_at = datetime.fromisoformat(close["date"]).replace(tzinfo=timezone.utc)
        return ClosedTrade(
            deal_id=deal_id,
            closed_at=closed_at,
            close_price=close_price,
            close_source=close.get("source", ""),
            realized_pnl=realized_pnl,
            fees=0.0,
        )
