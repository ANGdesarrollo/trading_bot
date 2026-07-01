"""Trading engine entry point — composition root and 15-minute aligned loop.

This is the ONLY place concrete infrastructure classes are instantiated and
wired together. Everything else depends on abstractions (ports).

Usage:
    uv run python -m trading_engine   # or: cd src && python __main__.py
"""

from __future__ import annotations

import logging
from datetime import datetime

import requests

from config import load_config
from application.trading_cycle import RunTradingCycleUseCase
from domain.adapters.fade_strategy import FadeStrategy
from domain.ports.trade_journal_port import TradeJournalPort
from infrastructure.capital.broker import CapitalBrokerAdapter
from infrastructure.capital.clock import SystemClock
from infrastructure.capital.session import CapitalSession
from infrastructure.capital.shared_cached_session import SharedCachedSession
from infrastructure.postgres.candle_store import PostgresCandleStore
from infrastructure.postgres.connection import connect
from infrastructure.postgres.journal_adapter import PostgresTradeJournal
from infrastructure.postgres.migration_runner import run_migrations
from infrastructure.postgres.session_cache import PostgresSessionCache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("trading_engine")


def seconds_until_next_boundary(now: datetime, period_minutes: int) -> float:
    """Seconds until the next multiple-of-period-minutes UTC boundary.

    When `now` falls exactly on a boundary, returns a full period so the
    loop always moves forward rather than spinning.
    """
    period = period_minutes * 60
    epoch_secs = now.timestamp()
    remainder = epoch_secs % period
    wait = period - remainder
    return float(wait)


def build_use_cases(
    config,
    http,
    clock,
    journal: TradeJournalPort | None = None,
    candle_store=None,
    session_cache=None,
):
    strategy = FadeStrategy()
    if config.warmup_bars < strategy.required_candles:
        raise SystemExit(
            f"warmup_bars={config.warmup_bars} < strategy requirement "
            f"{strategy.required_candles}"
        )
    if journal is None:
        conn = connect(config.database_url)
        run_migrations(conn)
        journal = PostgresTradeJournal(conn)
        if candle_store is None:
            candle_store = PostgresCandleStore(conn)
        if session_cache is None:
            session_cache = PostgresSessionCache(conn)

    capital_session = CapitalSession(
        http=http,
        base_url=config.base_url,
        api_key=config.api_key,
        identifier=config.identifier,
        password=config.password,
        clock=clock,
        max_auth_retries=config.auth_max_retries,
    )
    session = SharedCachedSession(
        inner=capital_session,
        cache=session_cache,
        clock=clock,
        owner=False,
    )
    broker = CapitalBrokerAdapter(
        session=session,
        http=http,
        base_url=config.base_url,
        epics=config.epics,
        timeframe=config.timeframe,
    )
    use_cases = [
        RunTradingCycleUseCase(
            broker=broker,
            strategy=strategy,
            symbol=sc.symbol,
            size=sc.size,
            logger=logger,
            clock=clock,
            poll_minutes=config.poll_minutes,
            candle_store=candle_store,
            resolution=config.timeframe,
            journal=journal,
            provider=config.provider,
        )
        for sc in config.symbols
    ]
    return use_cases, session


def run_forever(config, use_cases, session, clock) -> None:
    while True:
        wait = seconds_until_next_boundary(clock.utcnow(), config.poll_minutes)
        clock.sleep(wait + config.candle_settle_seconds)
        try:
            session.authenticate()
        except Exception:
            logger.exception("authentication failed; skipping boundary")
            continue
        for use_case in use_cases:
            try:
                use_case.execute()
            except Exception:
                symbol = getattr(use_case, "_symbol", "unknown")
                logger.exception("cycle failed for %s; continuing", symbol)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    config = load_config()
    http = requests.Session()
    clock = SystemClock()
    use_cases, session = build_use_cases(config, http, clock)
    session.authenticate()
    run_forever(config, use_cases, session, clock)
