# Verify Report: vendor-frozen-strategy

**Date**: 2026-07-01
**Verdict**: SHIP
**Summary**: 0 CRITICAL, 0 WARNING, 2 SUGGESTION. All spec invariants pass. Keystone anti-drift test passes.

---

## Completeness Table

| Task | Status | Evidence |
|---|---|---|
| Task 1 — Capture parent SHA | COMPLETE | SHA `67077c0271af0efd9cd167a1791f20d50c68bb2c` present in all provenance headers |
| Task 2 — Create `src/domain/strategy/` package | COMPLETE | 5 files exist: `__init__.py`, `runs.py`, `trajectory.py`, `fade.py`, `SYNC.md` |
| Task 3 — Update adapter (`fade_strategy.py`) | COMPLETE | sys.path shim removed; imports from `domain.strategy.*`; SL_ATR_MULT re-exported |
| Task 4 — Update `tests/conftest.py` | COMPLETE | File is empty (1 blank line); no shim |
| Task 5 — Update test files | COMPLETE | Both test files: shim removed, imports repointed, CSV resolver wired |
| Task 6 — Gate: no env var | COMPLETE | 91 passed, 8 skipped, exit 0 (verified in this run) |
| Task 7 — Grep gate | COMPLETE | Zero `sys.path` hits in src/; zero `research.lib` import hits in src/ |
| Task 8 — KEYSTONE: anti-drift | COMPLETE | 96 passed, 3 skipped — anti-drift PASSES |
| Task 9 — Boot smoke | COMPLETE | `from domain.adapters.fade_strategy import FadeStrategy` → ok |

---

## Invariant Checks

### 1. Standalone imports — zero research.lib / sys.path in src/

Grep result across `operator/src/**`:
- `sys.path` hits: **ZERO** (none in .py files)
- `import research` hits: **ZERO**
- `from research` hits: **ZERO**
- `research.lib` hits: 2 — both in allowed locations:
  - `SYNC.md` line 14–15: procedure prose (not Python, not imported)
  - `fade.py` line 3: provenance header comment documenting the import repoint (allowed per spec)

**Result: PASS**

### 2. Vendored files exist and are pure domain

All 4 Python files under `src/domain/strategy/` exist. No import from infrastructure, adapters, or any non-stdlib/numpy/pandas dependency observed. `fade.py` internal imports are relative (`.runs`, `.trajectory`).

**Result: PASS**

### 3. Provenance headers — real SHA, correct format

All three vendored `.py` files carry:
```
# VENDORED FROM: backend/research/lib/<file>.py @ 67077c0271af0efd9cd167a1791f20d50c68bb2c (2026-07-01)
# Frozen strategy — DO NOT EDIT. Re-vendor via SYNC.md when parent research changes constants.
```
`fade.py` adds a third line documenting the import repoint. SHA `67077c0271af0efd9cd167a1791f20d50c68bb2c` matches the captured parent HEAD. No placeholder.

**Result: PASS**

### 4. Byte-identical logic — constants and code

Direct comparison of vendored files against parent sources:

**runs.py**: body is byte-identical to `backend/research/lib/runs.py`. Only diffs are the 2 prepended provenance header lines.

**trajectory.py**: body is byte-identical to `backend/research/lib/trajectory.py`. Only diffs are the 2 prepended provenance header lines.

**fade.py**: body matches `backend/research/lib/fade_strategy.py` with exactly the 2 permitted import changes:
- `from research.lib.runs import compute_atr, identify_runs` → `from .runs import compute_atr, identify_runs`
- `from research.lib.trajectory import extract_trajectory_features` → `from .trajectory import extract_trajectory_features`

No other diffs found (no logic, constant, or formatting changes).

**Frozen constants verified:**

| Constant | Required | Actual | Match |
|---|---|---|---|
| `L_FROZEN` | `32` | `32` | PASS |
| `DIR_THRESHOLD_FROZEN` | `0.60` | `0.60` | PASS |
| `ATR_PERIOD` | `14` | `14` | PASS |
| `MIN_DISP_ATR` | `5.6` | `5.6` | PASS |
| `MIN_STRAIGHTNESS` | `0.37` | `0.37` | PASS |
| `SL_ATR_MULT` | `2.0` | `2.0` | PASS |
| `RR` | `1.0` | `1.0` | PASS |
| `TIME_STOP_BARS` | `48` | `48` | PASS |

**Result: PASS**

### 5. SL_ATR_MULT re-export

`trading_cycle.py` line 6: `from domain.adapters.fade_strategy import SL_ATR_MULT`.
Adapter exposes `SL_ATR_MULT` as a module-level name (imported from `domain.strategy.fade`).
Smoke check: `python3 -c "from domain.adapters.fade_strategy import SL_ATR_MULT; print(SL_ATR_MULT)"` → `2.0`.

**Result: PASS**

### 6. CSV gating

Without `EURUSD_FIXTURE_PATH`:
- `_build_aggressive_window` → SKIP
- `test_zero_atr_returns_none` → SKIP
- `fixture_data` fixture in anti-drift → SKIP (all 3 anti-drift tests skip)
- Exit code 0

With `EURUSD_FIXTURE_PATH` set:
- All CSV-dependent tests run and pass.

**Result: PASS**

### 7. Test suite results

**No env var:**
```
91 passed, 8 skipped in 0.51s
```
Exit code 0. CSV tests skip cleanly.

**With EURUSD_FIXTURE_PATH (full 330K-row fixture):**
```
96 passed, 3 skipped, 4 warnings in 80.14s
```
Exit code 0. Anti-drift test PASSES. The 3 remaining skips are ATR warm-up boundary cases documented in the test module header (expected, not regressions). The 4 warnings are `RuntimeWarning: invalid value encountered in divide` in `trajectory.py:110` — present in the parent source, not introduced by vendoring, benign (guarded by `np.where`).

**Result: PASS (KEYSTONE PASSES)**

### 8. Code quality

**SYNC policy**: `src/domain/strategy/SYNC.md` exists and documents the manual re-vendor procedure with all 5 steps including verification command.

**Comments**: Provenance headers are exactly the WHY/contract category allowed by policy (external provenance, sync contract, import repoint note). No narrating comments added.

**DRY — `_fixture_path` resolver**: [SUGGESTION-1] The resolver (`_FIXTURE_ENV`, `_fixture_path()`) is duplicated in `tests/unit/test_fade_strategy.py` and `tests/integration/test_fade_strategy_anti_drift.py`. The design spec said "same resolver" and the tasks wrote it in each file individually (Task 5a step 3, Task 5b step 3). Extraction to `conftest.py` would be the correct DRY fix — but this is a test-infrastructure concern, not a behavioral regression, and is separate from this change's scope.

---

## Findings

| ID | Severity | Description |
|---|---|---|
| S-1 | SUGGESTION | `_fixture_path()` resolver duplicated in both test files. Extract to `tests/conftest.py` as a future cleanup. Not a blocker. |
| S-2 | SUGGESTION | 4 `RuntimeWarning: invalid value encountered in divide` in `trajectory.py:110` during keystone run. Present in parent source (byte-identical copy), benign (guarded by `np.where`). Consider upstreaming a suppress-warning annotation if the noise is undesirable. |

**CRITICAL count: 0**
**WARNING count: 0**
**SUGGESTION count: 2**

---

## Verdict

**SHIP**

All 9 tasks complete, all spec invariants satisfied, keystone anti-drift test passes on the full 330K-row EURUSD fixture. The vendored package is behaviorally identical to the pre-vendoring research source. No blocking issues found.

**Next recommended**: `sdd-archive`
