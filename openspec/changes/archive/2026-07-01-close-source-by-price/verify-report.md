# Verify Report: close-source-by-price

**Verdict**: SHIP
**Date**: 2026-07-01
**Suite**: 102 passed, 8 skipped, 0 failed

---

## Completeness Table

| Requirement | File(s) | Status |
|---|---|---|
| Price-Based SYSTEM Close Derivation | `src/domain/services/close_source.py` | PASS |
| BUY SL/TP level math | `close_source.py:17-18` | PASS |
| SELL SL/TP level math | `close_source.py:19-20` | PASS |
| Tie-break (<=) → "SL" | `close_source.py:23` | PASS |
| USER passthrough | `close_source.py:12-13` | PASS |
| CLOSE_OUT passthrough | `close_source.py:12-13` | PASS |
| SYSTEM/unknown → price-derived | `close_source.py:14-15` | PASS |
| Direction normalized (.strip().upper()) | `close_source.py:16` | PASS |
| Invalid direction → ValueError | `close_source.py:21-22` | PASS |
| Empty direction → ValueError | `close_source.py:21-22` (empty → no branch match) | PASS |
| Adapter returns raw "SYSTEM" | `history_adapter.py:15` | PASS |
| Reconciler calls derive_close_source | `reconcile_closed_trades.py:34-37` | PASS |
| Reconciler passes derived label to JournalResult | `reconcile_closed_trades.py:43` | PASS |
| No domain→infra import edge | `close_source.py` (no infra imports) | PASS |
| Task 1 [x] | deriver + 10 unit tests | PASS |
| Task 2 [x] | adapter passthrough + flipped test | PASS |
| Task 3 [x] KEYSTONE | reconciler wiring + keystone test | PASS |
| Task 4 [x] | full suite 102/0 | PASS |

---

## Findings

### CRITICAL

None.

### WARNING

None.

### SUGGESTION

**S1 — Equidistant test fixture diverges from tasks spec**
`tasks.md` row 5 specifies `sl_distance=tp_distance=0.0020` for the tie-break case.
`test_close_source_derivation.py` uses the shared `_SL_DIST=0.0020` / `_TP_DIST=0.0040`
and achieves equidistance by choosing `close_price=1.1010` (midpoint between `sl_level=1.0980`
and `tp_level=1.1040`). The math is correct and the tie-break is exercised, but the fixture
diverges from the tasks description. A reader following the tasks table would expect
`sl_dist == tp_dist`. Not a behaviour defect — correctness is fully covered.

**S2 — Unknown source fallback comment removed from implementation**
`history_adapter.py` has a doc comment explaining SYSTEM passthrough, which is the only
non-narrating comment in the changed files and passes the WHY bar. `close_source.py`
has no comments, consistent with code-quality rules. No action required.

---

## Detailed Invariant Checks

**Invariant 1 — Purity**: `close_source.py` imports only `__future__`. No I/O, no
infra or adapter imports. Pure domain function. PASS.

**Invariant 2 — Level math**:
- BUY: `sl_level = filled_price - sl_distance`, `tp_level = filled_price + tp_distance` (line 18). PASS.
- SELL: `sl_level = filled_price + sl_distance`, `tp_level = filled_price - tp_distance` (line 20). PASS.
- Classification: `"SL" if abs(close_price - sl_level) <= abs(close_price - tp_level)` (line 23). PASS.

**Invariant 3 — Passthrough**: `api_source in ("USER", "CLOSE_OUT")` returns early (lines 12-13). PASS.

**Invariant 4 — Direction normalization**: `d = direction.strip().upper()` (line 16). Mixed-case
"buy" → "BUY" accepted; "" → no branch → `ValueError`. PASS.

**Invariant 5 — Adapter no longer forces SYSTEM→"SL"**: `_ACTIVITY_SOURCE_TO_CLOSE_SOURCE`
maps `"SYSTEM": "SYSTEM"` (line 15). Test `test_closed_trade_returns_raw_system_source`
asserts `close_source == "SYSTEM"`. PASS.

**Invariant 6 — Reconciler data flow**: `derive_close_source(closed.close_source,
closed.close_price, entry.filled_price, entry.sl_distance, entry.tp_distance,
entry.direction)` at lines 34-37; result passed as `close_source=derived_source` (line 43). PASS.

**Invariant 7 — KEYSTONE test**: `test_system_close_at_tp_level_journaled_as_tp` builds
SYSTEM-sourced ClosedTrade at `close_price=tp_level=1.1040` for BUY, asserts
`journal.result_calls[0].close_source == "TP"`. Present and passing. PASS.

**Invariant 8 — No domain→infra edge**: `reconcile_closed_trades.py` imports
`from domain.services.close_source import derive_close_source`. Direction is correct
(app → domain). `close_source.py` has no infra imports. PASS.

**Invariant 9 — Test coverage**:
- BUY→TP: parametrize row 1. PRESENT.
- BUY→SL: parametrize row 2. PRESENT.
- SELL→TP: parametrize row 3. PRESENT.
- SELL→SL: parametrize row 4. PRESENT.
- Tie→SL: parametrize row 5. PRESENT (equidistant mid-point; see S1).
- USER passthrough: parametrize row 6. PRESENT.
- CLOSE_OUT passthrough: parametrize row 7. PRESENT.
- Mixed-case accepted: parametrize row 8. PRESENT.
- Invalid direction ValueError: `test_invalid_direction_raises`. PRESENT.
- Empty direction ValueError: `test_empty_direction_raises`. PRESENT.
- Adapter SYSTEM raw: `test_closed_trade_returns_raw_system_source`. PRESENT.
- Keystone reconciler: `test_system_close_at_tp_level_journaled_as_tp`. PRESENT.

**Invariant 10 — Test run**: `102 passed, 8 skipped, 0 failed`. Baseline was 91/8;
11 new tests added. PASS.

**Invariant 11 — Code quality**: No narrating comments in any new or modified file.
No duplicated knowledge. `derive_close_source` is a single-responsibility pure function.
`_map_close_source` is the single source of truth for adapter mapping. PASS.

---

## Next Recommended

`sdd-archive`
