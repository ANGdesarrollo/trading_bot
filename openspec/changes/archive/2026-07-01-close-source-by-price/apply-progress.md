# Apply Progress: close-source-by-price

**Status**: done
**Suite**: 102 passed, 8 skipped, 0 failures
**Baseline**: 91 passed / 8 skipped
**New tests added**: 11 (10 deriver unit + 1 keystone reconciler)

---

## Task 1 — Pure deriver [x] DONE

**TDD evidence**:
- RED: `ModuleNotFoundError: No module named 'domain.services'` — all 10 tests failed at import
- GREEN: all 10 passed after creating `src/domain/services/close_source.py`
- REFACTOR: no changes needed, function already minimal

**Files created**:
- `src/domain/services/close_source.py` — pure `derive_close_source` function
- `tests/unit/test_close_source_derivation.py` — 10 parametrized tests

---

## Task 2 — Adapter passthrough [x] DONE

**TDD evidence**:
- RED: `assert 'SL' == 'SYSTEM'` failure in `test_closed_trade_returns_raw_system_source`
- GREEN: all 6 adapter tests pass after removing SYSTEM→SL mapping

**Files modified**:
- `tests/unit/test_capital_trade_history.py` — renamed test, flipped assertion to `"SYSTEM"`
- `src/infrastructure/capital/history_adapter.py` — `"SYSTEM": "SL"` → `"SYSTEM": "SYSTEM"` in map

---

## Task 3 — Reconciler wiring [x] DONE (KEYSTONE)

**TDD evidence**:
- RED: `assert 'SYSTEM' == 'TP'` failure in `test_system_close_at_tp_level_journaled_as_tp`
- GREEN: keystone passes after importing `derive_close_source` and using `derived_source` in `JournalResult`

**Files modified**:
- `tests/unit/test_reconcile_use_case.py` — added keystone test
- `src/application/reconcile_closed_trades.py` — wired deriver before `JournalResult`

---

## Task 4 — Full suite verification [x] DONE

**Result**: `102 passed, 8 skipped` — zero failures, zero errors.
