# Spec: ws-candle-ingestion

**Capability:** ws-candle-ingestion
**Status:** active
**Source:** ws-candle-ingestion change

---

## Overview

Introduces `CapitalWsIngester`, a synchronous WebSocket client that subscribes to Capital's `OHLCMarketData` stream, pairs bid and ask events by `(epic, resolution, t)`, and upserts completed `CandleRow` objects into `CandleStorePort`. A new long-running entry point `src/ingestion.py` owns the process. Startup follows a backfill-once / gap-fill-on-recovery / live-append lifecycle to guarantee store contiguity.

---

## Requirements

**WCI-01.** A `CapitalWsIngester` class SHALL exist in `src/infrastructure/capital/ws_ingester.py`. It SHALL depend on `CandleStorePort` (injected), not on any Postgres type directly.

#### Scenario: ingester depends only on the port abstraction
Given a `CapitalWsIngester` constructed with a mock `CandleStorePort`,
when it is instantiated without a `PostgresCandleStore` import,
then no `ImportError` is raised.

---

**WCI-02.** On startup, `CapitalWsIngester` SHALL:
1. Connect to `{streaming_host}/connect` and subscribe `OHLCMarketData` for all configured epics and the configured resolution.
2. Begin buffering incoming WS events (do NOT upsert yet).
3. Backfill via REST if the store is empty for any configured epic: fetch at least `required_candles` closed candles and upsert them via `CandleStorePort.upsert_candle`.
4. Gap-fill via REST if the store has rows: fetch the range from `last_candle_start + 1 period` through the current time and upsert.
5. Only after backfill/gap-fill completes, process buffered events and begin processing live events.

#### Scenario: empty store triggers full backfill (AC-WCI-5)
Given `CandleStorePort.last_candle_start` returns `None` for all configured epics,
when `CapitalWsIngester` starts up,
then it makes a REST history request for at least `required_candles` candles and calls `upsert_candle` for each returned candle.

#### Scenario: non-empty store triggers gap-fill only (AC-WCI-6)
Given `CandleStorePort.last_candle_start` returns datetime `T_last` for an epic,
when `CapitalWsIngester` starts up,
then it makes a REST history request for the range `[T_last + 1 period, now]` only (not a full backfill), and does NOT request candles already covered by `T_last`.

---

**WCI-03.** After startup, the store SHALL be contiguous up to the last CLOSED candle before the first live event is trusted. There SHALL be no missing bars between the oldest backfilled candle and the newest received live candle.

#### Scenario: backfill-live seam has no gap
Given a cold start with an empty store and a WS stream that buffered 3 live events during backfill,
when startup completes,
then the buffered events are processed after backfill, the store is contiguous with no missing bars at the seam, and upsert is idempotent for any overlap.

---

**WCI-04.** `CapitalWsIngester` SHALL parse `ohlc.event` messages with fields: `epic` (string), `resolution` (string), `t` (epoch milliseconds UTC), `o`/`h`/`l`/`c` (OHLC values), `priceType` (`"bid"` or `"ask"`).

#### Scenario: ohlc.event fields are parsed correctly
Given a raw `ohlc.event` JSON message with `epic="EURUSD"`, `resolution="MINUTE_15"`, `t=1700000000000`, `o=1.08`, `h=1.09`, `l=1.07`, `c=1.085`, `priceType="bid"`,
when the ingester processes the message,
then the parsed values match those fields exactly.

---

**WCI-05.** `CapitalWsIngester` SHALL buffer partial pairs by `(epic, resolution, t)`. A row SHALL be upserted via `CandleStorePort.upsert_candle` only when BOTH the bid event AND the ask event for the same `(epic, resolution, t)` have been received. A bid-only or ask-only event SHALL NOT trigger an upsert.

#### Scenario: bid alone does not write a row (AC-WCI-1)
Given a mock `CandleStorePort` and a `CapitalWsIngester` instance with startup complete,
when an `ohlc.event` for `priceType="bid"` arrives for `(epic="EURUSD", resolution="MINUTE_15", t=T)`,
then `upsert_candle` is NOT called.

#### Scenario: bid then ask writes exactly one row (AC-WCI-2)
Given a mock `CandleStorePort` and a `CapitalWsIngester` instance with startup complete,
when an `ohlc.event` for `priceType="bid"` arrives for `(epic, resolution, t=T)` followed by `priceType="ask"` for the same `(epic, resolution, t=T)`,
then `upsert_candle` is called exactly once with a `CandleRow` whose bid and ask OHLC values match the respective events and `candle_start == datetime.fromtimestamp(T / 1000, tz=timezone.utc)`.

#### Scenario: ask then bid also writes exactly one row (AC-WCI-3)
Given the same setup as AC-WCI-2 but events arrive ask-first,
then the same single `upsert_candle` call occurs with correct values.

#### Scenario: different epics buffered independently (AC-WCI-4)
Given bid event for EURUSD and bid event for GBPUSD arrive (no matching ask for either),
then `upsert_candle` is NOT called for either.
When the ask for EURUSD then arrives,
then `upsert_candle` is called exactly once for EURUSD and NOT for GBPUSD.

---

**WCI-06.** The timestamp in the upserted `CandleRow.candle_start` SHALL equal `datetime.fromtimestamp(t / 1000, tz=timezone.utc)` where `t` is the epoch-ms value from the WS event.

#### Scenario: epoch-ms timestamp conversion (AC-WCI-8)
Given an `ohlc.event` with `t=1_700_000_000_000` (epoch ms),
when the event is processed,
then `CandleRow.candle_start` equals `datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)`.

---

**WCI-07.** `CapitalWsIngester` SHALL send a WebSocket ping every `ws_ping_interval_seconds` seconds (configurable, default 540, MUST be < 600) to prevent the 10-minute WS cutoff.

#### Scenario: ping interval is below WS cutoff
Given a `Config` with `ws_ping_interval_seconds=540`,
when the ingester is running,
then a WS ping is sent at least once every 540 seconds (and the configured value must be < 600).

---

**WCI-08.** `CapitalWsIngester` SHALL reconnect and re-subscribe on disconnect (both on proactive pre-cutoff reconnect and on unexpected drop). After reconnect, it SHALL re-run the gap-fill step before resuming live event processing. Reconnect backoff policy (timing and retry cap) is deferred to design.

#### Scenario: reconnect re-runs gap-fill
Given the WS connection drops unexpectedly,
when the ingester reconnects and re-subscribes,
then it calls `last_candle_start` and performs a gap-fill REST request before processing any new live events.

#### Scenario: duplicate candle from overlap is idempotent (AC-WCI-7)
Given a candle for `(epic, resolution, T)` was already stored by backfill,
when a live WS pair for the same `(epic, resolution, T)` arrives and triggers `upsert_candle`,
then the store contains exactly one row for that key (idempotency enforced by the store, not the ingester).

---

**WCI-09.** An `ingestion.py` entry point SHALL exist at `src/ingestion.py`, structured as a long-running process analogous to `src/reconciler.py`. It SHALL be independently runnable (`python -m ingestion`).

#### Scenario: ingestion entry point is independently invocable
Given `src/ingestion.py` exists,
when `python -m ingestion` is executed (with required environment variables set),
then the process starts without `ImportError` or `AttributeError`.

---

**WCI-10.** `Config` SHALL include new fields: `ws_ping_interval_seconds: int` (default 540) and `required_candles: int`. A WS client library (`websocket-client>=1.9,<2`) SHALL be declared as a dependency in `pyproject.toml`.

#### Scenario: Config exposes ws_ping_interval_seconds and required_candles
Given a `Config` instance built from environment,
when `config.ws_ping_interval_seconds` and `config.required_candles` are accessed,
then they return integer values with `ws_ping_interval_seconds < 600`.

---
