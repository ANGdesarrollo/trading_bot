# Tasks: WebSocket Candle Ingestion + Postgres Candle Store

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~900–1 100 (new files + test files + modifications) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 (Slice 1) → PR 2 (Slice 2) → PR 3 (Slice 3) |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Candle store foundation (entity, ports, PG adapter, migration, config) | PR 1 → main | ~320 lines; green suite; nothing wired to trading cycle yet |
| 2 | Session streaming_host + WS ingester + ingestion entry point | PR 2 → main | ~480 lines; fakes-only unit tests; depends on PR 1 |
| 3 | Trading cycle cutover (remove broker candles, wire store) | PR 3 → main | ~180 lines; deletes freshness tests; depends on PR 2 |

---

## Apply-time probes (risks to validate during implementation)

- **(a) /prices gap-fill param shape** — Capital API may only support `max` (not `from`/`to`). Probe in `CapitalCandleHistory`; adapter tolerates overlap via idempotent upsert if forced to over-fetch.
- **(b) ohlc.event JSON envelope** — field names (`epic`, `resolution`, `t`, `o`/`h`/`l`/`c`, `priceType`) must be validated against a real WS capture before merge. Add a fixture file with a captured event once confirmed.
- **(c) NUMERIC → Decimal → float cast** — psycopg v3 returns `Decimal` for `NUMERIC` columns. `recent_candles` must cast each field to `float` explicitly before building `Candle`; absence of the cast causes type errors downstream.

---

## Slice 1 — Candle Store Foundation (PR 1 → main)

### Phase 1: Domain entities and ports

- [ ] 1.1 **RED** `tests/unit/test_candle_row.py` — assert `CandleRow` is frozen (mutation raises), has all 11 fields, `candle_start` is UTC-aware. (CSP-02)
- [ ] 1.2 **GREEN** Create `src/domain/entities/candle_row.py` — frozen dataclass with slots, 11 fields. Make 1.1 pass.
- [ ] 1.3 **RED** `tests/unit/test_candle_store_port.py` — assert `CandleStorePort` is abstract: instantiating without implementing all three methods raises `TypeError`. (CSP-01, CSP-03)
- [ ] 1.4 **GREEN** Create `src/domain/ports/candle_store_port.py` — ABC, three `@abstractmethod`s, zero infra imports. Make 1.3 pass.
- [ ] 1.5 **RED** `tests/unit/test_candle_history_port.py` — assert `CandleHistoryPort` is abstract; `fetch_history` signature matches design. (ISP split per design decision 4)
- [ ] 1.6 **GREEN** Create `src/domain/ports/candle_history_port.py` — ABC, one `@abstractmethod fetch_history`. Make 1.5 pass.

### Phase 2: Migration

- [ ] 1.7 **RED** `tests/integration/test_candle_migration.py` — with `pg_conn` fixture (mirrors `test_postgres_journal.py`): assert `candles` table does not exist before migration; after `run_migrations`, assert table exists with correct columns and `schema_migrations` contains `002_create_candles`. (AC-CSP-8)
- [ ] 1.8 **GREEN** Create `src/infrastructure/postgres/migrations/002_create_candles.sql` — `CREATE TABLE IF NOT EXISTS candles`, 11 data columns all `NOT NULL`, `UNIQUE(epic,resolution,candle_start)`, `CREATE INDEX IF NOT EXISTS idx_candles_recent ON candles(epic, resolution, candle_start DESC)`. Make 1.7 pass.

### Phase 3: PostgresCandleStore adapter

- [ ] 1.9 **RED** `tests/integration/test_postgres_candle_store.py` — test `upsert_candle` twice same key, different OHLC second call; assert one row, second-call values win. (AC-CSP-1)
- [ ] 1.10 **RED** (same file) — insert 5 rows T1..T5; `recent_candles("EURUSD", 3)` returns `[T3,T4,T5]` oldest-first; each `candle.open == (open_bid+open_ask)/2`. (AC-CSP-2, AC-CSP-7)
- [ ] 1.11 **RED** (same file) — insert 10 rows; `recent_candles(symbol,3)` returns exactly 3. (AC-CSP-3)
- [ ] 1.12 **RED** (same file) — empty table; `recent_candles` returns `[]`, no exception. (AC-CSP-4)
- [ ] 1.13 **RED** (same file) — `last_candle_start` on empty table returns `None`. (AC-CSP-5)
- [ ] 1.14 **RED** (same file) — insert T1<T2<T3; `last_candle_start` returns T3 as UTC-aware datetime. (AC-CSP-6)
- [ ] 1.15 **GREEN** Create `src/infrastructure/postgres/candle_store.py` — `PostgresCandleStore(conn)` implements `CandleStorePort`; upsert SQL with `ON CONFLICT ... DO UPDATE SET`; `recent_candles` queries `ORDER BY candle_start DESC LIMIT n`, reverses, applies `float((bid+ask)/2)` cast per field (addresses probe-c); `last_candle_start` single-row query. Make 1.9–1.14 pass.
- [ ] 1.16 **REFACTOR** Ensure NUMERIC→float cast is done in a private `_row_to_candle` helper (single source of truth; DRY).

### Phase 4: Config additions

- [ ] 1.17 **RED** `tests/unit/test_config.py` (modify existing) — assert `Config` has `ws_ping_interval_seconds` defaulting to 540 and asserting < 600; `required_candles` and `backfill_max_candles` fields present; `freshness_max_retries` and `freshness_retry_seconds` absent. (WCI-10)
- [ ] 1.18 **GREEN** Modify `src/config.py` — add `ws_ping_interval_seconds` (env `WS_PING_INTERVAL_SECONDS`, default 540, assert < 600), `required_candles` (= `warmup_bars`), `backfill_max_candles` (default 500); remove `freshness_max_retries`/`freshness_retry_seconds`. Make 1.17 pass.

### Phase 5: pyproject.toml

- [ ] 1.19 Modify `pyproject.toml` — add `websocket-client>=1.9,<2` to project dependencies.

> **Slice 1 exit gate**: `cd operator && .venv/bin/python3 -m pytest` passes; no freshness config fields; `candles` table created by migration; `PostgresCandleStore` all AC-CSP-* green.

---

## Slice 2 — Session + WS Ingester + Ingestion Entry Point (PR 2 → main)

### Phase 6: CapitalSession streaming_host

- [ ] 2.1 **RED** `tests/unit/test_capital_session.py` (modify existing) — assert `streaming_host` raises `RuntimeError` before `authenticate()`; assert after `authenticate()` with fake HTTP body `{"streamingHost": "https://streaming.capital.com"}`, property returns that URL; assert `authenticate()` still returns `SessionTokens` with correct tokens. (AC-CS-1, AC-CS-2, AC-CS-3, AC-CS-4)
- [ ] 2.2 **GREEN** Modify `src/infrastructure/capital/session.py` — after extracting headers in `authenticate()`, parse `response.json()` and store `self._streaming_host = body.get("streamingHost")`; add `@property streaming_host` raising `RuntimeError("Not authenticated")` when `_streaming_host is None`. Make 2.1 pass.

### Phase 7: CandleHistoryPort adapter

- [ ] 2.3 **RED** `tests/unit/test_capital_candle_history.py` — with fake `requests.Session` returning a canned `/prices` response: assert `fetch_history(epic, resolution, count=3, since=None)` calls `/prices` with correct params and returns 3 `CandleRow` objects with correct epic/resolution/candle_start/bid/ask fields. Addresses probe-(a) by testing both param shapes (max-only path).
- [ ] 2.4 **RED** (same file) — `fetch_history(epic, resolution, count=5, since=T_last)` calls `/prices` with range params (probe-a: note in test that `from`/`to` path may need adjustment after real API capture).
- [ ] 2.5 **GREEN** Create `src/infrastructure/capital/candle_history.py` — `CapitalCandleHistory` implements `CandleHistoryPort`; uses `/prices` endpoint; handles both cold (`max=count`) and gap (`from`/`to`) call shapes; returns `Sequence[CandleRow]`. Make 2.3–2.4 pass.

### Phase 8: PairBuffer (unit)

- [ ] 2.6 **RED** `tests/unit/test_pair_buffer.py` — assert bid-only event: `upsert_candle` NOT called; bid+ask same key: called exactly once with correct `CandleRow`; ask-first then bid: same; two epics, only matched epic writes. (AC-WCI-1, AC-WCI-2, AC-WCI-3, AC-WCI-4)
- [ ] 2.7 **RED** (same file) — assert epoch-ms conversion: `t=1_700_000_000_000` → `candle_start == datetime(2023, 11, 14, 22, 13, 20, tz=utc)`. (AC-WCI-8)
- [ ] 2.8 **RED** (same file) — staleness eviction: partial with `t_ms < newest - 4*period_ms` is dropped on next event; no upsert for the evicted partial.
- [ ] 2.9 **GREEN** Create `src/infrastructure/capital/_pair_buffer.py` — `PairBuffer` class; internal `dict[(epic,resolution,t_ms), _Partial]`; `on_event(msg, upsert_fn)` method; eviction on each call; `candle_start = datetime.fromtimestamp(t/1000, tz=utc)`. Make 2.6–2.8 pass.
- [ ] 2.10 **REFACTOR** Extract `_Partial` as a `dataclass(slots=True)` if not already; keep `PairBuffer` at single responsibility.

### Phase 9: CapitalWsIngester (unit with fakes)

- [ ] 2.11 **RED** `tests/unit/test_ws_ingester.py` — cold-start: fake `last_candle_start` returns `None`; assert `fetch_history` called with `count=required_candles, since=None`; upsert called for each returned row; buffered events drained after backfill. (AC-WCI-5)
- [ ] 2.12 **RED** (same file) — warm-start: fake `last_candle_start` returns `T_last`; assert `fetch_history` called with `since=T_last+1_period`; no full-history request. (AC-WCI-6)
- [ ] 2.13 **RED** (same file) — reconnect: fake transport raises `ConnectionError` on second `recv()`; assert exp-backoff sleep schedule called (1s..60s jitter, fake clock); re-subscribe + gap-fill re-run before resuming. (WCI-08)
- [ ] 2.14 **RED** (same file) — ping: after `ws_ping_interval_seconds` elapses on fake clock, assert `ws.ping()` called (WCI-07).
- [ ] 2.15 **GREEN** Create `src/infrastructure/capital/ws_ingester.py` — `CapitalWsIngester`; deps: `CandleStorePort`, `CandleHistoryPort`, `CapitalSession`, `Config`; startup sequence (connect+subscribe → buffer → backfill/gap → drain → live); `PairBuffer` delegation; ping timer; reconnect with exp-backoff (base 1s, cap 60s, full jitter, unbounded). Make 2.11–2.14 pass.
- [ ] 2.16 **REFACTOR** Extract `_backfill_or_gap_fill(epic)` private method used both at startup and after reconnect (DRY — WCI-02 vs WCI-08 share the same logic).

### Phase 10: Ingestion entry point

- [ ] 2.17 **RED** `tests/unit/test_ingestion.py` — assert `run_ingestion_forever(ingester)` calls `ingester.start()` and loops; verify it is independently callable (structural test, not integration).
- [ ] 2.18 **GREEN** Create `src/ingestion.py` — mirrors `src/reconciler.py`; `run_ingestion_forever(ingester)` blocking loop; `if __name__ == "__main__"` guard (WCI-09). Make 2.17 pass.

> **Slice 2 exit gate**: `cd operator && .venv/bin/python3 -m pytest` passes; `CapitalWsIngester` tested via fakes; `CapitalSession.streaming_host` green; ingestion entry point runnable.

---

## Slice 3 — Trading Cycle Cutover (PR 3 → main)

### Phase 11: Remove BrokerPort.recent_candles

- [ ] 3.1 **RED** `tests/unit/test_broker_port.py` (create or modify) — assert `BrokerPort` has NO `recent_candles` method; assert only `open_position` and `has_open_position` remain as abstract methods. (CSP-08)
- [ ] 3.2 **GREEN** Modify `src/domain/ports/broker_port.py` — remove `recent_candles` abstract method.
- [ ] 3.3 **GREEN** Modify `src/infrastructure/capital/broker.py` — remove `recent_candles` and `_parse_candle`.
- [ ] 3.4 **GREEN** Modify `tests/fakes/fake_broker.py` — remove `recent_candles`, `recent_candles_calls`, and `candles` constructor param; keep only `has_open_position` + `open_position`. Make 3.1 pass.

### Phase 12: RunTradingCycleUseCase cutover

- [ ] 3.5 **RED** `tests/unit/test_trading_cycle.py` (modify) — delete freshness-1/2/3 tests; add `test_short_store_returns_none` (AC-TC-1); add `test_stale_store_returns_none_no_retry` (AC-TC-2); add `test_fresh_full_store_calls_strategy_and_broker` (AC-TC-3); add `test_no_retry_params_in_constructor` introspecting `__init__` signature (AC-TC-4); confirm `test_open_position_skips_cycle` still passes (AC-TC-5); use new `FakeCandleStore`.
- [ ] 3.6 **GREEN** Create `tests/fakes/fake_candle_store.py` — `FakeCandleStore(CandleStorePort)` with injectable `candles` list and `last_start` value; records `recent_candles_calls`.
- [ ] 3.7 **GREEN** Modify `src/application/trading_cycle.py` — replace `broker` candle source with `candle_store: CandleStorePort` constructor param; remove `freshness_max_retries`/`freshness_retry_seconds`; implement single staleness check (`candles[-1].timestamp != expected → warn + None`); startup-race guard (`len < required → None`). Make 3.5 pass.

### Phase 13: __main__ wiring + startup-race guard

- [ ] 3.8 **RED** `tests/unit/test_main_wiring.py` (create or modify) — assert `RunTradingCycleUseCase` is constructed with a `CandleStorePort` arg, not `broker.recent_candles`; `startup_required` param absent or `None`.
- [ ] 3.9 **GREEN** Modify `src/__main__.py` — build `PostgresCandleStore(conn)`; pass `candle_store=store` to `RunTradingCycleUseCase`; remove any broker-candle wiring; `ingestion.py` is a separate process — no wiring here. Make 3.8 pass.

### Phase 14: Final suite clean-up

- [ ] 3.10 Verify full suite green: `cd operator && .venv/bin/python3 -m pytest`; confirm zero references to `BrokerPort.recent_candles`, `freshness_max_retries`, or `freshness_retry_seconds` remain in source or tests.
- [ ] 3.11 **Integration smoke** (optional if DATABASE_URL available): run `tests/integration/test_postgres_candle_store.py` + `tests/integration/test_candle_migration.py` against real PG to confirm AC-WCI-7 (idempotent overlap from live event after backfill).

> **Slice 3 exit gate**: `cd operator && .venv/bin/python3 -m pytest` passes; `RunTradingCycleUseCase` has no freshness params; `BrokerPort` has no `recent_candles`; all AC-TC-* and AC-CSP-* green.

---

## AC → Task mapping

| Acceptance Criterion | Task(s) |
|---------------------|---------|
| AC-CSP-1 (idempotent upsert) | 1.9, 1.15 |
| AC-CSP-2 (oldest-first mid) | 1.10, 1.15 |
| AC-CSP-3 (count cap) | 1.11, 1.15 |
| AC-CSP-4 (empty → []) | 1.12, 1.15 |
| AC-CSP-5 (last_candle_start None) | 1.13, 1.15 |
| AC-CSP-6 (last_candle_start newest) | 1.14, 1.15 |
| AC-CSP-7 (mid formula) | 1.10, 1.15, 1.16 |
| AC-CSP-8 (migration discovery) | 1.7, 1.8 |
| AC-WCI-1 (bid alone no write) | 2.6, 2.9 |
| AC-WCI-2 (bid+ask → one row) | 2.6, 2.9 |
| AC-WCI-3 (ask+bid → one row) | 2.6, 2.9 |
| AC-WCI-4 (epics independent) | 2.6, 2.9 |
| AC-WCI-5 (cold backfill) | 2.11, 2.15 |
| AC-WCI-6 (gap-fill only) | 2.12, 2.15 |
| AC-WCI-7 (idempotent overlap) | 1.9, 1.15, 3.11 |
| AC-WCI-8 (epoch-ms conversion) | 2.7, 2.9 |
| AC-TC-1 (short store → None) | 3.5, 3.7 |
| AC-TC-2 (stale → None no retry) | 3.5, 3.7 |
| AC-TC-3 (fresh+full → broker) | 3.5, 3.7 |
| AC-TC-4 (no retry params) | 3.5, 3.7 |
| AC-TC-5 (open position skip) | 3.5, 3.7 |
| AC-CS-1 (streaming_host after auth) | 2.1, 2.2 |
| AC-CS-2 (streaming_host before auth raises) | 2.1, 2.2 |
| AC-CS-3 (authenticate returns SessionTokens) | 2.1, 2.2 |
| AC-CS-4 (tokens() unaffected) | 2.1, 2.2 |
