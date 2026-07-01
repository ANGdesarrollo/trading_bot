# Apply Progress: ws-candle-ingestion — Slice 1

**Status:** COMPLETE (tasks 1.1–1.19 all done)
**Suite result:** 157 passed, 18 skipped (integration tests skip correctly when DATABASE_URL not set)

---

## Tasks Completed

- [x] 1.1 RED `tests/unit/test_candle_row.py` — 4 tests, all RED confirmed
- [x] 1.2 GREEN `src/domain/entities/candle_row.py` — frozen dataclass, 11 fields, UTC invariant
- [x] 1.3 RED `tests/unit/test_candle_store_port.py` — 3 tests, all RED confirmed
- [x] 1.4 GREEN `src/domain/ports/candle_store_port.py` — ABC, 3 abstractmethods, no infra imports
- [x] 1.5 RED `tests/unit/test_candle_history_port.py` — 3 tests, all RED confirmed
- [x] 1.6 GREEN `src/domain/ports/candle_history_port.py` — ABC, `fetch_history(epic,resolution,count,since)`
- [x] (bonus) `tests/unit/test_ports_are_abstract.py` extended with 4 new candle port assertions
- [x] 1.7 RED `tests/integration/test_candle_migration.py` — 4 tests, skip (no DB) before migration file exists
- [x] 1.8 GREEN `src/infrastructure/postgres/migrations/002_create_candles.sql` — DDL per design
- [x] (bonus) `tests/unit/test_migration_runner.py` — new test verifies 002 content is applied
- [x] 1.9–1.14 RED `tests/integration/test_postgres_candle_store.py` — 6 integration tests (skip no DB) + `tests/unit/test_postgres_candle_store.py` — 5 unit tests, all RED confirmed
- [x] 1.15 GREEN `src/infrastructure/postgres/candle_store.py` — `PostgresCandleStore` implementing `CandleStorePort`
- [x] 1.16 REFACTOR `_row_to_candle()` helper is the single source for Decimal→float mid derivation
- [x] 1.17 RED `tests/unit/test_config.py` — 8 new tests RED confirmed
- [x] 1.18 GREEN `src/config.py` — added `ws_ping_interval_seconds`, `required_candles`, `backfill_max_candles`; removed `freshness_max_retries`/`freshness_retry_seconds`
- [x] 1.19 `pyproject.toml` — added `websocket-client>=1.9,<2`

---

## AC → Test Mapping (Slice 1)

| Acceptance Criterion | Test(s) |
|---------------------|---------|
| AC-CSP-1 (idempotent upsert, second-call wins) | `tests/integration/test_postgres_candle_store.py::test_upsert_twice_same_key_second_call_wins`, `tests/unit/test_postgres_candle_store.py::test_upsert_uses_on_conflict_do_update` |
| AC-CSP-2 (oldest-first mid-derived) | `tests/integration/test_postgres_candle_store.py::test_recent_candles_returns_three_oldest_first_mid_derived`, `tests/unit/test_postgres_candle_store.py::test_recent_candles_mid_derivation_from_decimal_rows` |
| AC-CSP-3 (count cap) | `tests/integration/test_postgres_candle_store.py::test_recent_candles_respects_count_cap` |
| AC-CSP-4 (empty → []) | `tests/integration/test_postgres_candle_store.py::test_recent_candles_empty_table_returns_empty` |
| AC-CSP-5 (last_candle_start None) | `tests/integration/test_postgres_candle_store.py::test_last_candle_start_empty_table_returns_none`, `tests/unit/test_postgres_candle_store.py::test_last_candle_start_returns_none_when_no_rows` |
| AC-CSP-6 (last_candle_start newest) | `tests/integration/test_postgres_candle_store.py::test_last_candle_start_returns_newest` |
| AC-CSP-7 (mid formula) | `tests/unit/test_postgres_candle_store.py::test_recent_candles_mid_derivation_from_decimal_rows`, `tests/unit/test_postgres_candle_store.py::test_decimal_to_float_cast_probe` |
| AC-CSP-8 (migration discovery) | `tests/integration/test_candle_migration.py` (4 tests), `tests/unit/test_migration_runner.py::test_002_create_candles_sql_is_discovered_and_applied` |

---

## Apply-Time Probe Results

**Probe (c) — NUMERIC → Decimal → float cast**
Confirmed in `tests/unit/test_postgres_candle_store.py::test_decimal_to_float_cast_probe`.
The stub cursor returns `Decimal` values for all 8 OHLC columns. After `_row_to_candle()`:
- `type(candle.open) is float` → **True**
- `type(candle.high) is float` → **True**
- All 4 fields cast via `float((bid + ask) / 2)` in the single `_row_to_candle` helper.
The cast is contained in ONE function (DRY compliant).

---

## Files Created/Modified

### New files
- `src/domain/entities/candle_row.py`
- `src/domain/ports/candle_store_port.py`
- `src/domain/ports/candle_history_port.py`
- `src/infrastructure/postgres/migrations/002_create_candles.sql`
- `src/infrastructure/postgres/candle_store.py`
- `tests/unit/test_candle_row.py`
- `tests/unit/test_candle_store_port.py`
- `tests/unit/test_candle_history_port.py`
- `tests/unit/test_postgres_candle_store.py`
- `tests/integration/test_candle_migration.py`
- `tests/integration/test_postgres_candle_store.py`
- `openspec/changes/ws-candle-ingestion/apply-progress.md`

### Modified files
- `src/config.py` — added ws_ping/required_candles/backfill_max_candles; removed freshness fields
- `pyproject.toml` — added websocket-client>=1.9,<2
- `tests/unit/test_config.py` — removed old freshness tests, added 8 new config tests
- `tests/unit/test_ports_are_abstract.py` — added 4 candle port assertions
- `tests/unit/test_migration_runner.py` — added 002 discovery test

---

## Deviations from Design

None. All SQL, signatures, and structures implemented verbatim per design.

The `required_candles` field is derived as `warmup_bars` at construction time (single source — no divergence), per design decision 7.
