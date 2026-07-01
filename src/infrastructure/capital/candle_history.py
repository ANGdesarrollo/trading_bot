from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from domain.entities.candle_row import CandleRow
from domain.ports.candle_history_port import CandleHistoryPort
from infrastructure.capital.session import CapitalSession


def _to_iso(dt: datetime) -> str:
    # Capital's /prices rejects trailing 'Z'; expects naive-looking UTC ISO string.
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _now_iso() -> str:
    return _to_iso(datetime.now(tz=timezone.utc))


class CapitalCandleHistory(CandleHistoryPort):
    """Implements CandleHistoryPort via Capital.com /prices REST endpoint.

    Uses separate bid and ask requests and merges them by timestamp.

    epic_resolution_map: maps (epic, resolution) -> period_seconds; used only
    to align the 'to' timestamp for gap-fills. May be empty for tests that
    don't exercise gap-fills requiring period derivation.
    """

    def __init__(
        self,
        session: CapitalSession,
        http,
        base_url: str,
        epic_resolution_map: dict[tuple[str, str], int] | None = None,
    ) -> None:
        self._session = session
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._epic_resolution_map: dict[tuple[str, str], int] = epic_resolution_map or {}

    def fetch_history(
        self,
        epic: str,
        resolution: str,
        count: int,
        since: datetime | None,
    ) -> Sequence[CandleRow]:
        tokens = self._session.tokens()
        auth_headers = {
            "CST": tokens.cst,
            "X-SECURITY-TOKEN": tokens.security_token,
        }

        if since is None:
            return self._cold_backfill(epic, resolution, count, auth_headers)
        return self._gap_fill(epic, resolution, since, auth_headers)

    def _cold_backfill(
        self,
        epic: str,
        resolution: str,
        count: int,
        auth_headers: dict[str, str],
    ) -> Sequence[CandleRow]:
        fetch_count = count + 1
        base_url = f"{self._base_url}/prices/{epic}?resolution={resolution}&max={fetch_count}"

        bid_records = self._fetch_prices(base_url + "&priceType=bid", auth_headers)
        ask_records = self._fetch_prices(base_url + "&priceType=ask", auth_headers)

        bid_closed = bid_records[:-1]
        ask_closed = ask_records[:-1]

        return _merge_to_rows(epic, resolution, bid_closed, ask_closed)

    def _gap_fill(
        self,
        epic: str,
        resolution: str,
        since: datetime,
        auth_headers: dict[str, str],
    ) -> Sequence[CandleRow]:
        from_iso = _to_iso(since)
        to_iso = _now_iso()
        base_url = (
            f"{self._base_url}/prices/{epic}"
            f"?resolution={resolution}&from={from_iso}&to={to_iso}"
        )

        bid_records = self._fetch_prices(base_url + "&priceType=bid", auth_headers)
        ask_records = self._fetch_prices(base_url + "&priceType=ask", auth_headers)

        return _merge_to_rows(epic, resolution, bid_records, ask_records)

    def _fetch_prices(self, url: str, auth_headers: dict[str, str]) -> list[dict]:
        response = self._http.get(url, headers=auth_headers)
        response.raise_for_status()
        return response.json().get("prices", [])


def _merge_to_rows(
    epic: str,
    resolution: str,
    bid_records: list[dict],
    ask_records: list[dict],
) -> list[CandleRow]:
    ask_by_t = {r["t"]: r for r in ask_records}
    rows: list[CandleRow] = []
    for bid in bid_records:
        t_ms = bid["t"]
        ask = ask_by_t.get(t_ms)
        if ask is None:
            continue
        candle_start = datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc)
        rows.append(CandleRow(
            epic=epic,
            resolution=resolution,
            candle_start=candle_start,
            open_bid=float(bid["o"]),
            high_bid=float(bid["h"]),
            low_bid=float(bid["l"]),
            close_bid=float(bid["c"]),
            open_ask=float(ask["o"]),
            high_ask=float(ask["h"]),
            low_ask=float(ask["l"]),
            close_ask=float(ask["c"]),
        ))
    return rows
