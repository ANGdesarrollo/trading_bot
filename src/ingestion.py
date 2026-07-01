from __future__ import annotations

import logging
from typing import Protocol


class _HasRunOnce(Protocol):
    def run_once(self) -> None: ...


def run_ingestion_forever(ingester: _HasRunOnce) -> None:
    logger = logging.getLogger("ingestion")
    while True:
        try:
            ingester.run_once()
        except Exception:
            logger.exception("ingestion cycle failed; restarting")


if __name__ == "__main__":
    import requests
    from dotenv import load_dotenv

    from config import load_config
    from infrastructure.capital.candle_history import CapitalCandleHistory
    from infrastructure.capital.clock import SystemClock
    from infrastructure.capital.session import CapitalSession
    from infrastructure.capital.shared_cached_session import SharedCachedSession
    from infrastructure.capital.ws_ingester import CapitalWsIngester
    from infrastructure.capital.ws_transport import WebsocketClientTransport
    from infrastructure.postgres.candle_store import PostgresCandleStore
    from infrastructure.postgres.connection import connect
    from infrastructure.postgres.migration_runner import run_migrations
    from infrastructure.postgres.session_cache import PostgresSessionCache

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    load_dotenv()
    _config = load_config()
    _conn = connect(_config.database_url)
    run_migrations(_conn)

    _http = requests.Session()
    _clock = SystemClock()
    _capital_session = CapitalSession(
        http=_http,
        base_url=_config.base_url,
        api_key=_config.api_key,
        identifier=_config.identifier,
        password=_config.password,
        clock=_clock,
        max_auth_retries=_config.auth_max_retries,
    )
    _session = SharedCachedSession(
        inner=_capital_session,
        cache=PostgresSessionCache(_conn),
        clock=_clock,
        owner=True,
    )
    _session.authenticate()

    _store = PostgresCandleStore(_conn)
    _period_seconds = {
        (s.epic, _config.timeframe): 60 * int(_config.timeframe.split("_")[1])
        if "_" in _config.timeframe else 60
        for s in _config.symbols
    }
    _history = CapitalCandleHistory(
        session=_session,
        http=_http,
        base_url=_config.base_url,
        epic_resolution_map=_period_seconds,
    )
    _ingester = CapitalWsIngester(
        session=_session,
        store=_store,
        history=_history,
        transport=WebsocketClientTransport(),
        clock=_clock,
        epics=[s.epic for s in _config.symbols],
        resolution=_config.timeframe,
        period_seconds=_period_seconds,
        ws_ping_interval_seconds=_config.ws_ping_interval_seconds,
        required_candles=_config.required_candles,
        provider=_config.provider,
    )

    run_ingestion_forever(_ingester)
