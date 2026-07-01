"""Reconciler process — composition root and 60-second loop.

Runs as a separate OS process from the operator. Connects to Capital.com and
Postgres, then polls at 60-second cadence to fill result columns for entries
the operator has written but not yet reconciled.
"""

from __future__ import annotations

import logging
from typing import Protocol


class _HasExecute(Protocol):
    def execute(self) -> None: ...


class _HasSleep(Protocol):
    def sleep(self, seconds: float) -> None: ...


def run_reconciler_forever(
    use_case: _HasExecute,
    clock: _HasSleep,
    logger: logging.Logger,
) -> None:
    while True:
        clock.sleep(60)
        try:
            use_case.execute()
        except Exception:
            logger.exception("reconciler cycle failed; retrying next boundary")


if __name__ == "__main__":
    import requests

    from config import load_config
    from application.reconcile_closed_trades import ReconcileClosedTradesUseCase
    from infrastructure.capital.clock import SystemClock
    from infrastructure.capital.history_adapter import CapitalTradeHistory
    from infrastructure.capital.session import CapitalSession
    from infrastructure.postgres.connection import connect
    from infrastructure.postgres.journal_adapter import PostgresTradeJournal
    from infrastructure.postgres.migration_runner import run_migrations

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _logger = logging.getLogger("reconciler")

    _config = load_config()
    _conn = connect(_config.database_url)
    run_migrations(_conn)

    _http = requests.Session()
    _session = CapitalSession(
        http=_http,
        base_url=_config.base_url,
        api_key=_config.api_key,
        identifier=_config.identifier,
        password=_config.password,
    )
    _session.authenticate()

    _journal = PostgresTradeJournal(_conn)
    _history = CapitalTradeHistory(session=_session, http=_http, base_url=_config.base_url)
    _use_case = ReconcileClosedTradesUseCase(_journal, _history)
    _clock = SystemClock()

    run_reconciler_forever(_use_case, _clock, _logger)
