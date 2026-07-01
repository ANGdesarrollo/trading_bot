"""Bounded end-to-end smoke probe for the REAL candle ingestion pipeline.

Read-only against production code: instantiates the SAME components used by
ingestion.py (CapitalWsIngester + PostgresCandleStore + CapitalCandleHistory +
CapitalSession) with a single epic and a hard wall-clock deadline, then compares
our persisted mid=(bid+ask)/2 candles against Capital's REST snapshot.

The only non-production piece is DeadlineTransport: it wraps the real
WebsocketClientTransport and raises StopIteration once the deadline passes, so
CapitalWsIngester._process_events (an unbounded `while True: recv()`) exits
cleanly without any change to production code. The socket read timeout keeps
recv() from blocking past the deadline during quiet stretches.

Usage:
    cd operator && uv run python scripts/probe_ingestion_smoke.py

Writes idempotent upserts to the real `candles` table (harmless: same rows the
live ingester would write). MODE=demo expected.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import requests
from dotenv import load_dotenv

from config import load_config
from infrastructure.capital.candle_history import CapitalCandleHistory
from infrastructure.capital.clock import SystemClock
from infrastructure.capital.session import CapitalSession
from infrastructure.capital.ws_ingester import CapitalWsIngester
from infrastructure.capital.ws_transport import WebsocketClientTransport
from infrastructure.postgres.candle_store import PostgresCandleStore
from infrastructure.postgres.connection import connect
from infrastructure.postgres.migration_runner import run_migrations

_EPIC = "EURUSD"
_RESOLUTION = "MINUTE"
_DEADLINE_SECONDS = 90.0
_SOCKET_READ_TIMEOUT_S = 5.0

_log = logging.getLogger("probe_ingestion_smoke")


class DeadlineTransport:
    """Wraps the real WS transport and stops the ingester after a deadline.

    recv() raises StopIteration once wall-clock passes the deadline, which
    CapitalWsIngester treats as a clean end-of-stream. A socket read timeout
    bounds each recv() so the deadline is honored even during quiet stretches;
    a timeout is retried (not fatal) until the deadline is actually reached.
    """

    def __init__(self, inner: WebsocketClientTransport, deadline_epoch: float) -> None:
        self._inner = inner
        self._deadline = deadline_epoch
        self.event_count = 0

    def connect(self, url: str) -> None:
        _log.info("connecting to %s", url)
        self._inner.connect(url)
        self._inner._ws.settimeout(_SOCKET_READ_TIMEOUT_S)
        _log.info("connected")

    def send(self, payload) -> None:
        _log.info("subscribe frame -> %s", payload)
        self._inner.send(payload)

    def recv(self) -> str:
        while True:
            if time.time() >= self._deadline:
                _log.info("deadline reached, stopping recv loop")
                raise StopIteration("probe deadline")
            try:
                raw = self._inner.recv()
            except Exception as exc:
                if time.time() >= self._deadline:
                    raise StopIteration("probe deadline") from exc
                _log.debug("recv timeout/quiet, retrying: %s", exc)
                continue
            self.event_count += 1
            _log.info("frame[%d]: %s", self.event_count, raw[:300])
            return raw

    def ping(self) -> None:
        self._inner.ping()

    def close(self) -> None:
        self._inner.close()


class LoggingStore(PostgresCandleStore):
    """PostgresCandleStore that logs every upsert so we can watch persistence."""

    def upsert_candle(self, row) -> None:
        mid_open = (row.open_bid + row.open_ask) / 2
        mid_close = (row.close_bid + row.close_ask) / 2
        _log.info(
            "UPSERT %s %s @ %s  mid_o=%.5f mid_c=%.5f (bid_c=%.5f ask_c=%.5f)",
            row.epic,
            row.resolution,
            row.candle_start.isoformat(),
            mid_open,
            mid_close,
            row.close_bid,
            row.close_ask,
        )
        super().upsert_candle(row)


def _rest_last_candles(session: CapitalSession, http, base_url: str, count: int):
    tokens = session.tokens()
    headers = {"CST": tokens.cst, "X-SECURITY-TOKEN": tokens.security_token}
    url = f"{base_url}/prices/{_EPIC}?resolution={_RESOLUTION}&max={count}"
    resp = http.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json().get("prices", [])


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    config = load_config()
    if config.mode != "demo":
        _log.error("refusing to run probe: MODE=%s (expected demo)", config.mode)
        return 2

    conn = connect(config.database_url)
    run_migrations(conn)

    http = requests.Session()
    clock = SystemClock()
    session = CapitalSession(
        http=http,
        base_url=config.base_url,
        api_key=config.api_key,
        identifier=config.identifier,
        password=config.password,
    )
    _log.info("authenticating against %s ...", config.base_url)
    session.authenticate()
    _log.info("authenticated; streaming_host=%s", session.streaming_host)

    period_seconds = {(_EPIC, _RESOLUTION): 60}
    store = LoggingStore(conn)
    history = CapitalCandleHistory(
        session=session,
        http=http,
        base_url=config.base_url,
        epic_resolution_map=period_seconds,
    )

    deadline_epoch = time.time() + _DEADLINE_SECONDS
    transport = DeadlineTransport(WebsocketClientTransport(), deadline_epoch)

    ingester = CapitalWsIngester(
        session=session,
        store=store,
        history=history,
        transport=transport,
        clock=clock,
        epics=[_EPIC],
        resolution=_RESOLUTION,
        period_seconds=period_seconds,
        ws_ping_interval_seconds=config.ws_ping_interval_seconds,
        required_candles=config.required_candles,
    )

    _log.info(
        "running bounded ingestion: epic=%s resolution=%s deadline=%.0fs",
        _EPIC,
        _RESOLUTION,
        _DEADLINE_SECONDS,
    )
    ingester.run_once()
    _log.info("ingestion loop ended; frames received: %d", transport.event_count)

    ours = store.recent_candles(_EPIC, _RESOLUTION, 5)
    _log.info("--- our persisted candles (mid) ---")
    for c in ours:
        _log.info(
            "  %s  o=%.5f h=%.5f l=%.5f c=%.5f",
            c.timestamp.isoformat(),
            c.open,
            c.high,
            c.low,
            c.close,
        )

    _log.info("--- Capital REST snapshot (bid/ask) ---")
    for p in _rest_last_candles(session, http, config.base_url, 5):
        _log.info(
            "  %s  o(bid=%s ask=%s) c(bid=%s ask=%s)",
            p.get("snapshotTimeUTC") or p.get("snapshotTime"),
            p["openPrice"]["bid"],
            p["openPrice"]["ask"],
            p["closePrice"]["bid"],
            p["closePrice"]["ask"],
        )

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
