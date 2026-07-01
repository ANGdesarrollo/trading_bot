# Delta for candle-store

## MODIFIED Requirements

### Requirement: CSP-01 — Port Interface

`CandleStorePort` SHALL declare three abstract methods:
- `recent_candles(provider: str, symbol: str, resolution: str, count: int) -> Sequence[Candle]` — returns up to `count` most-recently CLOSED candles for `(provider, symbol, resolution)`, ordered oldest-first, with OHLC derived as `mid = (bid + ask) / 2` per field. `provider` defaults to `"capital"`.
- `last_candle_start(provider: str, symbol: str, resolution: str) -> datetime | None` — returns the `candle_start` of the most recent row for `(provider, symbol, resolution)`, or `None` if none exists. `provider` defaults to `"capital"`.
- `upsert_candle(row: CandleRow) -> None` — writes or overwrites a single candle row identified by `(provider, epic, resolution, candle_start)`.

(Previously: signatures for `recent_candles` and `last_candle_start` did not include a `provider` parameter; `upsert_candle` identified rows by `(epic, resolution, candle_start)`.)

#### Scenario: port declares three abstract methods with updated signatures

- GIVEN the `CandleStorePort` ABC after this change
- WHEN its abstract interface is inspected
- THEN `recent_candles(provider, symbol, resolution, count)`, `last_candle_start(provider, symbol, resolution)`, and `upsert_candle(row)` are all present as abstract methods
- AND `provider` has a default value of `"capital"` in both read methods

---

### Requirement: CSP-02 — CandleRow Value Object

`CandleRow` SHALL be a frozen value object carrying: `provider: str`, `epic: str`, `resolution: str`, `candle_start: datetime` (UTC-aware), `open_bid: float`, `high_bid: float`, `low_bid: float`, `close_bid: float`, `open_ask: float`, `high_ask: float`, `low_ask: float`, `close_ask: float`. The `provider` field SHALL default to `"capital"`.

(Previously: `CandleRow` did not carry a `provider` field.)

#### Scenario: CandleRow is immutable

- GIVEN a `CandleRow` instance
- WHEN an attempt is made to set any field after construction
- THEN an `AttributeError` (or equivalent frozen-dataclass error) is raised

#### Scenario: CandleRow carries provider

- GIVEN a `CandleRow` constructed without an explicit `provider` argument
- WHEN `row.provider` is accessed
- THEN it equals `"capital"`

#### Scenario: CandleRow accepts explicit provider

- GIVEN a `CandleRow` constructed with `provider="ic_markets"`
- WHEN `row.provider` is accessed
- THEN it equals `"ic_markets"`

---

### Requirement: CSP-04 — PostgresCandleStore Idempotent Upsert

`PostgresCandleStore` SHALL implement `CandleStorePort`. `upsert_candle` SHALL be idempotent: inserting a row with the same `(provider, epic, resolution, candle_start)` twice produces exactly one row in the database (`ON CONFLICT (provider, epic, resolution, candle_start) DO UPDATE`).

(Previously: conflict key was `(epic, resolution, candle_start)`.)

#### Scenario: idempotent upsert with provider key (AC-CSP-1)

- GIVEN a `PostgresCandleStore` connected to the test database
- WHEN `upsert_candle` is called twice with the same `(provider, epic, resolution, candle_start)` and different OHLC values on the second call
- THEN the database contains exactly one row for that key and its OHLC values reflect the second call

#### Scenario: rows from different providers on the same epic coexist

- GIVEN `upsert_candle` is called for `provider="capital", epic="EURUSD", resolution="MINUTE_15", candle_start=T1`
- AND `upsert_candle` is called for `provider="ic_markets", epic="EURUSD", resolution="MINUTE_15", candle_start=T1`
- WHEN the `candles` table is queried
- THEN two rows exist — one per provider — with no unique constraint violation

---

### Requirement: CSP-05 — PostgresCandleStore.recent_candles

`PostgresCandleStore.recent_candles` SHALL filter by `provider`, `epic`, and `resolution`, fetch the N rows with the largest `candle_start`, then return them ordered oldest-first with OHLC derived as `mid = (bid_col + ask_col) / 2`. The returned objects SHALL be `Candle` entities. Each `Candle.open`, `.high`, `.low`, `.close` SHALL be of type `float`.

(Previously: filter did not include `provider`.)

#### Scenario: recent_candles returns oldest-first mid-derived candles (AC-CSP-2)

- GIVEN the store contains 5 rows for `(provider="capital", symbol="EURUSD", resolution="MINUTE_15")` with candle_start values T1 < T2 < T3 < T4 < T5
- WHEN `recent_candles("capital", "EURUSD", "MINUTE_15", 3)` is called
- THEN the result contains exactly 3 `Candle` objects in order [T3, T4, T5] (oldest-first)
- AND each candle's `open` equals `(open_bid + open_ask) / 2` for that row

#### Scenario: recent_candles isolates by provider

- GIVEN 5 rows for `provider="capital", epic="EURUSD", resolution="MINUTE_15"`
- AND 5 rows for `provider="ic_markets", epic="EURUSD", resolution="MINUTE_15"`
- WHEN `recent_candles("capital", "EURUSD", "MINUTE_15", 10)` is called
- THEN exactly 5 candles are returned, all belonging to `provider="capital"`

#### Scenario: recent_candles respects count cap (AC-CSP-3)

- GIVEN the store contains 10 rows for `(provider, symbol, resolution)`
- WHEN `recent_candles(provider, symbol, resolution, 3)` is called
- THEN exactly 3 candles are returned

#### Scenario: empty store returns empty sequence (AC-CSP-4)

- GIVEN no rows exist for `(provider, symbol, resolution)`
- WHEN `recent_candles(provider, symbol, resolution, 10)` is called
- THEN an empty sequence is returned (no exception raised)

#### Scenario: mid formula correctness (AC-CSP-7)

- GIVEN a row with `open_bid=1.0, open_ask=1.2`
- WHEN `recent_candles` returns that row as a `Candle`
- THEN `candle.open == 1.1` and the value is of type `float`

#### Scenario: SQL filters by resolution (W1 resolution fix)

- GIVEN rows for `(provider="capital", epic="EURUSD", resolution="MINUTE_15")` and `(provider="capital", epic="EURUSD", resolution="HOUR")`
- WHEN `recent_candles("capital", "EURUSD", "HOUR", 3)` is called
- THEN no MINUTE_15 rows are returned

---

### Requirement: CSP-05a — Multi-Timeframe Read Isolation

`recent_candles` SHALL filter by `provider`, `symbol`, and `resolution` so that reads for different timeframes on the same epic are always isolated. Rows for `MINUTE_15` and `HOUR` on the same epic and provider SHALL never appear in the same result set.

(Previously: filter included `symbol` and `resolution` only, not `provider`.)

#### Scenario: multi-timeframe reads are isolated (AC-CSP-resolution-isolation)

- GIVEN the store contains 5 MINUTE_15 rows and 5 HOUR rows all for `provider="capital", epic="EURUSD"`
- WHEN `recent_candles("capital", "EURUSD", "MINUTE_15", 10)` is called
- THEN all 5 returned candles correspond to MINUTE_15 candle_start values and no HOUR rows are mixed in

---

### Requirement: CSP-06 — last_candle_start

`PostgresCandleStore.last_candle_start` SHALL return `None` when no rows exist for the given `(provider, symbol, resolution)`. It SHALL filter by all three dimensions.

(Previously: filter used `(symbol, resolution)` only.)

#### Scenario: last_candle_start returns None on empty store (AC-CSP-5)

- GIVEN no rows exist for `(provider, symbol, resolution)`
- WHEN `last_candle_start(provider, symbol, resolution)` is called
- THEN `None` is returned

#### Scenario: last_candle_start returns the newest candle_start (AC-CSP-6)

- GIVEN rows exist with candle_start values T1 < T2 < T3 for `(provider="capital", symbol="EURUSD", resolution="MINUTE_15")`
- WHEN `last_candle_start("capital", "EURUSD", "MINUTE_15")` is called
- THEN `T3` is returned (UTC-aware datetime)

#### Scenario: last_candle_start isolates by provider

- GIVEN rows exist for `provider="capital"` up to T3 and rows for `provider="ic_markets"` up to T5, same epic and resolution
- WHEN `last_candle_start("capital", "EURUSD", "MINUTE_15")` is called
- THEN `T3` is returned, not T5

---

### Requirement: CSP-07 — Schema Migration

Migration `003_add_provider_to_candles.sql` SHALL:
1. Add a `provider TEXT NOT NULL DEFAULT 'capital'` column to the `candles` table.
2. Drop the existing `UNIQUE(epic, resolution, candle_start)` constraint.
3. Drop the existing `idx_candles_recent` index.
4. Add a `UNIQUE(provider, epic, resolution, candle_start)` constraint.
5. Add a new index that prefixes provider (`idx_candles_recent` or equivalent) on `(provider, epic, resolution, candle_start DESC)`.

Existing rows SHALL automatically receive `provider = 'capital'` via the column default. The migration SHALL be idempotent (`IF EXISTS` / `IF NOT EXISTS`). Migration `002_create_candles.sql` MUST have been applied before `003` runs.

(Previously: CSP-07 specified migration `002_create_candles.sql` and the original table structure without `provider`.)

#### Scenario: migration adds provider column and rebuilds index

- GIVEN migration `002_create_candles.sql` has been applied and the `candles` table exists with existing rows
- WHEN migration `003_add_provider_to_candles.sql` is applied
- THEN the `candles` table has a `provider` column
- AND all pre-existing rows have `provider = 'capital'`
- AND the unique constraint is `(provider, epic, resolution, candle_start)`
- AND the old `UNIQUE(epic, resolution, candle_start)` constraint no longer exists

#### Scenario: migration is idempotent

- GIVEN migration `003` has already been applied
- WHEN it is applied again
- THEN no error is raised and the table structure remains correct

---

## ADDED Requirements

### Requirement: CSP-09 — Provider Config Source

`Config` SHALL expose a `provider: str` attribute sourced from the `PROVIDER` environment variable, defaulting to `"capital"` when the variable is absent or empty.

#### Scenario: provider defaults to "capital" when env var absent

- GIVEN the `PROVIDER` environment variable is not set
- WHEN `Config` is instantiated
- THEN `config.provider` equals `"capital"`

#### Scenario: provider reads from PROVIDER env var

- GIVEN the `PROVIDER` environment variable is set to `"ic_markets"`
- WHEN `Config` is instantiated
- THEN `config.provider` equals `"ic_markets"`

---

### Requirement: CSP-10 — Trade Entries Provider Column

Migration `004_add_provider_to_trade_entries.sql` SHALL add a `provider TEXT NOT NULL DEFAULT 'capital'` column to the `trade_entries` table. Existing rows SHALL automatically receive `provider = 'capital'`. The migration SHALL be idempotent.

#### Scenario: migration adds provider to trade_entries

- GIVEN the `trade_entries` table exists with existing rows
- WHEN migration `004_add_provider_to_trade_entries.sql` is applied
- THEN the table has a `provider` column
- AND all pre-existing rows have `provider = 'capital'`

---
