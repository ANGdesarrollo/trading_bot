from __future__ import annotations

import logging
from datetime import timezone

from domain.boundary import seconds_until_next_boundary

_log = logging.getLogger("ingestion_polygon")

_SETTLE_SECONDS = 3.0
_RETRY_INTERVAL_S = 1.0
_MAX_RETRIES = 30


def _expected_candle_start(now, period_minutes):
    period = period_minutes * 60
    boundary = now.timestamp() - (now.timestamp() % period)
    from datetime import datetime
    return datetime.fromtimestamp(boundary - period, tz=timezone.utc)


def run_polygon_ingestion_forever(history, store, clock, symbols, resolution,
                                  period_minutes, required_candles, provider="polygon"):
    """Poll aligned to the 15-min boundary: after each close, fetch the just-closed
    candle for every symbol, retrying every second until it appears (Polygon
    publishes a few seconds after close)."""
    while True:
        wait = seconds_until_next_boundary(clock.utcnow(), period_minutes)
        clock.sleep(wait + _SETTLE_SECONDS)
        expected = _expected_candle_start(clock.utcnow(), period_minutes)
        for symbol in symbols:
            _ingest_symbol(history, store, clock, symbol, resolution,
                           required_candles, expected, provider)


def _ingest_symbol(history, store, clock, symbol, resolution, required_candles,
                   expected, provider):
    for attempt in range(_MAX_RETRIES):
        try:
            rows = history.fetch_history(
                provider=provider, epic=symbol, resolution=resolution,
                count=required_candles, since=None)
        except Exception:
            _log.exception("polygon fetch failed for %s; retrying", symbol)
            rows = []

        # Polygon returns the still-forming (current) bar as the newest result,
        # so never trust rows[0]; only persist bars that have actually closed
        # (candle_start <= expected), and confirm the just-closed one is present.
        closed = [r for r in rows if r.candle_start <= expected]
        if any(r.candle_start == expected for r in closed):
            for row in closed:
                store.upsert_candle(row)
            _log.info("persisting candle epic=%s start=%s", symbol, expected)
            return

        _log.info(
            "[%s] candle %s not published yet (attempt %d/%d); waiting %.0fs",
            symbol, expected, attempt + 1, _MAX_RETRIES, _RETRY_INTERVAL_S)
        clock.sleep(_RETRY_INTERVAL_S)

    _log.warning("[%s] candle %s never appeared after %d attempts; skipping",
                 symbol, expected, _MAX_RETRIES)


if __name__ == "__main__":
    import requests
    from dotenv import load_dotenv

    from config import load_config
    from infrastructure.capital.clock import SystemClock
    from infrastructure.polygon.candle_history import PolygonCandleHistory
    from infrastructure.postgres.candle_store import PostgresCandleStore
    from infrastructure.postgres.connection import connect
    from infrastructure.postgres.migration_runner import run_migrations

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    load_dotenv()
    _config = load_config()
    if not _config.polygon_api_key:
        raise SystemExit("Missing required environment variable: POLYGON_API_KEY")

    _conn = connect(_config.database_url)
    run_migrations(_conn)

    _history = PolygonCandleHistory(
        http=requests.Session(),
        base_url=_config.polygon_base_url,
        api_key=_config.polygon_api_key,
    )
    run_polygon_ingestion_forever(
        history=_history,
        store=PostgresCandleStore(_conn),
        clock=SystemClock(),
        symbols=[s.epic for s in _config.symbols],
        resolution=_config.timeframe,
        period_minutes=_config.poll_minutes,
        required_candles=_config.required_candles,
        provider="polygon",
    )
