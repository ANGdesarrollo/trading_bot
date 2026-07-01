from __future__ import annotations

import json
import logging

from domain.entities.candle_row import CandleRow
from domain.ports.candle_history_port import CandleHistoryPort
from domain.ports.candle_store_port import CandleStorePort
from infrastructure.capital._pair_buffer import PairBuffer
from infrastructure.capital.session import CapitalSession

_log = logging.getLogger(__name__)

_RECONNECT_DELAY_S = 2.0

_OHLC_EVENT = "ohlc.event"


class CapitalWsIngester:
    """Subscribes to Capital.com ohlc.event WebSocket stream and persists candles.

    Accepts an injected `transport` (connect/send/recv/ping/close) so unit
    tests can use a fake without a real socket. The real transport wraps
    websocket-client.

    `run_once()` handles one connection lifecycle: connect, subscribe,
    backfill/gap-fill, process events. On ConnectionError it reconnects
    after a fixed short delay, indefinitely.
    """

    def __init__(
        self,
        session: CapitalSession,
        store: CandleStorePort,
        history: CandleHistoryPort,
        transport,
        clock,
        epics: list[str],
        resolution: str,
        period_seconds: dict[tuple[str, str], int],
        ws_ping_interval_seconds: int,
        required_candles: int,
        provider: str = "capital",
    ) -> None:
        self._session = session
        self._store = store
        self._history = history
        self._transport = transport
        self._clock = clock
        self._epics = epics
        self._resolution = resolution
        self._period_seconds = period_seconds
        self._ping_interval = ws_ping_interval_seconds
        self._required_candles = required_candles
        self._provider = provider

    def run_once(self) -> None:
        while True:
            try:
                self._connect_and_process()
                return
            except StopIteration:
                return
            except ConnectionError as exc:
                _log.warning("WS dropped, reconnecting in %.1fs: %s", _RECONNECT_DELAY_S, exc)
                self._clock.sleep(_RECONNECT_DELAY_S)

    def _connect_and_process(self) -> None:
        url = f"{self._session.streaming_host}/connect"
        self._transport.connect(url)
        connected_at = self._clock.utcnow()
        self._subscribe()
        self._backfill_or_gap_fill()
        self._process_events(connected_at)

    def _subscribe(self) -> None:
        tokens = self._session.tokens()
        frame = {
            "destination": "OHLCMarketData.subscribe",
            "correlationId": "ingester-sub",
            "cst": tokens.cst,
            "securityToken": tokens.security_token,
            "payload": {
                "epics": self._epics,
                "resolutions": [self._resolution],
                "type": "classic",
            },
        }
        self._transport.send(json.dumps(frame))

    def _backfill_or_gap_fill(self) -> None:
        for epic in self._epics:
            last = self._store.last_candle_start(
                provider=self._provider, symbol=epic, resolution=self._resolution
            )
            if last is None:
                rows = self._history.fetch_history(
                    provider=self._provider, epic=epic,
                    resolution=self._resolution, count=self._required_candles, since=None
                )
            else:
                period_s = self._period_seconds.get((epic, self._resolution), 60)
                from datetime import timedelta
                since = last + timedelta(seconds=period_s)
                rows = self._history.fetch_history(
                    provider=self._provider, epic=epic,
                    resolution=self._resolution, count=self._required_candles, since=since
                )
            for row in rows:
                self._store.upsert_candle(row)

    def _process_events(self, last_ping=None) -> None:
        pair_buffer = PairBuffer(
            period_ms_map={
                (epic, self._resolution): self._period_seconds.get((epic, self._resolution), 60) * 1000
                for epic in self._epics
            },
            provider=self._provider,
        )
        if last_ping is None:
            last_ping = self._clock.utcnow()

        while True:
            now = self._clock.utcnow()
            elapsed = (now - last_ping).total_seconds()
            if elapsed >= self._ping_interval:
                self._transport.ping()
                self._session.authenticate()
                last_ping = now

            raw = self._transport.recv()
            msg = json.loads(raw)
            if msg.get("destination") == _OHLC_EVENT:
                pair_buffer.on_event(msg, self._store.upsert_candle)
