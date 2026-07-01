# Verify Report: ws-candle-ingestion

**Change:** ws-candle-ingestion  
**Phase:** verify  
**Date:** 2026-07-01  
**Suite result:** 187 passed, 18 skipped (0 failures)  
**Verdict: PASS WITH WARNINGS**

---

## Summary

All 3 slices implemented and all 187 unit tests pass. The 18 skipped tests are integration tests gated behind `DATABASE_URL` — they skip cleanly and intentionally. No critical implementation failures found. Two warnings identified: (1) `recent_candles` SQL query filters only on `epic`, not `resolution` — safe for a single-timeframe deployment but brittle for multi-timeframe futures; (2) probe (b) ohlc.event envelope field name validation is test-confirmed against a fixture but not against a live WS capture. One minor suggestion: redundant double-check in `_pair_buffer.py` line 63–64.

---

## Test Suite Evidence

```
187 passed, 18 skipped in 1.50s
```

- Unit tests: run inline (no DB, no network)
- Integration tests: 18 skipped cleanly (require `DATABASE_URL`)
- Command: `.venv/bin/python3 -m pytest`

---

## Task Completion

All tasks 1.1–1.19, 2.1–2.18, and 3.1–3.10 are marked complete in `apply-progress.md`. Task 3.11 (optional DB smoke test) is acknowledged optional and not blocking.

| Slice | Tasks | Status |
|-------|-------|--------|
| Slice 1 (1.1–1.19) | Candle store foundation | COMPLETE |
| Slice 2 (2.1–2.18) | Session + WS ingester + entry point | COMPLETE |
| Slice 3 (3.1–3.10) | Trading cycle cutover | COMPLETE |
| 3.11 (optional DB smoke) | Integration smoke with real PG | OPTIONAL — not run |

---

## AC Coverage Matrix

### candle-store capability

| AC | Description | Test(s) | Status |
|----|-------------|---------|--------|
| AC-CSP-1 | Idempotent upsert — second call wins | `tests/integration/test_postgres_candle_store.py::test_upsert_twice_same_key_second_call_wins` (skipped), `tests/unit/test_postgres_candle_store.py::test_upsert_uses_on_conflict_do_update` | SATISFIED (unit) / SKIPPED (integration) |
| AC-CSP-2 | recent_candles oldest-first mid-derived | `tests/integration/test_postgres_candle_store.py::test_recent_candles_returns_three_oldest_first_mid_derived` (skipped), `tests/unit/test_postgres_candle_store.py::test_recent_candles_mid_derivation_from_decimal_rows`, `test_recent_candles_ordering_oldest_first` | SATISFIED (unit) / SKIPPED (integration) |
| AC-CSP-3 | Count cap | `tests/integration/test_postgres_candle_store.py::test_recent_candles_respects_count_cap` (skipped) | SKIPPED (integration only) |
| AC-CSP-4 | Empty table returns [] | `tests/integration/test_postgres_candle_store.py::test_recent_candles_empty_table_returns_empty` (skipped) | SKIPPED (integration only) |
| AC-CSP-5 | last_candle_start None on empty | `tests/integration/test_postgres_candle_store.py::test_last_candle_start_empty_table_returns_none` (skipped), `tests/unit/test_postgres_candle_store.py::test_last_candle_start_returns_none_when_no_rows` | SATISFIED (unit) / SKIPPED (integration) |
| AC-CSP-6 | last_candle_start returns newest | `tests/integration/test_postgres_candle_store.py::test_last_candle_start_returns_newest` (skipped) | SKIPPED (integration only) |
| AC-CSP-7 | Mid formula `(bid+ask)/2` | `tests/unit/test_postgres_candle_store.py::test_recent_candles_mid_derivation_from_decimal_rows`, `test_decimal_to_float_cast_probe` | SATISFIED |
| AC-CSP-8 | Migration 002 discovered and applied | `tests/integration/test_candle_migration.py` — 4 tests (skipped), `tests/unit/test_migration_runner.py::test_002_create_candles_sql_is_discovered_and_applied` | SATISFIED (unit) / SKIPPED (integration) |

### ws-candle-ingestion capability

| AC | Description | Test(s) | Status |
|----|-------------|---------|--------|
| AC-WCI-1 | Bid alone does not write a row | `tests/unit/test_pair_buffer.py::test_bid_only_does_not_call_upsert`, `tests/unit/test_ws_ingester.py::test_bid_only_event_does_not_upsert` | SATISFIED |
| AC-WCI-2 | Bid+ask → one row | `tests/unit/test_pair_buffer.py::test_bid_then_ask_calls_upsert_once_with_correct_row`, `tests/unit/test_ws_ingester.py::test_bid_then_ask_upserts_one_row` | SATISFIED |
| AC-WCI-3 | Ask+bid → one row | `tests/unit/test_pair_buffer.py::test_ask_then_bid_calls_upsert_once`, `tests/unit/test_ws_ingester.py::test_ask_then_bid_upserts_one_row` | SATISFIED |
| AC-WCI-4 | Epics buffered independently | `tests/unit/test_pair_buffer.py::test_two_epics_buffered_independently_only_matched_writes` | SATISFIED |
| AC-WCI-5 | Cold backfill (empty store) | `tests/unit/test_ws_ingester.py::test_cold_start_fetches_backfill_then_upserts` | SATISFIED |
| AC-WCI-6 | Gap-fill only (non-empty store) | `tests/unit/test_ws_ingester.py::test_warm_start_fetches_gap_only` | SATISFIED |
| AC-WCI-7 | Idempotent overlap | Covered by AC-CSP-1 (upsert idempotency) + ingester calls upsert confirmed by AC-WCI-2; full integration path only validated with DB | PARTIAL — integration not run |
| AC-WCI-8 | Epoch-ms UTC conversion | `tests/unit/test_pair_buffer.py::test_epoch_ms_conversion`, `tests/unit/test_ws_ingester.py::test_epoch_ms_timestamp_conversion` | SATISFIED |

### trading-cycle capability

| AC | Description | Test(s) | Status |
|----|-------------|---------|--------|
| AC-TC-1 | Short store → None | `tests/unit/test_trading_cycle.py::test_short_store_returns_none` | SATISFIED |
| AC-TC-2 | Stale store → None, no retry | `tests/unit/test_trading_cycle.py::test_stale_store_returns_none_no_retry` | SATISFIED |
| AC-TC-3 | Fresh+full → strategy → broker | `tests/unit/test_trading_cycle.py::test_fresh_full_store_calls_strategy_and_broker` | SATISFIED |
| AC-TC-4 | No retry params in constructor | `tests/unit/test_trading_cycle.py::test_no_retry_params_in_constructor`, `tests/unit/test_main_wiring.py::test_use_case_has_no_freshness_params` | SATISFIED |
| AC-TC-5 | Open position skips cycle | `tests/unit/test_trading_cycle.py::test_open_position_skips_candle_store` | SATISFIED |

### capital-session capability

| AC | Description | Test(s) | Status |
|----|-------------|---------|--------|
| AC-CS-1 | streaming_host after authenticate | `tests/unit/test_capital_session.py::test_streaming_host_available_after_authenticate` | SATISFIED |
| AC-CS-2 | streaming_host raises before authenticate | `tests/unit/test_capital_session.py::test_streaming_host_raises_before_authenticate` | SATISFIED |
| AC-CS-3 | authenticate returns SessionTokens | `tests/unit/test_capital_session.py::test_authenticate_still_returns_session_tokens_with_streaming_host` | SATISFIED |
| AC-CS-4 | tokens() unaffected | `tests/unit/test_capital_session.py::test_tokens_still_works_after_streaming_host_captured` | SATISFIED |

---

## Apply-time Probe Verification

| Probe | Status | Evidence |
|-------|--------|----------|
| (a) /prices gap-fill param shape | SATISFIED — `from`/`to` path implemented; cold uses `max=count+1` then drops last | `candle_history.py:_cold_backfill` + `_gap_fill`; test `test_gap_fill_calls_from_to_params` asserts `from=` present and `max=` absent |
| (b) ohlc.event JSON envelope | PARTIAL — field names (`epic`, `resolution`, `t`, `o/h/l/c`, `priceType`) confirmed via test fixtures; no real WS capture file committed | `test_ws_ingester.py` + `_pair_buffer.py` use identical field names; no `ws_event_fixture.json` committed to repo |
| (c) Decimal→float cast | SATISFIED — `_row_to_candle` explicitly `float((bid+ask)/2)` per field; `test_decimal_to_float_cast_probe` asserts `type(candle.open) is float` | `candle_store.py:_row_to_candle` lines 46–54 |

---

## Adversarial / Correctness Checks

### Freshness references in source

Grep over `src/**/*.py` for `freshness`: ZERO matches. Confirmed the `.pyc` false-positive incident from Slice 3 apply — source is clean.

### recent_candles isolation

`recent_candles` appears ONLY in:
- `src/domain/ports/candle_store_port.py` (abstract method definition)
- `src/infrastructure/postgres/candle_store.py` (implementation)
- `src/application/trading_cycle.py` (the one call site)

Not present in `src/domain/ports/broker_port.py` or `src/infrastructure/capital/broker.py`. CSP-08 SATISFIED.

### build_use_cases(candle_store=None) seam risk

The `__main__.py:build_use_cases` has a test seam `candle_store=None`. Behavior:

- If `journal is None` (production path): creates `conn = connect(...)`, then if `candle_store is None` creates `PostgresCandleStore(conn)` from the same conn. SAFE.
- If `journal is not None` (test path) AND `candle_store is None`: creates a **new** `connect(config.database_url)` just for the candle store. This requires `DATABASE_URL` to be set even in unit tests that provide a `journal`. However, `test_main_wiring.py` always passes an explicit `FakeCandleStore()`, so this path is not exercised in the unit suite. In CI without `DATABASE_URL`, this code path would raise `SystemExit` or a connection error if reached.

**Severity: WARNING** — the `candle_store=None` + `journal not None` path opens a new DB connection without recycling the journal conn. Not a correctness bug under current tests, but a latent resource-management gap in integration scenarios.

### SL/TP order path unchanged

`broker.open_position` is called identically at `trading_cycle.py:65` with `(self._symbol, signal, self._size)`. `CapitalBrokerAdapter.open_position` is unchanged. SATISFIED.

### FadeStrategy math untouched

`src/domain/adapters/fade_strategy.py` and `src/domain/strategy/fade.py` were not modified. FadeStrategy consumes `Candle.open/high/low/close` mid-price fields, which are now derived from `(bid+ask)/2` in `PostgresCandleStore._row_to_candle`. The interface is transparent to FadeStrategy. SATISFIED.

### Timezone correctness

- `candle_start TIMESTAMPTZ` in migration 002 — correct.
- `datetime.fromtimestamp(t/1000, tz=timezone.utc)` in `_pair_buffer.py:83` and `candle_history.py:115` — correct UTC conversion.
- `_to_iso()` in `candle_history.py` strips timezone suffix (`.strftime("%Y-%m-%dT%H:%M:%S")`) — correct, matches Capital API expectation.
- `CandleRow.__post_init__` enforces `tzinfo == timezone.utc` — correct.

### recent_candles missing resolution filter (WARNING)

`_SELECT_RECENT` in `candle_store.py` filters `WHERE epic = %s` without `AND resolution = %s`. The `CandleStorePort.recent_candles` signature (`symbol, count`) also has no `resolution` parameter — this is by spec design. With a single timeframe deployment (current architecture), the `candles` table will only contain rows for one resolution per epic, so this is safe today. If a future feature stores multiple resolutions per epic, `recent_candles` would silently mix timeframes.

---

## Issues

### WARNING — W1: recent_candles SQL has no resolution filter

**File:** `src/infrastructure/postgres/candle_store.py:27-35`  
**What:** `_SELECT_RECENT` WHERE clause uses only `epic`, not `(epic, resolution)`.  
**Risk:** Safe for single-resolution deployment. Would silently return mixed-timeframe data if the `candles` table ever contains multiple resolutions for the same epic.  
**Action required before multi-timeframe:** Add `AND resolution = %s` to `_SELECT_RECENT` and update the port signature.

### WARNING — W2: ohlc.event envelope not validated against real WS capture

**File:** `src/infrastructure/capital/_pair_buffer.py` + `ws_ingester.py`  
**What:** Field names (`epic`, `resolution`, `t`, `o/h/l/c`, `priceType`) are confirmed by the apply-time note in `apply-progress.md` and encoded in test fixtures, but no `ws_event_fixture.json` with a real captured message is committed to the repo.  
**Risk:** If the live Capital WS envelope differs (e.g., nesting, different field names), the ingester will silently drop all events (the `msg.get("destination") == "ohlc.event"` guard will not match, or `payload["epic"]` will raise `KeyError`).  
**Action required before production:** Run a short manual session, capture one real message, commit it as `tests/fixtures/ws_ohlc_event.json`, and add an assertion that `PairBuffer.on_event` processes it correctly.

### WARNING — W3: build_use_cases candle_store=None + journal provided opens a new DB conn

**File:** `src/__main__.py:82-83`  
**What:** `elif candle_store is None: candle_store = PostgresCandleStore(connect(config.database_url))` creates a second connection not shared with the journal. In the unit test suite this is never reached (tests always pass an explicit fake). In an integration scenario providing only a journal, two connections would be opened.  
**Risk:** Not a correctness bug under current test coverage. Potential resource-management issue in integration tests or if `DATABASE_URL` is absent when this branch is reached.  
**Action:** Low priority. Could be resolved by passing `conn` through the seam if both journal and store need to share it.

### SUGGESTION — S1: redundant double-check in _pair_buffer.py

**File:** `src/infrastructure/capital/_pair_buffer.py:63-65`  
```python
if buf_key not in self._partials:
    if buf_key not in self._partials:   # identical check — dead code
        self._partials[buf_key] = _Partial()
```
The nested `if` is redundant. Functionally harmless but is a code smell indicating a copy-paste artifact. Remove the inner `if`.

---

## ACs Covered Only by Skipped (No-DB) Integration Tests

The following ACs are validated only by integration tests that skip without `DATABASE_URL`. They have partial unit-test coverage (SQL structure verified via fake cursors) but lack real-DB end-to-end validation:

| AC | Risk |
|----|------|
| AC-CSP-1 (idempotent upsert — second-call wins) | Unit test verifies `ON CONFLICT DO UPDATE` SQL is emitted; real PG behavior unconfirmed |
| AC-CSP-2 (oldest-first mid-derived, 5-row scenario) | Unit test verifies ordering and mid math; real PG ordering unconfirmed |
| AC-CSP-3 (count cap with 10 rows) | Integration only |
| AC-CSP-4 (empty table returns []) | Integration only |
| AC-CSP-6 (last_candle_start returns newest) | Integration only |
| AC-CSP-8 (002 migration applied to real DB) | Unit test verifies file content; real DB schema unconfirmed |
| AC-WCI-7 (idempotent overlap end-to-end) | Combination of ingester + store; requires real DB |

---

## Production Readiness

### Must validate against a real DB before running

1. Run `pytest tests/integration/` with `DATABASE_URL` set — covers AC-CSP-1 through AC-CSP-8 and AC-WCI-7.
2. Confirm `ON CONFLICT DO UPDATE SET` succeeds with psycopg v3 + real Postgres (NUMERIC column types, TIMESTAMPTZ behaviour, ROLLBACK within migration).
3. Confirm `last_candle_start` returns a UTC-aware `datetime` (psycopg may return naive datetimes depending on connection timezone config).

### Must validate against a real Capital WS before running in production

1. Capture a live `ohlc.event` message from `wss://api-streaming-capital.backend-capital.com/connect`.
2. Verify the JSON envelope matches the fixture shape: `{"destination": "ohlc.event", "payload": {"epic": ..., "resolution": ..., "t": epoch_ms, "o": ..., "h": ..., "l": ..., "c": ..., "priceType": "bid"|"ask"}}`.
3. If the Capital API supports `from`/`to` on `/prices`, confirm the gap-fill path works with real credentials. The apply-time note says `from`/`to` are implemented but not confirmed with a live call.
4. Confirm `streamingHost` is present in the real POST `/session` response body (not just in test fixtures).
5. Run the ingestion process for one full WS connection cycle, observe logs, and confirm the gap-fill + live-event path writes rows to the `candles` table without errors.
