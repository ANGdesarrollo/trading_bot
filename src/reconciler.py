from __future__ import annotations

import logging
from typing import Protocol


class _HasExecute(Protocol):
    def execute(self) -> None: ...


class _HasAuthenticate(Protocol):
    def authenticate(self) -> None: ...


class _HasSleep(Protocol):
    def sleep(self, seconds: float) -> None: ...


def run_reconciler_forever(
    use_case: _HasExecute,
    session: _HasAuthenticate,
    clock: _HasSleep,
    logger: logging.Logger,
    interval_seconds: float,
) -> None:
    while True:
        try:
            session.authenticate()
            use_case.execute()
        except Exception:
            logger.exception("reconciler cycle failed; retrying next boundary")
        clock.sleep(interval_seconds)


if __name__ == "__main__":
    import requests
    from dotenv import load_dotenv

    from config import load_config

    load_dotenv()
    from application.reconcile_closed_trades import ReconcileClosedTradesUseCase
    from infrastructure.capital.clock import SystemClock
    from infrastructure.capital.history_adapter import CapitalTradeHistory
    from infrastructure.capital.shared_cached_session import SharedCachedSession
    from infrastructure.postgres.connection import connect
    from infrastructure.postgres.journal_adapter import PostgresTradeJournal
    from infrastructure.postgres.migration_runner import run_migrations
    from infrastructure.postgres.session_cache import PostgresSessionCache

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _logger = logging.getLogger("reconciler")

    _config = load_config()
    _conn = connect(_config.database_url)
    run_migrations(_conn)

    _http = requests.Session()
    _clock = SystemClock()
    _session = SharedCachedSession(
        cache=PostgresSessionCache(_conn),
        clock=_clock,
    )
    _session.authenticate()

    _journal = PostgresTradeJournal(_conn)
    _history = CapitalTradeHistory(session=_session, http=_http, base_url=_config.base_url)
    _use_case = ReconcileClosedTradesUseCase(_journal, _history)

    run_reconciler_forever(
        _use_case, _session, _clock, _logger,
        interval_seconds=_config.reconciler_interval_seconds,
    )
