from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

from domain.entities.candle_row import CandleRow
from domain.ports.candle_history_port import CandleHistoryPort

# Polygon `limit` caps the number of BASE (1-min) aggregates used to build each
# result bar, NOT the number of returned bars. A small limit yields empty
# multi-minute bars, so it must be large enough to cover the requested window.
_BASE_AGG_LIMIT = 5000
_DEFAULT_BASE_URL = "https://api.massive.com"


def _to_polygon_ticker(epic: str) -> str:
    return f"C:{epic}"


def _resolution_to_range(resolution: str) -> tuple[int, str]:
    # "MINUTE_15" -> (15, "minute")
    unit, _, value = resolution.partition("_")
    multiplier = int(value) if value else 1
    return multiplier, unit.lower()


def _date(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


class PolygonCandleHistory(CandleHistoryPort):
    """Implements CandleHistoryPort via Polygon/Massive REST aggregates.

    Forex aggregates return a single OHLC per bar (derived from quoted
    bid/ask). Since the candle store reads mid = (bid+ask)/2, the same value is
    written to both bid and ask fields so mid equals the Polygon price.
    """

    def __init__(self, http, base_url: str = _DEFAULT_BASE_URL, api_key: str = "") -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    def fetch_history(
        self,
        *,
        provider: str = "polygon",
        epic: str,
        resolution: str,
        count: int,
        since: datetime | None,
    ) -> Sequence[CandleRow]:
        multiplier, timespan = _resolution_to_range(resolution)
        ticker = _to_polygon_ticker(epic)
        to = datetime.now(tz=timezone.utc)
        if since is not None:
            frm = since
        else:
            period_minutes = multiplier if timespan == "minute" else multiplier * 60
            frm = to - timedelta(minutes=period_minutes * (count + 1))

        url = (
            f"{self._base_url}/v2/aggs/ticker/{ticker}"
            f"/range/{multiplier}/{timespan}/{_date(frm)}/{_date(to)}"
        )
        response = self._http.get(url, params={
            "adjusted": "true",
            "sort": "desc",
            "limit": _BASE_AGG_LIMIT,
            "apiKey": self._api_key,
        })
        response.raise_for_status()
        results = response.json().get("results") or []
        return [_to_row(provider, epic, resolution, bar) for bar in results]


def _to_row(provider: str, epic: str, resolution: str, bar: dict) -> CandleRow:
    o = float(bar["o"])
    h = float(bar["h"])
    low = float(bar["l"])
    c = float(bar["c"])
    candle_start = datetime.fromtimestamp(bar["t"] / 1000, tz=timezone.utc)
    return CandleRow(
        provider=provider,
        epic=epic,
        resolution=resolution,
        candle_start=candle_start,
        open_bid=o, high_bid=h, low_bid=low, close_bid=c,
        open_ask=o, high_ask=h, low_ask=low, close_ask=c,
    )
