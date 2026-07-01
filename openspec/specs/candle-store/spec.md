# Spec: candle-store

**Capability:** candle-store
**Status:** active
**Source:** ws-candle-ingestion change

---

## Overview

Introduces a domain port `CandleStorePort` and a Postgres adapter `PostgresCandleStore` as the single source of truth for closed candle data. The store persists raw bid+ask OHLC and derives mid at read time. A new `candles` table is created via migration `002_create_candles.sql`. `BrokerPort.recent_candles` is removed.

---

## Requirements

**CSP-01.** A domain port `CandleStorePort` SHALL declare three abstract methods:
- `recent_candles(symbol: str, resolution: str, count: int) -> Sequence[Candle]` — returns up to `count` most-recently CLOSED candles for `(symbol, resolution)`, ordered oldest-first, with OHLC derived as `mid = (bid + ask) / 2` per field.
- `last_candle_start(symbol: str, resolution: str) -> datetime | None` — returns the `candle_start` of the most recent row for `(symbol, resolution)`, or `None` if none exists.
- `upsert_candle(row: CandleRow) -> None` — writes or overwrites a single candle row identified by `(epic, resolution, candle_start)`.

#### Scenario: port declares the three abstract methods with correct signatures
Given the `CandleStorePort` ABC,
when its abstract interface is inspected,
then `recent_candles(symbol, resolution, count)`, `last_candle_start(symbol, resolution)`, and `upsert_candle(row)` are all present as abstract methods.

---

**CSP-02.** `CandleRow` SHALL be a value object (frozen dataclass or equivalent) carrying: `epic: str`, `resolution: str`, `candle_start: datetime` (UTC-aware), `open_bid: float`, `high_bid: float`, `low_bid: float`, `close_bid: float`, `open_ask: float`, `high_ask: float`, `low_ask: float`, `close_ask: float`.

#### Scenario: CandleRow is immutable
Given a `CandleRow` instance,
when an attempt is made to set any field after construction,
then an `AttributeError` (or equivalent frozen-dataclass error) is raised.

---

**CSP-03.** `CandleStorePort` SHALL live in `src/domain/ports/candle_store_port.py`. It is a domain-layer abstraction with no infrastructure imports.

#### Scenario: no infrastructure imports in the port module
Given `src/domain/ports/candle_store_port.py`,
when the module is imported in isolation (no infrastructure packages available),
then it loads without `ImportError`.

---

**CSP-04.** A `PostgresCandleStore` adapter SHALL implement `CandleStorePort`. `upsert_candle` SHALL be idempotent: inserting a row with the same `(epic, resolution, candle_start)` twice produces exactly one row in the database (`ON CONFLICT (epic, resolution, candle_start) DO UPDATE`).

#### Scenario: idempotent upsert (AC-CSP-1)
Given a `PostgresCandleStore` connected to the test database,
when `upsert_candle` is called twice with the same `(epic, resolution, candle_start)` and different OHLC values on the second call,
then the database contains exactly one row for that key and its OHLC values reflect the second call.

---

**CSP-05.** `PostgresCandleStore.recent_candles` SHALL query using both `epic` and `resolution` as filter predicates (SQL includes `AND resolution = %s`), fetch the N rows with the largest `candle_start`, then return them ordered oldest-first with OHLC derived as `mid = (bid_col + ask_col) / 2` for each of open, high, low, close. The returned objects SHALL be `Candle` entities as defined in `src/domain/entities/candle.py` (unchanged entity, unchanged invariants). Each `Candle.open`, `.high`, `.low`, `.close` value SHALL be of type `float` (not `Decimal`).

#### Scenario: recent_candles returns oldest-first mid-derived candles (AC-CSP-2)
Given the store contains 5 rows for `(symbol="EURUSD", resolution="MINUTE_15")` with candle_start values T1 < T2 < T3 < T4 < T5,
when `recent_candles("EURUSD", "MINUTE_15", 3)` is called,
then the result contains exactly 3 `Candle` objects in order [T3, T4, T5] (oldest-first),
and each candle's `open` equals `(open_bid + open_ask) / 2` for that row (same for high, low, close).

#### Scenario: recent_candles respects count cap (AC-CSP-3)
Given the store contains 10 rows for `(symbol, resolution)`,
when `recent_candles(symbol, resolution, 3)` is called,
then exactly 3 candles are returned.

#### Scenario: empty store returns empty sequence (AC-CSP-4)
Given no rows exist for `(symbol, resolution)`,
when `recent_candles(symbol, resolution, 10)` is called,
then an empty sequence is returned (no exception raised).

#### Scenario: mid formula correctness (AC-CSP-7)
Given a row with `open_bid=1.0, open_ask=1.2` (and matching high/low/close values),
when `recent_candles` returns that row as a `Candle`,
then `candle.open == 1.1` (i.e., exactly `(1.0 + 1.2) / 2`) and the value is of type `float`.

#### Scenario: SQL filters by resolution (W1 resolution fix)
Given the store contains rows for `(epic="EURUSD", resolution="MINUTE_15")` and rows for `(epic="EURUSD", resolution="HOUR")`,
when `recent_candles("EURUSD", "HOUR", 3)` is called,
then the SQL executed includes `resolution = %s` with the value `"HOUR"`,
and no MINUTE_15 rows are returned.

---

**CSP-05a.** `recent_candles` SHALL filter by BOTH `symbol` (mapped to `epic`) AND `resolution`, so that reads for different timeframes on the same epic are always isolated. Rows for `MINUTE_15` and `HOUR` on the same epic SHALL never appear in the same result set.

#### Scenario: multi-timeframe reads are isolated (AC-CSP-resolution-isolation)
Given the store contains 5 MINUTE_15 rows and 5 HOUR rows all for `epic="EURUSD"`,
when `recent_candles("EURUSD", "MINUTE_15", 10)` is called,
then all 5 returned candles correspond to MINUTE_15 candle_start values and no HOUR rows are mixed in.

---

**CSP-06.** `PostgresCandleStore.last_candle_start` SHALL return `None` when no rows exist for the given `(symbol, resolution)`.

#### Scenario: last_candle_start returns None on empty store (AC-CSP-5)
Given no rows exist for `(symbol, resolution)`,
when `last_candle_start(symbol, resolution)` is called,
then `None` is returned.

#### Scenario: last_candle_start returns the newest candle_start (AC-CSP-6)
Given rows exist with candle_start values T1 < T2 < T3 for `(symbol, resolution)`,
when `last_candle_start(symbol, resolution)` is called,
then `T3` is returned (UTC-aware datetime).

---

**CSP-07.** Migration `002_create_candles.sql` SHALL create a table `candles` with columns: `epic TEXT NOT NULL`, `resolution TEXT NOT NULL`, `candle_start TIMESTAMPTZ NOT NULL`, `open_bid NUMERIC NOT NULL`, `high_bid NUMERIC NOT NULL`, `low_bid NUMERIC NOT NULL`, `close_bid NUMERIC NOT NULL`, `open_ask NUMERIC NOT NULL`, `high_ask NUMERIC NOT NULL`, `low_ask NUMERIC NOT NULL`, `close_ask NUMERIC NOT NULL`, and a `UNIQUE(epic, resolution, candle_start)` constraint. The migration file SHALL be discoverable by the existing migration runner via alphabetical filename sort (prefix `002_`).

#### Scenario: migration is discovered automatically (AC-CSP-8)
Given the migration runner is invoked on a fresh database that already has `001_create_trade_entries.sql` applied,
when it runs again with `002_create_candles.sql` present,
then the `candles` table exists and `schema_migrations` contains `002_create_candles`.

---

**CSP-08.** `BrokerPort.recent_candles` SHALL be removed from the abstract port and from `CapitalBrokerAdapter`. No caller in the domain or application layer SHALL reference `BrokerPort.recent_candles` after this change.

#### Scenario: BrokerPort no longer declares recent_candles
Given the `BrokerPort` ABC after this change,
when its interface is inspected,
then `recent_candles` is NOT present as a method.

---
