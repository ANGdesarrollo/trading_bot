# Apply Progress: ws-candle-ingestion — Slice 1 + Slice 2 + Slice 3

**Status:** Slice 1 COMPLETE (1.1–1.19), Slice 2 COMPLETE (2.1–2.18), Slice 3 COMPLETE (3.1–3.10)
**Suite result after Slice 3:** 187 passed, 18 skipped (integration tests skip w/o DB)

---

## Tasks Completed

### Slice 1 (1.1–1.19) — Candle Store Foundation

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

### Slice 2 (2.1–2.18) — Session + WS Ingester + Entry Point

- [x] 2.1 RED `tests/unit/test_capital_session.py` — 4 new tests (streaming_host before/after auth, tokens still works, authenticate returns SessionTokens)
- [x] 2.2 GREEN `src/infrastructure/capital/session.py` — `_streaming_host` field captured from `response.json()["streamingHost"]`; `@property streaming_host` raises RuntimeError when None
- [x] 2.3 RED `tests/unit/test_capital_candle_history.py` — cold backfill path (max param, drop last)
- [x] 2.4 RED (same file) — gap-fill path (from/to params, no drop)
- [x] 2.5 GREEN `src/infrastructure/capital/candle_history.py` — `CapitalCandleHistory` implementing `CandleHistoryPort`; cold=max+1 then `[:-1]`; gap=from/to; bid+ask merged by `t`
- [x] 2.6 RED `tests/unit/test_pair_buffer.py` — bid-only no upsert; bid+ask one upsert; ask+bid one upsert; epics independent
- [x] 2.7 RED (same file) — epoch-ms conversion t=1_700_000_000_000 → correct datetime
- [x] 2.8 RED (same file) — staleness eviction at 4*period
- [x] 2.9 GREEN `src/infrastructure/capital/_pair_buffer.py` — `PairBuffer` with `_Partial dataclass(slots=True)`, `on_event()`, staleness eviction
- [x] 2.10 REFACTOR `_Partial` is already a `dataclass(slots=True)`, `PairBuffer` SRP
- [x] 2.11 RED `tests/unit/test_ws_ingester.py` — cold-start backfill: `since=None`, upsert all rows
- [x] 2.12 RED (same file) — warm-start gap-fill: `since=T_last+period`
- [x] 2.13 RED (same file) — reconnect: ConnectionError triggers sleep + gap-fill re-run
- [x] 2.14 RED (same file) — ping after ping_interval via AdvancingTransport fake clock trick
- [x] 2.15 GREEN `src/infrastructure/capital/ws_ingester.py` — `CapitalWsIngester`; `run_once()` lifecycle; `_subscribe()`, `_backfill_or_gap_fill()`, `_process_events()`; exp-backoff+jitter reconnect; ping timer
- [x] 2.16 REFACTOR `_backfill_or_gap_fill()` is the single method called at startup AND after reconnect (DRY)
- [x] 2.17 RED `tests/unit/test_ingestion.py` — run_once loop, continues on exception, __main__ guard AST check
- [x] 2.18 GREEN `src/ingestion.py` — `run_ingestion_forever()`, `__main__` block with full wiring
- [x] (bonus) `src/infrastructure/capital/ws_transport.py` — `WebsocketClientTransport` wrapping websocket-client

---

## AC → Test Mapping (Slice 2)

| Acceptance Criterion | Test(s) |
|---------------------|---------|
| AC-CS-1 (streaming_host after auth) | `tests/unit/test_capital_session.py::test_streaming_host_available_after_authenticate` |
| AC-CS-2 (streaming_host before auth raises) | `tests/unit/test_capital_session.py::test_streaming_host_raises_before_authenticate` |
| AC-CS-3 (authenticate returns SessionTokens) | `tests/unit/test_capital_session.py::test_authenticate_still_returns_session_tokens_with_streaming_host` |
| AC-CS-4 (tokens() unaffected) | `tests/unit/test_capital_session.py::test_tokens_still_works_after_streaming_host_captured` |
| AC-WCI-1 (bid alone no write) | `tests/unit/test_pair_buffer.py::test_bid_only_does_not_call_upsert`, `tests/unit/test_ws_ingester.py::test_bid_only_event_does_not_upsert` |
| AC-WCI-2 (bid+ask → one row) | `tests/unit/test_pair_buffer.py::test_bid_then_ask_calls_upsert_once_with_correct_row`, `tests/unit/test_ws_ingester.py::test_bid_then_ask_upserts_one_row` |
| AC-WCI-3 (ask+bid → one row) | `tests/unit/test_pair_buffer.py::test_ask_then_bid_calls_upsert_once`, `tests/unit/test_ws_ingester.py::test_ask_then_bid_upserts_one_row` |
| AC-WCI-4 (epics independent) | `tests/unit/test_pair_buffer.py::test_two_epics_buffered_independently_only_matched_writes` |
| AC-WCI-5 (cold backfill) | `tests/unit/test_ws_ingester.py::test_cold_start_fetches_backfill_then_upserts` |
| AC-WCI-6 (gap-fill only) | `tests/unit/test_ws_ingester.py::test_warm_start_fetches_gap_only` |
| AC-WCI-7 (idempotent overlap) | Covered by upsert idempotency in PostgresCandleStore (Slice 1); `test_bid_then_ask_upserts_one_row` confirms ingester calls upsert |
| AC-WCI-8 (epoch-ms conversion) | `tests/unit/test_pair_buffer.py::test_epoch_ms_conversion`, `tests/unit/test_ws_ingester.py::test_epoch_ms_timestamp_conversion` |

---

## AC → Test Mapping (Slice 1)

| Acceptance Criterion | Test(s) |
|---------------------|---------|
| AC-CSP-1 (idempotent upsert) | `tests/integration/test_postgres_candle_store.py::test_upsert_twice_same_key_second_call_wins`, `tests/unit/test_postgres_candle_store.py::test_upsert_uses_on_conflict_do_update` |
| AC-CSP-2 (oldest-first mid-derived) | `tests/integration/test_postgres_candle_store.py::test_recent_candles_returns_three_oldest_first_mid_derived`, `tests/unit/test_postgres_candle_store.py::test_recent_candles_mid_derivation_from_decimal_rows` |
| AC-CSP-3 (count cap) | `tests/integration/test_postgres_candle_store.py::test_recent_candles_respects_count_cap` |
| AC-CSP-4 (empty → []) | `tests/integration/test_postgres_candle_store.py::test_recent_candles_empty_table_returns_empty` |
| AC-CSP-5 (last_candle_start None) | `tests/integration/test_postgres_candle_store.py::test_last_candle_start_empty_table_returns_none`, `tests/unit/test_postgres_candle_store.py::test_last_candle_start_returns_none_when_no_rows` |
| AC-CSP-6 (last_candle_start newest) | `tests/integration/test_postgres_candle_store.py::test_last_candle_start_returns_newest` |
| AC-CSP-7 (mid formula) | `tests/unit/test_postgres_candle_store.py::test_recent_candles_mid_derivation_from_decimal_rows`, `tests/unit/test_postgres_candle_store.py::test_decimal_to_float_cast_probe` |
| AC-CSP-8 (migration discovery) | `tests/integration/test_candle_migration.py` (4 tests), `tests/unit/test_migration_runner.py::test_002_create_candles_sql_is_discovered_and_applied` |

---

## Files Created/Modified (Slice 2)

### New files
- `src/infrastructure/capital/candle_history.py` — CapitalCandleHistory REST adapter
- `src/infrastructure/capital/_pair_buffer.py` — PairBuffer bid+ask pairing logic
- `src/infrastructure/capital/ws_ingester.py` — CapitalWsIngester lifecycle + reconnect
- `src/infrastructure/capital/ws_transport.py` — WebsocketClientTransport (real impl)
- `src/ingestion.py` — entry point process (mirrors reconciler.py)
- `tests/unit/test_capital_candle_history.py`
- `tests/unit/test_pair_buffer.py`
- `tests/unit/test_ws_ingester.py`
- `tests/unit/test_ingestion.py`

### Modified files (Slice 2)
- `src/infrastructure/capital/session.py` — added `_streaming_host` + `streaming_host` property
- `tests/unit/test_capital_session.py` — added 4 streaming_host tests
- `openspec/changes/ws-candle-ingestion/tasks.md` — marked 2.1–2.18 complete

---

## Deviations from Design

1. **WS transport seam**: Design said "WebSocket transport seam (small interface: connect/send/recv/close)" — implemented as `connect/send/recv/ping/close`. Added `ping` since the ingester needs to call it (implied by WCI-07). Additive, not breaking.

2. **`CapitalWsIngester` takes explicit params instead of `Config` object**: Design listed `Config` as a dependency. Decided to take decomposed params (`epics`, `resolution`, `period_seconds`, `ws_ping_interval_seconds`, `required_candles`) instead, which keeps the class testable without constructing a full Config. The `__main__` block in ingestion.py does the wiring from Config.

3. **`run_once()` instead of separate `start()` + `ingest_forever()`**: Design implied `run_ingestion_forever` at ingestion.py level. `CapitalWsIngester.run_once()` handles one connection lifecycle (including reconnects up to `max_reconnect_attempts`). `run_ingestion_forever` in ingestion.py wraps it in an outer loop. This matches the reconciler.py pattern more closely and keeps `CapitalWsIngester` independently testable.

4. **Cold backfill request sends `count+1`**: The design says `?max=required_candles+1` then drops `[:-1]`. Implemented exactly as specified (per probe (a) confirmation). The test fixture was corrected to send count+1 items to model the real API's inclusion of the in-formation bar.

5. **Ping test uses `AdvancingTransport`**: The clock must advance during `recv()` calls to trigger the ping check correctly (since the check runs at the top of each event loop iteration, before `recv`).

---

---

## Slice 3 (3.1–3.10) — Trading Cycle Cutover

### TDD Cycle Evidence

| Task | RED | GREEN | REFACTOR |
|------|-----|-------|----------|
| 3.1 | `test_broker_port_has_no_recent_candles` FAILED (BrokerPort had recent_candles) | Removed from BrokerPort → PASSED | N/A |
| 3.5 | 9 tests in test_trading_cycle.py FAILED (candle_store kwarg unknown) | Rewrote trading_cycle.py → 9 PASSED | `_expected_boundary()` extracted |
| 3.8 | `test_use_case_receives_candle_store_not_broker_candles` FAILED (freshness_ args passed) | Updated __main__.py → PASSED | N/A |

### AC → Test Mapping (Slice 3)

| Acceptance Criterion | Test(s) |
|---------------------|---------|
| AC-TC-1 (short store → None) | `tests/unit/test_trading_cycle.py::test_short_store_returns_none` |
| AC-TC-2 (stale → None no retry) | `tests/unit/test_trading_cycle.py::test_stale_store_returns_none_no_retry` |
| AC-TC-3 (fresh+full → broker) | `tests/unit/test_trading_cycle.py::test_fresh_full_store_calls_strategy_and_broker` |
| AC-TC-4 (no retry params) | `tests/unit/test_trading_cycle.py::test_no_retry_params_in_constructor`, `tests/unit/test_main_wiring.py::test_use_case_has_no_freshness_params` |
| AC-TC-5 (open position skip) | `tests/unit/test_trading_cycle.py::test_open_position_skips_candle_store` |
| CSP-08 (BrokerPort no recent_candles) | `tests/unit/test_ports_are_abstract.py::test_broker_port_has_no_recent_candles` |

### Files Created/Modified (Slice 3)

#### New files
- `tests/fakes/fake_candle_store.py` — FakeCandleStore implementing CandleStorePort
- `tests/unit/test_main_wiring.py` — CandleStorePort injection + no freshness params

#### Modified files
- `src/domain/ports/broker_port.py` — removed `recent_candles` abstract method
- `src/infrastructure/capital/broker.py` — removed `recent_candles`, `_parse_candle`, unused imports
- `tests/fakes/fake_broker.py` — removed `recent_candles`, `candles` param, `Sequence`/`Candle` imports
- `tests/unit/test_capital_broker.py` — removed 4 recent_candles tests (6.1 scenarios)
- `tests/unit/test_trading_cycle.py` — complete rewrite: freshness tests deleted, AC-TC-1..5 added
- `tests/unit/test_ports_are_abstract.py` — added BrokerPort assertions (2 new tests)
- `src/application/trading_cycle.py` — replaced broker candle source with CandleStorePort; removed freshness retry loop; added `_expected_boundary()` helper
- `src/__main__.py` — added PostgresCandleStore import + construction; `candle_store` test seam param; removed freshness args
- `tests/unit/test_main_loop.py` — updated build_use_cases calls to pass `candle_store=FakeCandleStore()`; removed dead freshness config attrs

### Deviations from Design

1. **`build_use_cases` gained `candle_store=None` test seam**: The design said to wire `PostgresCandleStore(conn)` inline. Added an optional `candle_store` param to avoid requiring a real DB in unit tests (mirrors the existing `journal=None` seam). Production path (journal=None) creates both from the same conn. Non-breaking addition.

2. **`_expected_boundary()` extracted as private method**: Boundary calculation moved out of `execute()` for SRP clarity. Not a deviation — design showed it inline but extraction is pure refactor.

---

## Notes on Probe (b) Implementation

The `ohlc.event` envelope shape (confirmed in prompt): `{"destination":"ohlc.event","payload":{"epic":...,"resolution":...,"t":epoch_ms,"o":...,"h":...,"l":...,"c":...,"priceType":"bid"|"ask"}}`. The ingester checks `msg.get("destination") == "ohlc.event"` and routes to `PairBuffer.on_event()`. The subscribe ack (`OHLCMarketData.subscribe`) is silently ignored (not an ohlc.event).
