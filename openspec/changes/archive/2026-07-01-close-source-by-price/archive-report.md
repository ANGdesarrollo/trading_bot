# Archive Report: close-source-by-price

**Date**: 2026-07-01
**Change**: close-source-by-price
**Verdict**: SHIPPED
**Test Suite**: 102 passed, 8 skipped, 0 failed

---

## What Shipped

This change corrects the trade journal's attribution of broker-triggered closes by disambiguating SYSTEM closes into SL/TP via nearest price level. The fix restores the hexagonal architecture: infrastructure reports facts (raw API source), domain decides meaning (price-based classification), and application wires them (reconciler calls deriver).

### Core Components

**1. Pure Domain Deriver**
- `src/domain/services/close_source.py` — new module, single free function `derive_close_source(api_source, close_price, filled_price, sl_distance, tp_distance, direction)`
- Accepts USER/CLOSE_OUT unchanged
- For SYSTEM closes, computes SL and TP levels and classifies by nearest price
- Tie-breaks conservatively to "SL" (equidistant resolves to "SL")
- Validates direction (BUY/SELL) and raises `ValueError` on invalid or empty
- Unknown sources fall back to "USER" (unchanged behavior)
- **No infrastructure or adapter imports** — pure policy, testable standalone

**2. Adapter Passthrough**
- `src/infrastructure/capital/history_adapter.py` — removed hard-coded `"SYSTEM": "SL"` mapping
- Now returns the raw Capital.com API `source` value in `ClosedTrade.close_source`
- Preserves raw value for debugging; classification deferred to domain
- Single-source-of-truth mapping: `_ACTIVITY_SOURCE_TO_CLOSE_SOURCE` now passes SYSTEM through, keeps USER/CLOSE_OUT identity, preserves unknown→USER fallback

**3. Reconciler Integration**
- `src/application/reconcile_closed_trades.py` — wired deriver into use-case loop
- Before building `JournalResult`, calls `derive_close_source(closed.close_source, closed.close_price, entry.filled_price, entry.sl_distance, entry.tp_distance, entry.direction)`
- Passes derived label into `JournalResult(close_source=...)` instead of raw API source
- **Keystone invariant**: SYSTEM-sourced closes are never written to journal with raw "SYSTEM" label; the derived "SL" or "TP" is persisted

### Test Coverage

**New Tests Added** (11 total; baseline was 91 passed / 8 skipped):
- 10 deriver unit tests (`test_close_source_derivation.py`): BUY→TP, BUY→SL, SELL→TP, SELL→SL, tie→SL, USER passthrough, CLOSE_OUT passthrough, invalid direction raises, empty direction raises, mixed-case accepted
- 1 keystone reconciler integration test (`test_reconcile_use_case.py`): asserts SYSTEM close at TP level is journaled as "TP" (not raw "SYSTEM")

**Modified Tests**:
- `test_capital_trade_history.py` — flipped adapter test assertion from `"SL"` to `"SYSTEM"` (now confirms raw passthrough)

**Final Result**: 102 passed, 8 skipped, 0 failed — zero regressions.

---

## Outcome

**Problem Solved**: The journal now correctly attributes profit/loss. TP winners are no longer silently mislabeled as SL losses. Win rate, realized-R distribution, and strategy evaluation will reflect actual outcomes, not pessimistic corruption.

**Data Integrity**:
- All required price fields (filled_price, sl_distance, tp_distance, close_price, direction) are already stored in journal entries and closed trades — the deriver requires no new data.
- Classification is deterministic: the same SYSTEM close + entry fields always yield the same derived label.
- Pure function design makes historical recompute trivial if needed.

**Architecture**:
- Restores hexagonal edges: infra facts → domain policy → app wiring
- No schema or port changes
- No new dependencies
- No breaking changes to existing code paths (USER/CLOSE_OUT/unknown sources pass through unchanged)

---

## Deferred Follow-Ups

### 1. DB Backfill of Pre-Existing Mislabeled Rows
**Status**: Not included in this change.
**Rationale**: Demo bot is fresh with few or no real closed rows yet. Backfill adds migration risk without current benefit.
**Future Work**: If real Capital.com history exists, run one-off SQL or script that applies `derive_close_source` to all rows where `close_source = 'SL'` and `close_price` was near TP level. All inputs are already stored, so recompute is offline and reversible.
**Owner**: defer to next session if production data is onboarded

### 2. Manual Empirical Validation of Real Capital.com TP Close
**Status**: Not automated; manual operator task only.
**Rationale**: Assumption that Capital.com reports both SL and TP as "SYSTEM" comes from code comment only. Confirming real API behavior requires manually opening a demo position, closing at TP, and inspecting the `/history/activity` payload.
**Future Work**: Operator manually inspects one real TP close payload to confirm "SYSTEM" is the source value. Do NOT place autonomous demo orders for this.
**Owner**: manual task; not part of automated test suite

---

## Artifact References

All SDD artifacts resolved and persisted:

| Artifact | Location | Topic Key |
|----------|----------|-----------|
| Proposal | `openspec/changes/close-source-by-price/proposal.md` | `sdd/close-source-by-price/proposal` |
| Specification | `openspec/changes/close-source-by-price/spec.md` | `sdd/close-source-by-price/spec` |
| Design | `openspec/changes/close-source-by-price/design.md` | `sdd/close-source-by-price/design` |
| Tasks | `openspec/changes/close-source-by-price/tasks.md` | `sdd/close-source-by-price/tasks` |
| Apply Progress | `openspec/changes/close-source-by-price/apply-progress.md` | `sdd/close-source-by-price/apply-progress` |
| Verify Report | `openspec/changes/close-source-by-price/verify-report.md` | `sdd/close-source-by-price/verify-report` |
| **Archive Report** | `openspec/changes/close-source-by-price/archive-report.md` | `sdd/close-source-by-price/archive-report` |

---

## Files Modified

| File | Lines Changed | Change Type |
|------|---|---|
| `src/domain/services/close_source.py` | ~35 | NEW |
| `src/application/reconcile_closed_trades.py` | ~6 | IMPORT + call deriver |
| `src/infrastructure/capital/history_adapter.py` | ~2 | MAPPING: remove SL override |
| `tests/unit/test_close_source_derivation.py` | ~50 | NEW (10 tests) |
| `tests/unit/test_capital_trade_history.py` | ~2 | ASSERTION: "SL" → "SYSTEM" |
| `tests/unit/test_reconcile_use_case.py` | ~30 | NEW (1 keystone test) |

**Total estimated changed lines**: ~125 (well under 400-line budget)

---

## Quality Gates

- [x] All 102 tests pass (0 failures)
- [x] No CRITICAL findings
- [x] No WARNING findings
- [x] Pure domain function (no infra imports)
- [x] Hexagonal architecture maintained (app → domain → infra only)
- [x] No duplicated knowledge (single `derive_close_source`, single mapping)
- [x] Code quality rules followed (no narrating comments, expressive function/variable names)
- [x] Keystone test present and passing (SYSTEM close at TP level → TP label in journal)
- [x] All spec requirements covered (6/6 requirements PASS)
- [x] All tasks completed (4/4 tasks DONE)

---

## Migration & Rollout

**No migration required.**
- No schema changes to any entity
- No port signature changes
- No database modifications
- Existing closed-trades with stale labels remain until explicit backfill (deferred follow-up)
- All price fields needed for recompute already stored
- Pure function design makes future offline recompute trivial

**Deploy**: Merge single PR to main. Change is self-contained and backward-compatible. No coordinated rollout needed.

---

## Next Recommended

`none` — Change is complete and shipped. Future work is captured as deferred follow-ups above (DB backfill, manual empirical validation). No blocking issues or incomplete artifacts remain.
