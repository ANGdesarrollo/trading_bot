# Spec: WebSocket Candle Ingestion + Postgres Candle Store

**Change:** ws-candle-ingestion
**Status:** draft
**Phase:** spec

---

## Overview

The closed decision candle must be available in sub-second after the bar boundary. This spec defines the WHAT for four capabilities: a new Postgres candle store, a new WebSocket ingestion process, a modified trading cycle, and a modified Capital session. Implementation details (library choice, async model, exact backoff timings) are deferred to design.

---

## Resolved Open Decisions

### (a) BrokerPort.recent_candles — REMOVE

`BrokerPort.recent_candles` SHALL be removed from the abstract port and from `CapitalBrokerAdapter`. Candle supply is `CandleStorePort`'s responsibility. Keeping a method on the port that no caller invokes violates ISP: it forces every test double to stub behavior that is never exercised. The existing `BrokerPort` mock in tests must be updated to remove `recent_candles`; tests relying on it are deleted or rewritten against `CandleStorePort`.

### (d) streamingHost surfacing — property on CapitalSession

`CapitalSession.authenticate()` SHALL internally parse `streamingHost` from the POST /session response body and store it. `CapitalSession` SHALL expose a `streaming_host: str` property that returns the captured value. The return type of `authenticate()` remains `SessionTokens` — no signature change to that type. `streaming_host` raises `RuntimeError` if accessed before `authenticate()` has been called successfully.

### (e) Startup race — return None when store is short

`RunTradingCycleUseCase.execute()` SHALL return `None` without raising when `CandleStorePort.recent_candles` returns fewer items than `strategy.required_candles`. This is the only startup-race guard needed; no retry, no REST fallback.

---

## Capability: candle-store (new)

### Requirements

**CSP-01.** A domain port `CandleStorePort` SHALL declare three abstract methods:
- `recent_candles(symbol: str, count: int) -> Sequence[Candle]` — returns up to `count` most-recently CLOSED candles for `symbol`, ordered oldest-first, with OHLC derived as `mid = (bid + ask) / 2` per field.
- `last_candle_start(symbol: str, resolution: str) -> datetime | None` — returns the `candle_start` of the most recent row for `(symbol, resolution)`, or `None` if none exists.
- `upsert_candle(row: CandleRow) -> None` — writes or overwrites a single candle row identified by `(epic, resolution, candle_start)`.

**CSP-02.** `CandleRow` SHALL be a value object (frozen dataclass or equivalent) carrying: `epic: str`, `resolution: str`, `candle_start: datetime` (UTC-aware), `open_bid: float`, `high_bid: float`, `low_bid: float`, `close_bid: float`, `open_ask: float`, `high_ask: float`, `low_ask: float`, `close_ask: float`.

**CSP-03.** `CandleStorePort` SHALL live in `src/domain/ports/candle_store_port.py`. It is a domain-layer abstraction with no infrastructure imports.

**CSP-04.** A `PostgresCandleStore` adapter SHALL implement `CandleStorePort`. `upsert_candle` SHALL be idempotent: inserting a row with the same `(epic, resolution, candle_start)` twice produces exactly one row in the database (ON CONFLICT DO UPDATE or DO NOTHING — decided in design).

**CSP-05.** `PostgresCandleStore.recent_candles` SHALL query the N rows with the largest `candle_start` for the given symbol, then return them ordered oldest-first with OHLC derived as `mid = (bid_col + ask_col) / 2` for each of open, high, low, close. The returned objects SHALL be `Candle` entities as defined in `src/domain/entities/candle.py` (unchanged entity, unchanged invariants).

**CSP-06.** `PostgresCandleStore.last_candle_start` SHALL return `None` when no rows exist for the given `(symbol, resolution)`.

**CSP-07.** Migration `002_create_candles.sql` SHALL create a table `candles` with columns: `epic TEXT NOT NULL`, `resolution TEXT NOT NULL`, `candle_start TIMESTAMPTZ NOT NULL`, `open_bid NUMERIC NOT NULL`, `high_bid NUMERIC NOT NULL`, `low_bid NUMERIC NOT NULL`, `close_bid NUMERIC NOT NULL`, `open_ask NUMERIC NOT NULL`, `high_ask NUMERIC NOT NULL`, `low_ask NUMERIC NOT NULL`, `close_ask NUMERIC NOT NULL`, and a `UNIQUE(epic, resolution, candle_start)` constraint. The migration file SHALL be discoverable by the existing migration runner via alphabetical filename sort (prefix `002_`).

**CSP-08.** `BrokerPort.recent_candles` SHALL be removed from the abstract port and from `CapitalBrokerAdapter`. No caller in the domain or application layer SHALL reference `BrokerPort.recent_candles` after this change.

### Acceptance Criteria

**AC-CSP-1 — Idempotent upsert**
Given a `PostgresCandleStore` connected to the test database,
when `upsert_candle` is called twice with the same `(epic, resolution, candle_start)` and different OHLC values on the second call,
then the database contains exactly one row for that key and its OHLC values reflect the second call.

**AC-CSP-2 — recent_candles returns oldest-first mid-derived candles**
Given the store contains 5 rows for symbol "EURUSD" with candle_start values T1 < T2 < T3 < T4 < T5,
when `recent_candles("EURUSD", 3)` is called,
then the result contains exactly 3 `Candle` objects in order [T3, T4, T5] (oldest-first),
and each candle's `open` equals `(open_bid + open_ask) / 2` for that row (same for high, low, close).

**AC-CSP-3 — recent_candles respects count cap**
Given the store contains 10 rows for a symbol,
when `recent_candles(symbol, 3)` is called,
then exactly 3 candles are returned.

**AC-CSP-4 — Empty store returns empty sequence**
Given no rows exist for a symbol,
when `recent_candles(symbol, 10)` is called,
then an empty sequence is returned (no exception raised).

**AC-CSP-5 — last_candle_start returns None on empty store**
Given no rows exist for `(symbol, resolution)`,
when `last_candle_start(symbol, resolution)` is called,
then `None` is returned.

**AC-CSP-6 — last_candle_start returns the newest candle_start**
Given rows exist with candle_start values T1 < T2 < T3 for `(symbol, resolution)`,
when `last_candle_start(symbol, resolution)` is called,
then `T3` is returned (UTC-aware datetime).

**AC-CSP-7 — mid formula correctness**
Given a row with `open_bid=1.0, open_ask=1.2` (and matching high/low/close values),
when `recent_candles` returns that row as a `Candle`,
then `candle.open == 1.1` (i.e., exactly `(1.0 + 1.2) / 2`).

**AC-CSP-8 — Migration is discovered automatically**
Given the migration runner is invoked on a fresh database that already has `001_create_trade_entries.sql` applied,
when it runs again with `002_create_candles.sql` present,
then the `candles` table exists and `schema_migrations` contains `002_create_candles`.

---

## Capability: ws-candle-ingestion (new)

### Requirements

**WCI-01.** A `CapitalWsIngester` class SHALL exist in `src/infrastructure/capital/ws_ingester.py`. It SHALL depend on `CandleStorePort` (injected), not on any Postgres type directly.

**WCI-02.** On startup, `CapitalWsIngester` SHALL:
1. Connect to `{streaming_host}/connect` and subscribe `OHLCMarketData` for all configured epics and the configured resolution.
2. Begin buffering incoming WS events (do NOT upsert yet).
3. Backfill via REST if the store is empty for any configured epic: fetch at least `required_candles` closed candles and upsert them via `CandleStorePort.upsert_candle`.
4. Gap-fill via REST if the store has rows: fetch the range from `last_candle_start + 1 period` through the current time and upsert.
5. Only after backfill/gap-fill completes, process buffered events and begin processing live events.

**WCI-03.** After startup, the store SHALL be contiguous up to the last CLOSED candle before the first live event is trusted. There SHALL be no missing bars between the oldest backfilled candle and the newest received live candle.

**WCI-04.** `CapitalWsIngester` SHALL parse `ohlc.event` messages with fields: `epic` (string), `resolution` (string), `t` (epoch milliseconds UTC), `o`/`h`/`l`/`c` (OHLC values), `priceType` (`"bid"` or `"ask"`).

**WCI-05.** `CapitalWsIngester` SHALL buffer partial pairs by `(epic, resolution, t)`. A row SHALL be upserted via `CandleStorePort.upsert_candle` only when BOTH the bid event AND the ask event for the same `(epic, resolution, t)` have been received. A bid-only or ask-only event SHALL NOT trigger an upsert.

**WCI-06.** The timestamp in the upserted `CandleRow.candle_start` SHALL equal `datetime.fromtimestamp(t / 1000, tz=timezone.utc)` where `t` is the epoch-ms value from the WS event.

**WCI-07.** `CapitalWsIngester` SHALL send a WebSocket ping every `ws_ping_interval_seconds` seconds (configurable, default 540, MUST be < 600) to prevent the 10-minute WS cutoff.

**WCI-08.** `CapitalWsIngester` SHALL reconnect and re-subscribe on disconnect (both on proactive pre-cutoff reconnect and on unexpected drop). After reconnect, it SHALL re-run the gap-fill step before resuming live event processing. Reconnect backoff policy (timing and retry cap) is deferred to design.

**WCI-09.** An `ingestion.py` entry point SHALL exist at `src/ingestion.py`, structured as a long-running process analogous to `src/reconciler.py`. It SHALL be independently runnable (`python -m ingestion`).

**WCI-10.** `Config` SHALL include new fields: `ws_ping_interval_seconds: int` (default 540) and `required_candles: int` (reuses existing strategy value or separate config key — resolved in design). Library dependency for WS client SHALL be added to `pyproject.toml` (library choice deferred to design).

### Acceptance Criteria

**AC-WCI-1 — Bid alone does not write a row**
Given a mock `CandleStorePort` and a `CapitalWsIngester` instance with startup complete,
when an `ohlc.event` for `priceType="bid"` arrives for `(epic="EURUSD", resolution="MINUTE_15", t=T)`,
then `upsert_candle` is NOT called.

**AC-WCI-2 — Bid then ask writes exactly one row**
Given a mock `CandleStorePort` and a `CapitalWsIngester` instance with startup complete,
when an `ohlc.event` for `priceType="bid"` arrives for `(epic, resolution, t=T)` followed by `priceType="ask"` for the same `(epic, resolution, t=T)`,
then `upsert_candle` is called exactly once with a `CandleRow` whose bid and ask OHLC values match the respective events and `candle_start == datetime.fromtimestamp(T / 1000, tz=timezone.utc)`.

**AC-WCI-3 — Ask then bid also writes exactly one row**
Given the same setup as AC-WCI-2 but events arrive ask-first,
then the same single `upsert_candle` call occurs with correct values.

**AC-WCI-4 — Different epics buffered independently**
Given bid event for EURUSD and bid event for GBPUSD arrive (no matching ask for either),
then `upsert_candle` is NOT called for either.
When the ask for EURUSD then arrives,
then `upsert_candle` is called exactly once for EURUSD and NOT for GBPUSD.

**AC-WCI-5 — Empty store triggers full backfill**
Given `CandleStorePort.last_candle_start` returns `None` for all configured epics,
when `CapitalWsIngester` starts up,
then it makes a REST history request for at least `required_candles` candles and calls `upsert_candle` for each returned candle.

**AC-WCI-6 — Non-empty store triggers gap-fill only**
Given `CandleStorePort.last_candle_start` returns datetime `T_last` for an epic,
when `CapitalWsIngester` starts up,
then it makes a REST history request for the range `[T_last + 1 period, now]` only (not a full backfill), and does NOT request candles already covered by `T_last`.

**AC-WCI-7 — Duplicate candle from overlap is idempotent**
Given a candle for `(epic, resolution, T)` was already stored by backfill,
when a live WS pair for the same `(epic, resolution, T)` arrives and triggers `upsert_candle`,
then the store contains exactly one row for that key (idempotency enforced by the store, not the ingester).

**AC-WCI-8 — Epoch-ms timestamp conversion**
Given an `ohlc.event` with `t=1_700_000_000_000` (epoch ms),
when the event is processed,
then `CandleRow.candle_start` equals `datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)`.

---

## Capability: trading-cycle (modified)

### Requirements

**TC-01.** `RunTradingCycleUseCase` SHALL accept a `CandleStorePort` dependency (constructor injection) in place of reading candles from `BrokerPort`. The `BrokerPort` dependency remains for `open_position` and `has_open_position`.

**TC-02.** `RunTradingCycleUseCase.execute` SHALL call `candle_store.recent_candles(symbol, strategy.required_candles)` to obtain candles.

**TC-03.** The freshness retry loop (current `trading_cycle.py:53-66`) SHALL be removed entirely. No REST retry, no `freshness_max_retries`, no `freshness_retry_seconds` in the constructor or config.

**TC-04.** `RunTradingCycleUseCase.execute` SHALL perform a single staleness check: if the store's newest candle's `timestamp` does not equal `expected_decision_ts`, it SHALL log a warning and return `None`. No retry, no broker call.

**TC-05.** If `candle_store.recent_candles` returns fewer items than `strategy.required_candles`, `execute` SHALL return `None` without raising. This is the startup-race guard.

**TC-06.** When the store is both fresh (newest candle == expected boundary) and full (count >= required_candles), `execute` SHALL call `strategy.evaluate(candles)` and, if a signal is returned, call `broker.open_position` — the order path is unchanged.

### Acceptance Criteria

**AC-TC-1 — Short store returns None**
Given `CandleStorePort.recent_candles` returns 5 candles when `required_candles` is 128,
when `execute` is called,
then the return value is `None` and `broker.open_position` is NOT called.

**AC-TC-2 — Stale store returns None without retry**
Given the store returns 128 candles but the newest candle's timestamp does not equal `expected_decision_ts`,
when `execute` is called,
then the return value is `None`, a warning is logged, and `broker.recent_candles` is NEVER called (the method no longer exists on `BrokerPort`).

**AC-TC-3 — Fresh full store calls strategy then broker**
Given the store returns exactly 128 candles with the newest timestamp equal to `expected_decision_ts`,
and `strategy.evaluate` returns a non-None signal,
when `execute` is called,
then `broker.open_position` is called exactly once with the signal.

**AC-TC-4 — No retry parameters in constructor**
The `RunTradingCycleUseCase.__init__` signature SHALL NOT include `freshness_max_retries` or `freshness_retry_seconds`.

**AC-TC-5 — No open position skips cycle**
Given `broker.has_open_position` returns `True`,
when `execute` is called,
then `candle_store.recent_candles` is NOT called and the return value is `None`.

---

## Capability: capital-session (modified)

### Requirements

**CS-01.** `CapitalSession.authenticate()` SHALL parse the POST /session response body as JSON and store the value of the `streamingHost` key internally.

**CS-02.** `CapitalSession` SHALL expose a `streaming_host: str` property. Accessing this property before `authenticate()` has been called successfully SHALL raise `RuntimeError`.

**CS-03.** `CapitalSession.authenticate()` SHALL continue to return `SessionTokens` (unchanged return type). The `SessionTokens` dataclass SHALL NOT be modified.

**CS-04.** `CapitalSession.tokens()` behavior SHALL remain unchanged.

### Acceptance Criteria

**AC-CS-1 — streaming_host is available after authenticate**
Given a mock HTTP client whose POST /session response body contains `{"streamingHost": "https://streaming.capital.com"}` with a valid CST and X-SECURITY-TOKEN header,
when `authenticate()` is called,
then `session.streaming_host` returns `"https://streaming.capital.com"`.

**AC-CS-2 — streaming_host raises before authenticate**
Given a freshly constructed `CapitalSession`,
when `session.streaming_host` is accessed before `authenticate()`,
then `RuntimeError` is raised.

**AC-CS-3 — authenticate still returns SessionTokens**
Given the same mock HTTP client,
when `authenticate()` is called,
then the return value is a `SessionTokens` with the correct `cst` and `security_token` values (unchanged behavior).

**AC-CS-4 — tokens() unaffected**
Given `authenticate()` has been called,
when `session.tokens()` is called,
then it returns the same `SessionTokens` as the `authenticate()` return value.

---

## Out of Scope (deferred to design)

- WebSocket client library choice (`websockets` async vs `websocket-client` sync).
- Exact reconnect backoff numbers (retry count, base interval, cap).
- Whether `ingestion.py` uses `asyncio`, threads, or a sync event loop.
- Connection pool vs single-connection for `PostgresCandleStore` in the ingestion process.
- Exact REST endpoint parameter shape for backfill/gap-fill requests.
- Docker Compose / deployment topology for the third process.
- Whether `required_candles` is a separate config key or read from the strategy at wiring time.

---

## Test Impact Summary

| Area | Change |
|------|--------|
| `BrokerPort` test doubles | Remove `recent_candles` stub; only `open_position` + `has_open_position` remain |
| `RunTradingCycleUseCase` tests | Delete freshness-guard tests; add short-store and stale-store tests against `CandleStorePort` mock |
| New: `PostgresCandleStore` | Integration tests against a real test DB; covers AC-CSP-1 through AC-CSP-7 |
| New: `CapitalWsIngester` | Unit tests with mock `CandleStorePort` and mock WS/REST; covers AC-WCI-1 through AC-WCI-8 |
| New: `CapitalSession` | Unit test with mock HTTP; covers AC-CS-1 through AC-CS-4 |
| Migration runner | Integration test for AC-CSP-8 |
