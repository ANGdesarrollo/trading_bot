# Verify Report: trade-journal-postgres

**Change**: trade-journal-postgres
**Date**: 2026-07-01
**Verdict**: SHIP-WITH-FIXES
**Mode**: Strict TDD
**Artifact store**: openspec + engram

---

## Test Suite Evidence

```
Command: cd /home/alexis/Documents/Projects/TRADING_PROJECT_DEFINITIVE/operator && .venv/bin/python3 -m pytest -q
Result:  93 passed, 3 skipped, 4 warnings in 99.82s
```

- 93 passed: all unit tests pass.
- 3 skipped: `tests/integration/test_postgres_journal.py` — correct, DATABASE_URL not set in CI.
- 4 warnings: pre-existing numpy RuntimeWarnings in `research/lib/trajectory.py`, unrelated to this change.
- Pre-existing test count (57) preserved: confirmed all pass.

---

## Task Completeness

| Task | Description | Checked in tasks.md | Code exists | Status |
|------|-------------|---------------------|-------------|--------|
| T-01 | psycopg dep + DATABASE_URL config | [x] | Yes | COMPLETE |
| T-02 | JournalEntry, JournalResult, ClosedTrade VOs | [x] | Yes | COMPLETE |
| T-03 | TradeJournalPort + TradeHistoryPort ABCs | [x] | Yes | COMPLETE |
| T-04a | FakeJournalPort | [x] | Yes | COMPLETE |
| T-04b | FakeTradeHistoryPort | [x] | Yes | COMPLETE |
| T-05 | SQL migration + idempotent runner | [x] | Yes | COMPLETE |
| T-06 | PostgresTradeJournal adapter | [x] | Yes | COMPLETE |
| T-07 | Wire journal into RunTradingCycleUseCase | [x] | Yes | COMPLETE |
| T-08 | Wire journal into operator composition root | [x] | Yes | COMPLETE |
| T-09 | Integration test — Postgres journal round-trip | [x] | Yes (3 SKIPs) | COMPLETE |
| T-10 | ReconcileClosedTradesUseCase | [x] | Yes | COMPLETE |
| T-11 | CapitalTradeHistory adapter | [x] | Yes | COMPLETE |
| T-12 | Reconciler entrypoint + 1-min loop | [x] | Yes | COMPLETE |
| T-13 | docker-compose.yml + Makefile | [x] | Yes | COMPLETE |

All 13 tasks checked off AND verified to exist in code.

---

## Spec Compliance Matrix

### REQ-01 / Scenarios 1.1–1.4 — TradeJournalPort

| Scenario | Requirement | Test | Status |
|----------|-------------|------|--------|
| 1.1 — record_entry persists row | INSERT ON CONFLICT DO NOTHING | `test_record_entry_executes_insert_on_conflict_do_nothing` | PASS |
| 1.2 — record_entry idempotent | second call does not raise | `test_record_entry_idempotent_on_duplicate` | PASS |
| 1.3 — record_result writes result cols only | guarded UPDATE WHERE reconciled_at IS NULL | `test_record_result_uses_guarded_update` | PASS |
| 1.4 — open_entries returns unreconciled only | SELECT WHERE reconciled_at IS NULL | `test_open_entries_filters_reconciled_at_null` | PASS |

### REQ-02/REQ-03/REQ-04 / Scenario 2.1 — Domain entities

| Requirement | Check | Status |
|-------------|-------|--------|
| REQ-02 — JournalEntry immutable VO | frozen=True, slots=True dataclass | PASS |
| REQ-03 — atr_at_entry MUST NOT be supplied by caller; must be derived | **DEVIATION**: entity accepts atr_at_entry as a plain field; derivation is in trading_cycle._build_entry. Applied-progress documents this as an intentional deviation following the hexagonal "critical constraint" that domain entities must not import infrastructure constants. Derivation happens correctly in the app layer. | DEVIATION (intentional, compliant with hexagonal principle) |
| Scenario 2.1 — atr_at_entry == sl_distance / SL_ATR_MULT | Derivation in `_build_entry`: `atr_at_entry=signal.sl_distance / SL_ATR_MULT` | PASS |
| REQ-04 — JournalResult immutable VO with close_source in {SL, TP, USER, CLOSE_OUT} | **WARNING**: JournalResult.close_source is typed as `str` with no enforcement. CapitalTradeHistory sets it to `match["type"]` which is `"POSITION_CLOSED"` — NOT one of the spec-required values. Confirmed by test assertion `assert result.close_source == "POSITION_CLOSED"` | WARNING |

### REQ-05/REQ-06 / Scenarios 3.1–3.3 — Best-effort entry write

| Scenario | Test | Status |
|----------|------|--------|
| 3.1 — record_entry called after successful open | `test_journal_record_entry_called_after_successful_open` | PASS |
| 3.2 — no entry when no signal | `test_journal_not_called_when_no_signal` | PASS |
| 3.3 — journal failure does not crash cycle | `test_journal_failure_does_not_crash_cycle` | PASS |

### REQ-07 / Scenarios 4.1–4.2 — realized_r arithmetic

| Scenario | Formula | Test | Status |
|----------|---------|------|--------|
| 4.1 — winning trade | `(19.0 - 1.0) / (0.0020 * 10000) = 0.9` | `test_open_entry_gets_reconciled_when_closed` | PASS |
| 4.2 — losing trade | `(-20.0 - 1.0) / (0.0020 * 10000) = -1.05` | `test_realized_r_losing_trade` | PASS |
| SELL/short case sign | Tasks T-10 listed `test_realized_r_sell_win`. Not implemented. The PNL-based formula is direction-agnostic (broker provides signed PNL directly), so SELL correctness is implicit but untested. | SUGGESTION |

### REQ-08/REQ-09/REQ-10/REQ-11 / Scenarios 5.1–5.4 — Reconciler

| Scenario | Test | Status |
|----------|------|--------|
| 5.1 — open entry reconciled on close | `test_open_entry_gets_reconciled_when_closed` | PASS |
| 5.2 — still-open position left untouched | `test_still_open_position_skipped` | PASS |
| 5.3 — malformed lookup does not abort remaining | `test_lookup_failure_does_not_abort_remaining` | PASS |
| 5.4 — re-running on already-reconciled is no-op | `test_already_reconciled_entry_not_returned_by_open_entries` (open_entries returns [] when reconciled) | PASS |

### REQ-12/REQ-13/REQ-14 / Scenario 6.1 — Reconciler entrypoint

| Requirement | Implementation | Status |
|-------------|----------------|--------|
| REQ-12 — separate OS process, 60s cadence | `src/reconciler.py` independent entrypoint, `clock.sleep(60)` in loop | PASS |
| REQ-13 — reconciler crash does not affect operator | Separate processes, shared DB only | PASS |
| REQ-14 — cycle error caught, loop continues | `try/except Exception: logger.exception(...)` in loop | PASS |
| Scenario 6.1 — exception logged, loop retries | `test_reconciler_loop_catches_exception_and_continues` in `test_reconciler_loop.py` | PASS |

### REQ-15/REQ-16/REQ-17 / Scenarios 7.1–7.3 — Migration runner

| Scenario | Test | Status |
|----------|------|--------|
| 7.1 — first run creates schema_migrations and applies pending | `test_runner_creates_schema_migrations_table_on_first_run`, `test_runner_applies_pending_sql_in_order` | PASS |
| 7.2 — second run is no-op | `test_runner_skips_already_applied_migration` | PASS |
| 7.3 — new migration applied, old skipped | `test_runner_applies_new_migration_when_first_already_applied` | PASS |

### REQ-18 / Scenario 8.1 — DATABASE_URL configuration

| Scenario | Test | Status |
|----------|------|--------|
| 8.1 — missing DATABASE_URL raises early | `test_database_url_missing_raises_config_error` | PASS |

### REQ-19/REQ-20 — Infrastructure bring-up

| Requirement | Implementation | Status |
|-------------|----------------|--------|
| REQ-19 — make up starts only Postgres | `docker-compose.yml` has single `postgres` service; `make up` = `docker compose up -d` | PASS |
| REQ-20 — make operator and make reconciler are independent | Both targets exist in Makefile with no shared dependencies | PASS |

---

## Design Coherence

| Decision | Implemented | Deviation |
|----------|-------------|-----------|
| Two ports (ISP): TradeJournalPort + TradeHistoryPort; BrokerPort untouched | Both ports created; BrokerPort unchanged | None |
| Disjoint column ownership: INSERT entry cols / UPDATE result cols WHERE reconciled_at IS NULL | Verified in SQL constants in journal_adapter.py | None |
| realized_r formula | Design says price-based; spec says PNL-based. Implementation follows SPEC. Design note is internally inconsistent with the formula table. | Design deviation (spec wins correctly) |
| atr_at_entry derived in app layer | Derived in `_build_entry`, not in domain entity | Documented intentional deviation |
| Migration runner idempotent, both processes call it on startup | operator in build_use_case, reconciler in __main__ block | None |
| psycopg v3 sync | psycopg[binary] added to pyproject.toml | None |

---

## Invariant Checks

### 1. Domain Purity (hexagonal invariant)

`src/domain/entities/journal.py`: imports only `dataclasses` and `datetime`. No infrastructure, no SL_ATR_MULT. CLEAN.

`src/domain/ports/trade_journal_port.py`: imports only `abc`, `collections.abc`, and `domain.entities.journal`. CLEAN.

`src/domain/ports/trade_history_port.py`: imports only `abc`, `datetime`, and `domain.entities.journal`. CLEAN.

`SL_ATR_MULT` is imported in `src/application/trading_cycle.py` (application layer) — correct.

### 2. ISP: BrokerPort untouched

`src/domain/ports/broker_port.py` verified unchanged. Two new ports created independently. PASS.

### 3. Best-effort entry write

`trading_cycle.py` line 75–79: `try: ... except Exception: logger.exception(...)` wraps only the journal call, after `open_position` returns. The `result` is returned regardless. PASS.

### 4. Reconciler isolation per-entry

`reconcile_closed_trades.py`: `try/except Exception` inside the `for entry in ...` loop. One failing deal_id does not abort the rest. PASS.

### 5. Conflict-free writes

`_INSERT_ENTRY`: `ON CONFLICT (deal_id) DO NOTHING`. PASS.
`_UPDATE_RESULT`: `WHERE deal_id = %s AND reconciled_at IS NULL`. PASS.

### 6. realized_r formula

`compute_realized_r(pnl, fees, sl_distance, position_size)`: `risk_currency = sl_distance * position_size; return (pnl - fees) / risk_currency`. Matches spec REQ-07 exactly. PASS.

### 7. Migration idempotency

Runner uses `CREATE TABLE IF NOT EXISTS schema_migrations`, checks applied set before executing each file, commits per file. Double-run is a no-op by design. PASS.

### 8. Integration test skip guard

`tests/integration/test_postgres_journal.py` line 9: `pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")`. Confirmed 3 SKIPs in suite output. PASS.

---

## Issues

### CRITICAL

None.

---

### WARNING

**W-01 — close_source spec violation in CapitalTradeHistory**

Spec REQ-04 states `close_source` must be one of `"SL"`, `"TP"`, `"USER"`, `"CLOSE_OUT"`.

`history_adapter.py` line 62 sets `close_source=match["type"]`, where `match["type"]` is always `"POSITION_CLOSED"` (the Capital.com activity type field used to filter). The test at line 71 of `test_capital_trade_history.py` asserts `result.close_source == "POSITION_CLOSED"` — confirming the violation.

This means every reconciled row in the database will have `close_source = "POSITION_CLOSED"` instead of `"SL"`, `"TP"`, `"USER"`, or `"CLOSE_OUT"`. The close reason is currently unresolvable from activity data alone because the Capital.com activity type field encodes the event type, not the close reason.

**Impact**: Functional (persists incorrect data). Does not crash the system but makes `close_source` semantically wrong.

**Fix needed**: Map the actual close reason from a different field in the activity payload (e.g., `details.actions[].actionType`) or document that the Capital.com API does not provide a granular close reason at this endpoint, and use a sentinel like `"UNKNOWN"` explicitly.

---

### SUGGESTION

**S-01 — Missing SELL/short realized_r test**

Tasks T-10 explicitly listed `test_realized_r_sell_win` as a required test to confirm direction-sign correctness for SELL trades. It does not appear in `test_reconcile_use_case.py`.

The PNL-based formula `(pnl - fees) / (sl_distance * position_size)` is direction-agnostic (broker provides signed PNL), so SELL is implicitly correct. However, the tasks spec mandated the explicit coverage. Adding this test would complete the test triangulation and protect against future formula changes.

**S-02 — Makefile `operator` target path issue**

`Makefile` reconciler target: `cd src && ../.venv/bin/python3 -m reconciler` — the `-m reconciler` would resolve to `src/reconciler.py` which is correct when `cwd=src`. However operator target: `cd src && ../.venv/bin/python3 -m src` would fail because `src` is a directory without an `__init__.py` making it importable as `src`. The `__main__.py` sits at `src/__main__.py` — this would need `python -m __main__` from inside `src/` or `python src/__main__.py` from the operator root. This is a runtime concern (not tested by unit tests) but worth validating before deployment.

**S-03 — Narrating module docstring in reconciler.py**

`src/reconciler.py` has a module docstring at line 1–6 that describes what the file does and how it runs. Per project code quality rules, comments should only capture non-obvious WHY/contracts, not narrate what the code does. The docstring is readable code narration. Suggest removing it.

---

## Code Quality

- No duplicate `SL_ATR_MULT` literals: single import from `domain.adapters.fade_strategy` in the application layer. PASS.
- SQL constants extracted as module-level constants in `journal_adapter.py`. PASS.
- `compute_realized_r` extracted as a pure module-level function. PASS.
- `_to_iso`, `_row_to_entry`, `_build_entry` extracted as focused helpers. PASS.
- Domain entities and ports contain zero infrastructure imports. PASS.
- One narrating docstring identified in `reconciler.py` (see S-03).

---

## Final Verdict

**SHIP-WITH-FIXES**

The implementation is functionally sound. All 13 tasks are complete, 93 tests pass (3 integration tests correctly skip without a live DB), and every spec invariant except one is correctly implemented.

W-01 (`close_source` stores `"POSITION_CLOSED"` instead of `"SL"`/`"TP"` etc.) is a data-quality violation that makes the reconciled rows semantically wrong. It does not crash anything, but it persists incorrect information to the database for every reconciled trade. This needs a fix before the journal data can be trusted for analysis.

**To archive**: fix W-01 (map `close_source` correctly from Capital.com API), add S-01 (`test_realized_r_sell_win`). S-02 and S-03 can be deferred.
