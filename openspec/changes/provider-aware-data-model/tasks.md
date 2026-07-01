# Tasks: Provider-Aware Data Model

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~550–700 (migrations + entity fields + adapter SQL + port sigs + producers + tests) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 (Slice 1) → PR 2 (Slice 2) → PR 3 (Slice 3) |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Migrations 003/004 + `CandleRow`/`JournalEntry` provider field + `Config.provider` | PR 1 → main | ~180 lines; defaults keep every existing caller/test green |
| 2 | Ports `provider` param + Postgres adapters SQL + `FakeCandleStore` seam | PR 2 → main | ~220 lines; integration tests for upsert/select round-trips; depends on PR 1 |
| 3 | Capital producers wiring + composition roots + remaining unit tests | PR 3 → main | ~160 lines; unit tests with fakes; depends on PR 2 |

---

## Slice 1 — Migrations + Domain Entities + Config (PR 1 → main)

### Phase 1: Schema migrations

- [x] 1.1 **RED** `tests/integration/test_candle_migration.py` (modify) — assert `candles` table has `provider` column after migration 003; existing rows default to `"capital"`; new unique constraint is `(provider,epic,resolution,candle_start)`; old constraint `candles_epic_resolution_candle_start_key` absent; `idx_candles_recent` exists and leads with `provider`; two rows same `(epic,resolution,candle_start)` different `provider` coexist (no constraint violation). (CSP-07)
- [x] 1.2 **GREEN** Create `src/infrastructure/postgres/migrations/003_add_provider_to_candles.sql` — `ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'capital'`; `DROP CONSTRAINT IF EXISTS candles_epic_resolution_candle_start_key`; `DROP INDEX IF EXISTS idx_candles_recent`; `ADD CONSTRAINT candles_provider_epic_resolution_candle_start_key UNIQUE(provider,epic,resolution,candle_start)`; `CREATE INDEX IF NOT EXISTS idx_candles_recent ON candles(provider,epic,resolution,candle_start DESC)`. Make 1.1 pass.
- [x] 1.3 **RED** `tests/integration/test_candle_migration.py` (same file) — assert `trade_entries` table has `provider` column after migration 004; existing rows default to `"capital"`; `deal_id` remains the identity column (no new unique change). (CSP-10)
- [x] 1.4 **GREEN** Create `src/infrastructure/postgres/migrations/004_add_provider_to_trade_entries.sql` — `ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'capital'`. Make 1.3 pass.

### Phase 2: CandleRow entity

- [x] 1.5 **RED** `tests/unit/test_candle_row.py` (modify) — assert `CandleRow` has `provider` as its first field; `CandleRow()` without explicit `provider` has `row.provider == "capital"`; `CandleRow(provider="ic_markets", …)` has `row.provider == "ic_markets"`; mutation still raises `AttributeError`. (CSP-02)
- [x] 1.6 **GREEN** Modify `src/domain/entities/candle_row.py` — add `provider: str = "capital"` as the **first** field of the frozen `slots=True` dataclass. Make 1.5 pass.

### Phase 3: JournalEntry entity

- [x] 1.7 **RED** `tests/unit/test_journal_entities.py` (modify) — assert `JournalEntry` has `provider` field; default is `"capital"`; `JournalEntry(provider="capital", …)` mutation raises `AttributeError`. (TC-07)
- [x] 1.8 **GREEN** Modify `src/domain/entities/journal.py` — add `provider: str = "capital"` to the `JournalEntry` frozen dataclass. Make 1.7 pass.

### Phase 4: Config provider field

- [x] 1.9 **RED** `tests/unit/test_config.py` (modify) — assert `Config()` (no env) has `config.provider == "capital"`; with `PROVIDER="ic_markets"` env, `config.provider == "ic_markets"`. (CSP-09)
- [x] 1.10 **GREEN** Modify `src/config.py` — add `provider: str` sourced from `env.get("PROVIDER", "capital").lower()`. Make 1.10 pass.

> **Slice 1 exit gate**: `uv run python -m pytest` passes; `CandleRow.provider` defaults to `"capital"`; `JournalEntry.provider` defaults to `"capital"`; migrations 003/004 green; existing callers untouched (all prior tests still pass via defaults).

---

## Slice 2 — Ports + Postgres Adapters (PR 2 → main)

### Phase 5: CandleStorePort signature

- [x] 2.1 **RED** `tests/unit/test_candle_store_port.py` (modify) — assert `recent_candles` signature leads with `provider` having default `"capital"`; same for `last_candle_start`; ABC still raises `TypeError` if not implemented. (CSP-01)
- [x] 2.2 **GREEN** Modify `src/domain/ports/candle_store_port.py` — add `provider: str = "capital"` as first param (after `self`) to `recent_candles` and `last_candle_start`. Make 2.1 pass.

### Phase 6: CandleHistoryPort signature

- [x] 2.3 **RED** `tests/unit/test_candle_history_port.py` (modify) — assert `fetch_history` leads with `provider: str = "capital"`. (CS-05)
- [x] 2.4 **GREEN** Modify `src/domain/ports/candle_history_port.py` — add `provider: str = "capital"` as first param to `fetch_history`. Make 2.3 pass.

### Phase 7: FakeCandleStore seam

- [x] 2.5 **GREEN** Modify `tests/fakes/fake_candle_store.py` — add `provider` param to `recent_candles` and `last_candle_start` to match updated port signature; record it in call-log for assertion. (no new RED — fixes existing fake to compile)

### Phase 8: PostgresCandleStore adapter

- [x] 2.6 **RED** `tests/integration/test_postgres_candle_store.py` (modify) — assert `upsert_candle` twice same `(provider,epic,resolution,candle_start)` → one row, second OHLC wins (AC-CSP-1); rows from `provider="capital"` and `provider="ic_markets"` coexist on same `(epic,resolution,candle_start)` (CSP-04); `recent_candles("capital",…)` returns only capital rows when ic_markets rows also exist (CSP-05 provider isolation); `last_candle_start("capital",…)` returns T3 not T5 when ic_markets has T5 (CSP-06). (CSP-04, CSP-05, CSP-06)
- [x] 2.7 **GREEN** Modify `src/infrastructure/postgres/candle_store.py` — `upsert_candle` SQL: `provider` becomes first column in `INSERT` and `ON CONFLICT(provider,epic,resolution,candle_start)`; `recent_candles` WHERE clause adds `provider=%s` as first predicate; `last_candle_start` WHERE clause adds `provider=%s` as first predicate. Make 2.6 pass.

### Phase 9: PostgresTradeJournal adapter

- [x] 2.8 **RED** `tests/integration/test_postgres_journal.py` (modify) — assert inserting a `JournalEntry(provider="capital", …)` persists `provider`; `_row_to_entry` reconstructs `provider` correctly; existing open-positions query still returns entries. (TC-07)
- [x] 2.9 **GREEN** Modify `src/infrastructure/postgres/journal_adapter.py` — add `provider` to `_INSERT_ENTRY` column list and `VALUES` placeholders; add `provider` to `_SELECT_OPEN` column list; map it in `_row_to_entry`. Make 2.8 pass.

> **Slice 2 exit gate**: `uv run python -m pytest` passes; integration tests assert provider isolation in `candles`; `PostgresTradeJournal` round-trips `provider`; all pre-existing AC-CSP-* and AC-TC-* tests still green.

---

## Slice 3 — Capital Producers + Composition Roots (PR 3 → main)

### Phase 10: PairBuffer provider stamp

- [ ] 3.1 **RED** `tests/unit/test_pair_buffer.py` (modify) — assert `PairBuffer(provider="capital")` stamps `row.provider == "capital"` on every emitted `CandleRow`; `PairBuffer(provider="ic_markets")` stamps `"ic_markets"`. (CS-05, AC-WCI-2, AC-WCI-3)
- [ ] 3.2 **GREEN** Modify `src/infrastructure/capital/_pair_buffer.py` — add `provider: str = "capital"` to `__init__`; store as `self._provider`; pass `provider=self._provider` when constructing `CandleRow` in `on_event`. Make 3.1 pass.

### Phase 11: CapitalCandleHistory provider stamp

- [ ] 3.3 **RED** `tests/unit/test_capital_candle_history.py` (modify) — assert `CapitalCandleHistory(…, provider="capital")` returns rows where every `row.provider == "capital"`; assert `fetch_history` is called with leading `provider` arg that flows through to `_to_rows`; assert `_to_rows` receives `provider` as first positional argument (not a class field). (CS-05)
- [ ] 3.4 **GREEN** Modify `src/infrastructure/capital/candle_history.py` — add `provider: str = "capital"` to `__init__`; store as `self._provider`; thread `provider` as first arg into module-level `_to_rows(provider, raw_prices, epic, resolution)` calls inside `_cold_backfill` and `_gap_fill`; update `_to_rows` signature and `CandleRow` construction to pass `provider`. Make 3.3 pass.

### Phase 12: CapitalWsIngester provider injection

- [ ] 3.5 **RED** `tests/unit/test_ws_ingester.py` (modify) — assert `CapitalWsIngester(…, provider="capital")` constructs `PairBuffer(provider="capital")`; assert `fetch_history` is called with `"capital"` as first argument; emitted rows have `row.provider == "capital"`. (CS-05)
- [ ] 3.6 **GREEN** Modify `src/infrastructure/capital/ws_ingester.py` — add `provider: str = "capital"` to `__init__`; store as `self._provider`; pass `provider=self._provider` to `PairBuffer` constructor; pass `self._provider` as first arg to `candle_history.fetch_history(…)` calls. Make 3.5 pass.

### Phase 13: RunTradingCycleUseCase provider injection

- [ ] 3.7 **RED** `tests/unit/test_trading_cycle.py` (modify) — assert `RunTradingCycleUseCase(…, provider="capital")` calls `recent_candles("capital", symbol, resolution, count)` with provider as first arg (TC-02, TC-08); assert `_build_entry` produces `entry.provider == "capital"` (TC-07); assert omitting `provider` defaults to `"capital"`. (TC-02, TC-07, TC-08)
- [ ] 3.8 **GREEN** Modify `src/application/trading_cycle.py` — add `provider: str = "capital"` to `__init__`; store as `self._provider`; pass `self._provider` as first arg to `candle_store.recent_candles(…)` call; stamp `provider=self._provider` in `_build_entry` when constructing `JournalEntry`. Make 3.7 pass.

### Phase 14: Composition root wiring

- [ ] 3.9 **RED** `tests/unit/test_main_wiring.py` (modify) — assert `build_use_cases` passes `provider=config.provider` to `RunTradingCycleUseCase`; no hardcoded `"capital"` string in `__main__.py`. (CS-06)
- [ ] 3.10 **GREEN** Modify `src/__main__.py` — pass `provider=config.provider` to `RunTradingCycleUseCase` constructor. Make 3.9 pass.
- [ ] 3.11 **RED** `tests/unit/test_ingestion.py` (modify) — assert ingestion startup passes `provider=config.provider` to both `CapitalWsIngester` and `CapitalCandleHistory`. (CS-06)
- [ ] 3.12 **GREEN** Modify `src/ingestion.py` — pass `provider=config.provider` to `CapitalWsIngester` and `CapitalCandleHistory` at construction. Make 3.11 pass.

### Phase 15: Final suite validation

- [ ] 3.13 Full suite `uv run python -m pytest` — all tests pass; grep confirms zero hardcoded `"capital"` strings in composition roots (`src/__main__.py`, `src/ingestion.py`); grep confirms all three stamp sites (`_pair_buffer.py`, `candle_history.py`, `trading_cycle.py`) pass `provider` explicitly. (CS-05, CS-06)

> **Slice 3 exit gate**: `uv run python -m pytest` passes; all three provider stamp sites covered by strict-TDD tests; no hardcoded `"capital"` in composition roots; `PROVIDER` env drives the entire chain end-to-end.

---

## AC → Task mapping

| Acceptance Criterion | Task(s) |
|---------------------|---------|
| CSP-01 (port signatures) | 2.1, 2.2 |
| CSP-02 (CandleRow.provider) | 1.5, 1.6 |
| CSP-04 (upsert conflict key) | 2.6, 2.7 |
| CSP-05 (recent_candles provider filter) | 2.6, 2.7 |
| CSP-05a (multi-timeframe isolation) | 2.6, 2.7 |
| CSP-06 (last_candle_start provider filter) | 2.6, 2.7 |
| CSP-07 (migration 003) | 1.1, 1.2 |
| CSP-09 (Config.provider) | 1.9, 1.10 |
| CSP-10 (migration 004) | 1.3, 1.4 |
| TC-02 (recent_candles with provider) | 3.7, 3.8 |
| TC-07 (JournalEntry.provider stamp) | 1.7, 1.8, 3.7, 3.8 |
| TC-08 (TradingCycle provider injection) | 3.7, 3.8 |
| CS-05 (producers stamp provider) | 3.1–3.6 |
| CS-06 (composition roots wire config.provider) | 3.9–3.12 |
