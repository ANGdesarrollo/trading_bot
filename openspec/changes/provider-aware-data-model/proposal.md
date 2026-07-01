# Proposal: Provider-Aware Data Model

## Intent

The data model has NO concept of a **provider** (data/broker origin). Today Capital.com is the only source, but IC Markets is planned. When a second provider is added, two identity bugs surface:

- **`candles`**: `UNIQUE(epic, resolution, candle_start)` omits provider. The same epic string from two providers either **collides on the unique key (data corruption)** or, if epic strings differ, cannot be filtered/queried by provider.
- **`trade_entries`**: has `symbol` but no provider column, so trades cannot be attributed to a broker.

"Provider" is entirely absent from the codebase (no field, enum, config, or literal `"capital"`). `BrokerPort`/`CapitalBrokerAdapter` is an execution abstraction, not data provenance. This change adds provider as a first-class attribute of stored candles and trades, as the foundation for a provider-aware candle-viewing frontend.

## Scope

### In Scope
- Add `provider` to the `candles` table: new unique key `(provider, epic, resolution, candle_start)`, replacing the old key + index.
- Add `provider` to the `trade_entries` table.
- Thread `provider` through domain entities (`CandleRow`, `JournalEntry`), ports (candle-store read + write, trade-journal, candle-history), Postgres adapters, Capital producers, config, and composition roots.
- Provider is stamped at **construction time** (injected into producers), defaulting to `"capital"`; NOT parsed from WS payloads.
- Backward-compatible migration via `DEFAULT 'capital'` — existing rows auto-correct, no manual backfill.

### Out of Scope
- **PR 2** — read-only provider-aware HTTP candle API.
- **PR 3** — frontend wiring.
- Actual IC Markets adapter/onboarding (no second producer built here).
- Any change to strategy math, signal logic, order execution, or reconciliation behavior.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `candle-store`: `CandleRow` gains `provider`; `recent_candles` / `last_candle_start` gain a `provider` param (read-by-provider needed for PR 2); `upsert_candle` writes provider; unique key becomes `(provider, epic, resolution, candle_start)`.
- `trading-cycle`: `JournalEntry` gains `provider`; `_build_entry` stamps it so trades are attributable to a broker.
- `capital-session`: Capital producers (`CapitalWsIngester`, `CapitalCandleHistory`, `PairBuffer`) accept an injected `provider` and stamp every emitted row.

## Approach

- **Representation: plain lowercase string** (`"capital"`, `"ic_markets"`), not an enum. Rationale: it mirrors the existing `epic`/`resolution`/`symbol` string convention, needs no cross-layer type import, serializes cleanly for the PR 2 API/frontend, and stays open for new providers via config alone. An enum would add a domain type and migration coupling for zero current invariant.
- **Read path gets `provider` too**, not just writes. PR 2 (the API) must READ candles by provider; adding the param now avoids a second breaking port change and keeps write/read symmetric.
- **Backward-compatible defaults** (`provider: str = "capital"`) on every new param and `DEFAULT 'capital'` in SQL keep existing data valid and existing tests green, making the change low-risk.
- **Injection at construction**: `Config.provider` (env `PROVIDER`, default `"capital"`) flows through composition roots into producers, which stamp each `CandleRow`/`JournalEntry`. WS payloads never carry provider, so construction is the only reliable source.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `.../migrations/003_add_provider_to_candles.sql` | New | Add col; drop old `UNIQUE` + `idx_candles_recent`; add `UNIQUE(provider, epic, resolution, candle_start)` + new index |
| `.../migrations/004_add_provider_to_trade_entries.sql` | New | Add `provider` column, `DEFAULT 'capital'` |
| `src/domain/entities/candle_row.py`, `journal.py` | Modified | Add `provider` field |
| `src/domain/ports/candle_store_port.py` | Modified | `recent_candles`, `last_candle_start` gain `provider` |
| `src/domain/ports/trade_journal_port.py`, `candle_history_port.py` | Modified | `fetch_history` gains `provider`; journal writes provider |
| `src/infrastructure/postgres/candle_store.py`, `journal_adapter.py` | Modified | Upsert + SELECTs carry provider |
| `src/infrastructure/capital/_pair_buffer.py`, `candle_history.py`, `ws_ingester.py` | Modified | Accept + stamp injected provider |
| `src/config.py` | Modified | `provider: str = "capital"` (env `PROVIDER`) |
| `src/application/trading_cycle.py` | Modified | `_build_entry` stamps `JournalEntry.provider` |
| `src/__main__.py`, `ingestion.py`, `reconciler.py` | Modified | Wire provider from config into producers + journal |
| tests (unit + integration + fakes) | Modified | ~9 test files updated; new provider tests for candles + journal |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Migration `003` drops/recreates unique index on live `candles` | Med | Additive column first with `DEFAULT 'capital'`; index swap is fast (no data rewrite); idempotent `IF EXISTS`/`IF NOT EXISTS` |
| Silent default masks a real missing-provider bug | Low | Default `"capital"` is correct for all current data; second provider must set `PROVIDER` explicitly per producer process |
| Missed edit site among ~25 across 5 layers breaks writes | Med | Backward-compatible defaults keep unpatched callers compiling; strict TDD covers each entity/port/adapter |
| No impact on signal evaluation or trade execution | Low | Provider is a stored attribute only; strategy, signal, and order paths are untouched — verified in scope |

## Rollback Plan

Migrations `003`/`004` are additive (new column + index swap). To revert: restore the old `UNIQUE(epic, resolution, candle_start)` + `idx_candles_recent` and drop the `provider` column; existing rows are unaffected since all are `"capital"`. Code reverts via git (`operator/` is a standalone repo). Because every new param defaults to `"capital"`, a partial revert leaves the system functionally identical to today.

## Dependencies

- None new. Uses the existing sorted-`.sql` migration runner and `schema_migrations` tracking.

## Success Criteria

- [ ] `candles` unique key is `(provider, epic, resolution, candle_start)`; existing rows are `provider = 'capital'`.
- [ ] `trade_entries` has a `provider` column; existing rows are `'capital'`.
- [ ] `CandleRow` and `JournalEntry` carry `provider`; every Capital-produced row is stamped from injected config.
- [ ] `recent_candles` / `last_candle_start` filter by provider; PR 2 can read one provider's candles.
- [ ] All existing tests pass unchanged (defaults preserve behavior); new provider tests are green.
- [ ] Strategy, signal, order, and reconciliation behavior are byte-for-byte unchanged.

## Review Workload Forecast

- Estimated changed lines: **>400** (~25 edit sites across 5 layers + 2 migrations + ~9 test files).
- **400-line budget risk: High**
- **Chained PRs recommended: Yes**
- **Decision needed before apply: Yes**
- Suggested slices: (1) migrations `003`/`004` + `CandleRow`/`JournalEntry` provider fields + config; (2) ports + Postgres adapters (read/write provider) + fakes; (3) Capital producers + composition roots wiring + remaining tests.
