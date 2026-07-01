from __future__ import annotations

import logging

if __name__ == "__main__":
    import requests
    from dotenv import load_dotenv

    from config import load_config
    from infrastructure.capital.clock import SystemClock
    from infrastructure.capital.session import CapitalSession
    from infrastructure.capital.session_refresher import SessionTokenRefresher
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
    _refresher = SessionTokenRefresher(
        inner=_capital_session,
        cache=PostgresSessionCache(_conn),
        clock=_clock,
    )
    _refresher.run_forever(interval_seconds=_config.session_refresh_ttl_seconds)
