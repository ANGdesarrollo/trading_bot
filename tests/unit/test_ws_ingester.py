from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call

import pytest

from domain.entities.candle import Candle
from domain.entities.candle_row import CandleRow
from domain.ports.candle_history_port import CandleHistoryPort
from domain.ports.candle_store_port import CandleStorePort
from infrastructure.capital.ws_ingester import CapitalWsIngester

_EPIC = "EURUSD"
_RES = "MINUTE"
_BASE_WS = "wss://api-streaming-capital.backend-capital.com"
_T_MS = 1_700_000_000_000
_T_DT = datetime.fromtimestamp(_T_MS / 1000, tz=timezone.utc)
_PERIOD_S = 60


def _row(t_dt: datetime = _T_DT, epic: str = _EPIC) -> CandleRow:
    return CandleRow(
        epic=epic,
        resolution=_RES,
        candle_start=t_dt,
        open_bid=1.1,
        high_bid=1.11,
        low_bid=1.09,
        close_bid=1.105,
        open_ask=1.101,
        high_ask=1.111,
        low_ask=1.091,
        close_ask=1.106,
    )


def _bid_msg(t_ms: int = _T_MS, epic: str = _EPIC) -> dict:
    return {
        "destination": "ohlc.event",
        "payload": {
            "epic": epic,
            "resolution": _RES,
            "t": t_ms,
            "o": 1.1,
            "h": 1.11,
            "l": 1.09,
            "c": 1.105,
            "priceType": "bid",
        },
    }


def _ask_msg(t_ms: int = _T_MS, epic: str = _EPIC) -> dict:
    return {
        "destination": "ohlc.event",
        "payload": {
            "epic": epic,
            "resolution": _RES,
            "t": t_ms,
            "o": 1.101,
            "h": 1.111,
            "l": 1.091,
            "c": 1.106,
            "priceType": "ask",
        },
    }


def _subscribe_ack() -> dict:
    return {
        "destination": "OHLCMarketData.subscribe",
        "payload": {"subscriptions": {f"{_EPIC}:{_RES}:classic": "PROCESSED"}},
    }


class FakeWsTransport:
    """Synchronous fake WS transport for testing CapitalWsIngester.

    msg_queue is consumed by recv(); when exhausted raises StopIteration
    which signals the ingester to exit the run loop.
    """

    def __init__(self, msgs: list[dict]) -> None:
        self._msgs = list(msgs)
        self.connected = False
        self.sent: list[dict] = []
        self.ping_count = 0
        self.closed = False

    def connect(self, url: str) -> None:
        self.connected = True

    def send(self, payload: str | dict) -> None:
        if isinstance(payload, str):
            self.sent.append(json.loads(payload))
        else:
            self.sent.append(payload)

    def recv(self) -> str:
        if not self._msgs:
            raise StopIteration("no more messages")
        return json.dumps(self._msgs.pop(0))

    def ping(self) -> None:
        self.ping_count += 1

    def close(self) -> None:
        self.closed = True


class FakeDropTransport(FakeWsTransport):
    """Like FakeWsTransport but raises ConnectionError on the n-th recv call."""

    def __init__(self, msgs: list[dict], drop_on_recv: int = 1) -> None:
        super().__init__(msgs)
        self._recv_count = 0
        self._drop_on = drop_on_recv

    def recv(self) -> str:
        self._recv_count += 1
        if self._recv_count >= self._drop_on:
            raise ConnectionError("WS dropped")
        return super().recv()


class FakeStore(CandleStorePort):
    def __init__(self, last_start: datetime | None = None) -> None:
        self._last_start = last_start
        self.upserted: list[CandleRow] = []
        self.last_candle_start_calls: list[tuple[str, str, str]] = []

    def recent_candles(
        self, *, provider: str = "capital", symbol: str, resolution: str, count: int
    ) -> Sequence[Candle]:
        return []

    def last_candle_start(
        self, *, provider: str = "capital", symbol: str, resolution: str
    ) -> datetime | None:
        self.last_candle_start_calls.append((provider, symbol, resolution))
        return self._last_start

    def upsert_candle(self, row: CandleRow) -> None:
        self.upserted.append(row)


class FakeHistory(CandleHistoryPort):
    def __init__(self, rows: list[CandleRow] | None = None) -> None:
        self._rows = rows or []
        self.calls: list[tuple[str, str, str, int, datetime | None]] = []

    def fetch_history(
        self, *, provider: str = "capital", epic: str, resolution: str, count: int, since: datetime | None
    ) -> Sequence[CandleRow]:
        self.calls.append((provider, epic, resolution, count, since))
        return self._rows


class FakeClock:
    def __init__(self) -> None:
        self._t = datetime(2023, 11, 14, 22, 0, 0, tzinfo=timezone.utc)
        self.sleep_calls: list[float] = []

    def utcnow(self) -> datetime:
        return self._t

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self._t += timedelta(seconds=seconds)

    def advance(self, seconds: float) -> None:
        self._t += timedelta(seconds=seconds)


class FakeSession:
    def __init__(self) -> None:
        self._streaming_host = _BASE_WS
        self.authenticate_calls = 0

    def authenticate(self):
        self.authenticate_calls += 1
        return self.tokens()

    @property
    def streaming_host(self) -> str:
        return self._streaming_host

    def tokens(self):
        from infrastructure.capital.session import SessionTokens
        return SessionTokens(cst="test-cst", security_token="test-xst")


_SENTINEL = object()


def _make_ingester(
    transport: FakeWsTransport,
    store: FakeStore,
    history: FakeHistory,
    ping_interval: int = 540,
    required_candles: int = 3,
    last_start=_SENTINEL,
    provider: str = "capital",
) -> CapitalWsIngester:
    if last_start is not _SENTINEL:
        store._last_start = last_start
    return CapitalWsIngester(
        session=FakeSession(),
        store=store,
        history=history,
        transport=transport,
        clock=FakeClock(),
        epics=[_EPIC],
        resolution=_RES,
        period_seconds={(_EPIC, _RES): _PERIOD_S},
        ws_ping_interval_seconds=ping_interval,
        required_candles=required_candles,
        provider=provider,
    )


def test_cold_start_fetches_backfill_then_upserts():
    history_rows = [_row(_T_DT), _row(_T_DT + timedelta(seconds=60)), _row(_T_DT + timedelta(seconds=120))]
    history = FakeHistory(history_rows)
    store = FakeStore(last_start=None)
    transport = FakeWsTransport([_subscribe_ack()])

    ingester = _make_ingester(transport, store, history, required_candles=3)
    ingester.run_once()

    assert len(history.calls) == 1
    provider, epic, resolution, count, since = history.calls[0]
    assert provider == "capital"
    assert epic == _EPIC
    assert since is None
    assert count >= 3
    assert len(store.upserted) == 3


def test_warm_start_fetches_gap_only():
    t_last = _T_DT
    history = FakeHistory([_row(_T_DT + timedelta(seconds=60))])
    store = FakeStore(last_start=t_last)
    transport = FakeWsTransport([_subscribe_ack()])

    ingester = _make_ingester(transport, store, history)
    ingester.run_once()

    assert len(history.calls) == 1
    _, _, _, count, since = history.calls[0]
    assert since == t_last + timedelta(seconds=_PERIOD_S)


def test_bid_only_event_does_not_upsert():
    store = FakeStore()
    history = FakeHistory()
    transport = FakeWsTransport([_subscribe_ack(), _bid_msg()])

    ingester = _make_ingester(transport, store, history)
    ingester.run_once()

    assert store.upserted == []


def test_bid_then_ask_upserts_one_row():
    store = FakeStore()
    history = FakeHistory()
    transport = FakeWsTransport([_subscribe_ack(), _bid_msg(), _ask_msg()])

    ingester = _make_ingester(transport, store, history)
    ingester.run_once()

    assert len(store.upserted) == 1
    row = store.upserted[0]
    assert row.epic == _EPIC
    assert row.candle_start == _T_DT
    assert row.open_bid == 1.1
    assert row.open_ask == 1.101


def test_ask_then_bid_upserts_one_row():
    store = FakeStore()
    history = FakeHistory()
    transport = FakeWsTransport([_subscribe_ack(), _ask_msg(), _bid_msg()])

    ingester = _make_ingester(transport, store, history)
    ingester.run_once()

    assert len(store.upserted) == 1


def test_epoch_ms_timestamp_conversion():
    store = FakeStore()
    history = FakeHistory()
    t_ms = 1_700_000_000_000
    transport = FakeWsTransport([_subscribe_ack(), _bid_msg(t_ms), _ask_msg(t_ms)])

    ingester = _make_ingester(transport, store, history)
    ingester.run_once()

    assert store.upserted[0].candle_start == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)


def test_subscribe_frame_includes_required_fields():
    store = FakeStore()
    history = FakeHistory()
    transport = FakeWsTransport([_subscribe_ack()])

    ingester = _make_ingester(transport, store, history)
    ingester.run_once()

    subscribe_frame = transport.sent[0]
    assert subscribe_frame["destination"] == "OHLCMarketData.subscribe"
    assert "cst" in subscribe_frame
    assert "securityToken" in subscribe_frame
    payload = subscribe_frame["payload"]
    assert _EPIC in str(payload)


def test_ping_sent_after_ping_interval():
    store = FakeStore()
    history = FakeHistory()
    clock = FakeClock()

    class AdvancingTransport(FakeWsTransport):
        def __init__(self, msgs: list[dict], clk: FakeClock, advance_s: float = 0) -> None:
            super().__init__(msgs)
            self._clk = clk
            self._advance_s = advance_s

        def recv(self) -> str:
            self._clk.advance(self._advance_s)
            return super().recv()

    transport = AdvancingTransport([_subscribe_ack()], clock, advance_s=6)

    ingester = CapitalWsIngester(
        session=FakeSession(),
        store=store,
        history=history,
        transport=transport,
        clock=clock,
        epics=[_EPIC],
        resolution=_RES,
        period_seconds={(_EPIC, _RES): _PERIOD_S},
        ws_ping_interval_seconds=5,
        required_candles=1,
    )
    ingester.run_once()

    assert transport.ping_count >= 1


def test_session_reauthenticated_on_refresh_tick():
    store = FakeStore()
    history = FakeHistory()
    clock = FakeClock()
    session = FakeSession()

    class AdvancingTransport(FakeWsTransport):
        def __init__(self, msgs, clk, advance_s=0):
            super().__init__(msgs)
            self._clk = clk
            self._advance_s = advance_s

        def recv(self):
            self._clk.advance(self._advance_s)
            return super().recv()

    transport = AdvancingTransport([_subscribe_ack()], clock, advance_s=600)

    ingester = CapitalWsIngester(
        session=session,
        store=store,
        history=history,
        transport=transport,
        clock=clock,
        epics=[_EPIC],
        resolution=_RES,
        period_seconds={(_EPIC, _RES): _PERIOD_S},
        ws_ping_interval_seconds=5,
        required_candles=1,
    )
    ingester.run_once()

    assert session.authenticate_calls >= 1


def test_reconnect_on_drop_calls_gap_fill_again():
    t_last = _T_DT
    history = FakeHistory([_row(_T_DT + timedelta(seconds=60))])
    store = FakeStore(last_start=t_last)

    class DropThenOkTransport:
        def __init__(self) -> None:
            self._attempts = 0
            self.sent: list[dict] = []
            self.ping_count = 0
            self.closed = False
            self._msgs_per_attempt = [
                [_subscribe_ack(), {"destination": "drop", "raise": True}],
                [_subscribe_ack()],
            ]

        def connect(self, url: str) -> None:
            self._attempt_msgs = list(self._msgs_per_attempt[min(self._attempts, len(self._msgs_per_attempt) - 1)])
            self._attempts += 1

        def send(self, payload) -> None:
            if isinstance(payload, str):
                self.sent.append(json.loads(payload))
            else:
                self.sent.append(payload)

        def recv(self) -> str:
            if not self._attempt_msgs:
                raise StopIteration("done")
            msg = self._attempt_msgs.pop(0)
            if msg.get("raise"):
                raise ConnectionError("simulated drop")
            return json.dumps(msg)

        def ping(self) -> None:
            self.ping_count += 1

        def close(self) -> None:
            self.closed = True

    transport = DropThenOkTransport()
    clock = FakeClock()
    ingester = CapitalWsIngester(
        session=FakeSession(),
        store=store,
        history=history,
        transport=transport,
        clock=clock,
        epics=[_EPIC],
        resolution=_RES,
        period_seconds={(_EPIC, _RES): _PERIOD_S},
        ws_ping_interval_seconds=540,
        required_candles=1,
    )

    ingester.run_once()

    assert len(history.calls) == 2
    assert clock.sleep_calls, "reconnect must sleep before retrying"


def test_backfill_records_capital_as_provider():
    history = FakeHistory([_row(_T_DT)])
    store = FakeStore(last_start=None)
    transport = FakeWsTransport([_subscribe_ack()])

    ingester = _make_ingester(transport, store, history, required_candles=1)
    ingester.run_once()

    assert len(history.calls) == 1
    provider, *_ = history.calls[0]
    assert provider == "capital"


def test_configured_provider_flows_to_fetch_history():
    history = FakeHistory([_row(_T_DT)])
    store = FakeStore(last_start=None)
    transport = FakeWsTransport([_subscribe_ack()])

    ingester = _make_ingester(
        transport, store, history, required_candles=1, provider="ic_markets"
    )
    ingester.run_once()

    provider, *_ = history.calls[0]
    assert provider == "ic_markets"
    assert store.last_candle_start_calls[0][0] == "ic_markets"
