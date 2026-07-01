from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from domain.entities.candle_row import CandleRow
from domain.ports.candle_history_port import CandleHistoryPort
from infrastructure.capital.session import CapitalSession

_SNAPSHOT_UTC_FORMAT = "%Y-%m-%dT%H:%M:%S"


def _to_iso(dt: datetime) -> str:
    # Capital's /prices rejects a trailing 'Z'; it expects naive-looking UTC ISO.
    return dt.astimezone(timezone.utc).strftime(_SNAPSHOT_UTC_FORMAT)


def _now_iso() -> str:
    return _to_iso(datetime.now(tz=timezone.utc))


class CapitalCandleHistory(CandleHistoryPort):
    """Implements CandleHistoryPort via Capital.com /prices REST endpoint.

    A single /prices request already returns bid and ask for every OHLC point,
    so there is no per-priceType fan-out: each record carries openPrice,
    closePrice, highPrice and lowPrice, each with .bid and .ask.

    epic_resolution_map: maps (epic, resolution) -> period_seconds; reserved for
    callers that need period derivation. May be empty.
    """

    def __init__(
        self,
        session: CapitalSession,
        http,
        base_url: str,
        epic_resolution_map: dict[tuple[str, str], int] | None = None,
        provider: str = "capital",
    ) -> None:
        self._session = session
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._epic_resolution_map: dict[tuple[str, str], int] = epic_resolution_map or {}
        self._provider = provider

    def fetch_history(
        self,
        *,
        provider: str = "capital",
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
        url = f"{self._base_url}/prices/{epic}?resolution={resolution}&max={fetch_count}"
        records = self._fetch_prices(url, auth_headers)
        closed = records[:-1]
        return _to_rows(self._provider, epic, resolution, closed)

    def _gap_fill(
        self,
        epic: str,
        resolution: str,
        since: datetime,
        auth_headers: dict[str, str],
    ) -> Sequence[CandleRow]:
        from_iso = _to_iso(since)
        to_iso = _now_iso()
        url = (
            f"{self._base_url}/prices/{epic}"
            f"?resolution={resolution}&from={from_iso}&to={to_iso}"
        )
        records = self._fetch_prices(url, auth_headers)
        return _to_rows(self._provider, epic, resolution, records)

    def _fetch_prices(self, url: str, auth_headers: dict[str, str]) -> list[dict]:
        response = self._http.get(url, headers=auth_headers)
        response.raise_for_status()
        return response.json().get("prices", [])


def _parse_snapshot(record: dict) -> datetime:
    naive = datetime.strptime(record["snapshotTimeUTC"], _SNAPSHOT_UTC_FORMAT)
    return naive.replace(tzinfo=timezone.utc)


def _to_rows(
    provider: str,
    epic: str,
    resolution: str,
    records: list[dict],
) -> list[CandleRow]:
    rows: list[CandleRow] = []
    for record in records:
        open_price = record["openPrice"]
        high_price = record["highPrice"]
        low_price = record["lowPrice"]
        close_price = record["closePrice"]
        rows.append(CandleRow(
            provider=provider,
            epic=epic,
            resolution=resolution,
            candle_start=_parse_snapshot(record),
            open_bid=float(open_price["bid"]),
            high_bid=float(high_price["bid"]),
            low_bid=float(low_price["bid"]),
            close_bid=float(close_price["bid"]),
            open_ask=float(open_price["ask"]),
            high_ask=float(high_price["ask"]),
            low_ask=float(low_price["ask"]),
            close_ask=float(close_price["ask"]),
        ))
    return rows
