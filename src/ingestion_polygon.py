from __future__ import annotations

import logging

_log = logging.getLogger("ingestion_polygon")


def run_polygon_ingestion_forever(history, store, clock, symbols, resolution,
                                  required_candles, poll_seconds, provider="polygon"):
    while True:
        for symbol in symbols:
            try:
                rows = history.fetch_history(
                    provider=provider, epic=symbol, resolution=resolution,
                    count=required_candles, since=None)
                for row in rows:
                    store.upsert_candle(row)
                if rows:
                    _log.info(
                        "persisting candle epic=%s start=%s",
                        symbol, rows[0].candle_start)
            except Exception:
                _log.exception("polygon fetch failed for %s; continuing", symbol)
        clock.sleep(poll_seconds)


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
        required_candles=_config.required_candles,
        poll_seconds=_config.polygon_poll_seconds,
        provider="polygon",
    )
