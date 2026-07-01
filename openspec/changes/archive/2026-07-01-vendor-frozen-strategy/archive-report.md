# Archive Report: vendor-frozen-strategy

**Date**: 2026-07-01
**Status**: COMPLETE
**Verdict**: SHIP — all tasks verified, change ready for production closure

---

## Executive Summary

The `vendor-frozen-strategy` change is fully implemented, verified SHIP (0 CRITICAL / 0 WARNING), and ready for archive. The operator repo is now self-contained: 3 frozen-strategy files are vendored into `src/domain/strategy/`, all sys.path shims coupling the operator to the parent backend repo have been removed, and the anti-drift keystone test passes (96 passed, 3 skipped with full fixture). The operator boots standalone without any reference to `backend/`.

---

## What Was Shipped

### Scope Delivered

| Item | Status |
|------|--------|
| Vendor `runs.py`, `trajectory.py`, `fade.py` into `src/domain/strategy/` with provenance headers | COMPLETE |
| Freeze parent SHA `67077c0` in all headers (captured 2026-07-01) | COMPLETE |
| Drop sys.path shims from adapter + 3 test files | COMPLETE |
| Repoint all imports from `research.lib.*` to `domain.strategy.*` | COMPLETE |
| Wire CSV fixture resolution via `EURUSD_FIXTURE_PATH` env-var | COMPLETE |
| Create `SYNC.md` documenting manual re-vendor procedure | COMPLETE |
| Pass anti-drift keystone with full 330K-row fixture | COMPLETE |
| Zero regression in synthetic unit tests (no CSV dependency) | COMPLETE |
| Apply S-1 DRY fix: extract `_fixture_path()` resolver to `tests/conftest.py` | COMPLETE |

### Verification State (Verdict: SHIP)

- **9/9 tasks complete** (all marked `[x]` in tasks.md)
- **Spec invariants**: 7/7 pass (standalone boot, frozen constants, anti-drift guarantee, provenance headers, consumer imports, CSV gating, test suite)
- **Test results**:
  - Without `EURUSD_FIXTURE_PATH`: **91 passed, 8 skipped** (exit 0)
  - With `EURUSD_FIXTURE_PATH`: **96 passed, 3 skipped** (keystone PASSES; 4 runtime warnings benign/inherited from parent)
- **Findings**: 0 CRITICAL, 0 WARNING, 2 SUGGESTION (duplicate fixture resolver — FIXED in S-1)
- **Anti-drift guarantee**: FULLY PRESERVED (both backtest oracle and live adapter call the vendored code)

---

## Artifacts Archived

All artifacts from the change folder are preserved in the archive:

| Artifact | Location | Purpose |
|----------|----------|---------|
| proposal.md | archive/2026-07-01-vendor-frozen-strategy/proposal.md | Business case: release blocker fix, scope, approach, risks, rollback plan |
| spec.md | archive/2026-07-01-vendor-frozen-strategy/spec.md | Requirements: 5 invariants (standalone boot, frozen constants, anti-drift, provenance, imports), 1 non-goal, all met |
| design.md | archive/2026-07-01-vendor-frozen-strategy/design.md | Technical decisions: package location, import rewrites, CSV env-var, SYNC policy, test strategy |
| tasks.md | archive/2026-07-01-vendor-frozen-strategy/tasks.md | 9 tasks (all complete), dependency order, review forecast (~406 lines: 366 vendored + 40 edited) |
| explore.md | archive/2026-07-01-vendor-frozen-strategy/explore.md | Context: current sys.path coupling, transitive closure analysis, CSV critical finding, pyproject unchanged |
| apply-progress.md | archive/2026-07-01-vendor-frozen-strategy/apply-progress.md | Task completion log, verification results, changed files manifest, S-1 DRY fix applied |
| verify-report.md | archive/2026-07-01-vendor-frozen-strategy/verify-report.md | Verdict SHIP, completeness table (9/9), invariant checks (7/7 pass), byte-identical verification, constants table, findings (2 SUGGESTION) |
| archive-report.md | archive/2026-07-01-vendor-frozen-strategy/archive-report.md | This document |

---

## Implementation Summary

### Files Created (5)

```
operator/src/domain/strategy/__init__.py
  → Package marker, empty

operator/src/domain/strategy/runs.py
  → Byte-identical copy of backend/research/lib/runs.py
  → Provenance header with SHA 67077c0, date 2026-07-01
  → Exports: EURUSD_PIP, RunRecord, compute_atr, identify_runs

operator/src/domain/strategy/trajectory.py
  → Byte-identical copy of backend/research/lib/trajectory.py
  → Provenance header with SHA 67077c0, date 2026-07-01
  → Exports: SHAPE_POINTS, extract_trajectory_features

operator/src/domain/strategy/fade.py
  → Copy of backend/research/lib/fade_strategy.py with 2 import edits
  → Repointed: research.lib.runs → .runs, research.lib.trajectory → .trajectory
  → Provenance header documents the import repoint
  → Exports: L_FROZEN, DIR_THRESHOLD_FROZEN, ATR_PERIOD, MIN_DISP_ATR, MIN_STRAIGHTNESS, SL_ATR_MULT, RR, TIME_STOP_BARS, FadeTrade, _aggressive_episodes, simulate_fades

operator/src/domain/strategy/SYNC.md
  → Re-vendor procedure (5 steps: capture SHA, copy files, prepend headers, re-apply imports, verify)
  → Verification command: EURUSD_FIXTURE_PATH=<csv> python3 -m pytest tests/integration/test_fade_strategy_anti_drift.py
```

### Files Modified (5)

```
operator/src/domain/adapters/fade_strategy.py
  → Removed sys.path shim (import sys, from pathlib import Path, _BACKEND_ROOT, sys.path.append)
  → Repointed imports: research.lib.fade_strategy → domain.strategy.fade, research.lib.runs → domain.strategy.runs
  → Kept SL_ATR_MULT as module-level re-export (for trading_cycle.py consumer)
  → Updated docstring (from cross-project shim to same-repo vendored import)

operator/tests/conftest.py
  → Removed sys.path shim body (import sys, from pathlib import Path, _BACKEND_ROOT, sys.path.append)
  → File now empty (1 blank line) — pure fixture placeholder
  → Added eurusd_fixture_path module-scoped pytest fixture (S-1 DRY fix)

operator/tests/unit/test_fade_strategy.py
  → Removed sys.path shim (lines 11, 13, 19–21)
  → Repointed imports: research.lib → domain.strategy
  → Added CSV resolver (originally _FIXTURE_ENV / _fixture_path, extracted to conftest via S-1)
  → Synthetic tests (required_candles, too_few_*, non_aggressive) remain unconditional; CSV tests skip when env-var unset

operator/tests/integration/test_fade_strategy_anti_drift.py
  → Removed sys.path shim (lines 24, 31–33)
  → Repointed imports: research.lib.fade/runs/trajectory → domain.strategy.*
  → Fixture wired to eurusd_fixture_path (S-1 DRY fix); fixture_data fixture skips cleanly when env-var unset

operator/src/config.py
  → Updated stale docstring comment (was referencing research.lib constants by name)
  → No code change
```

---

## SDD Cycle Complete

| Phase | Status | Verdict |
|-------|--------|---------|
| Exploration | COMPLETE | Ready for proposal |
| Proposal | COMPLETE | Scope clear, approach solid, risks documented |
| Spec | COMPLETE | 5 invariants defined, all verified ✓ |
| Design | COMPLETE | Technical decisions locked, import graph verified |
| Tasks | COMPLETE | 9 tasks sequenced, dependency graph accurate |
| Apply | COMPLETE | All tasks shipped, S-1 DRY fix applied |
| Verify | COMPLETE | Verdict SHIP (0 CRITICAL, 0 WARNING) |
| Archive | COMPLETE | Change moved to archive, audit trail preserved |

---

## Next Recommended

None. The `vendor-frozen-strategy` change is complete and archived. The operator repo now boots standalone. All release blockers have been resolved.

---

**Archive Timestamp**: 2026-07-01 at archive creation
**Change Name**: vendor-frozen-strategy
**Archived to**: operator/openspec/changes/archive/2026-07-01-vendor-frozen-strategy/
