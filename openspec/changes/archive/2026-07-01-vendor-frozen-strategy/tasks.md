# Tasks: vendor-frozen-strategy

## Delivery: Single cohesive PR

All tasks ship in one PR. Sequential order enforces: package exists before consumers are repointed;
consumers are repointed before verification catches regressions.

---

## Task 1 [x] — Capture parent git SHA (prerequisite, ~1 min)

**Spec ref**: Provenance Headers requirement.
**Action**: From the root of the parent repo (`/home/alexis/Documents/Projects/TRADING_PROJECT_DEFINITIVE`),
run `git rev-parse HEAD` and record the SHA and today's date. This value is substituted into every
provenance header written in Task 2.

**Output**: `GIT_SHA` and `VENDOR_DATE` variables to be used in Task 2.
**Parallel**: Must complete before Task 2. No other dependency.

---

## Task 2 [x] — Create `src/domain/strategy/` package with vendored files

**Spec ref**: Frozen Constants Preserved Verbatim; Signal Identity; Provenance Headers; Standalone Boot.
**Parallel**: Sequential after Task 1; Tasks 3–5 can start after this completes.

### 2a — Create `src/domain/strategy/__init__.py`

Empty file (bare package marker, no re-exports).

### 2b — Vendor `runs.py` (byte-identical + provenance header)

Source: `backend/research/lib/runs.py`

Prepend header (substitute `GIT_SHA` and `VENDOR_DATE` captured in Task 1):

```
# VENDORED FROM: backend/research/lib/runs.py @ <GIT_SHA> (<VENDOR_DATE>)
# Frozen strategy — DO NOT EDIT. Re-vendor via SYNC.md when parent research changes constants.
```

Body: byte-identical copy. No other edits permitted.

### 2c — Vendor `trajectory.py` (byte-identical + provenance header)

Source: `backend/research/lib/trajectory.py`

Prepend same provenance header format, file path adjusted to `trajectory.py`.
Body: byte-identical copy. No other edits permitted.

### 2d — Vendor `fade.py` (copy + provenance header + ONLY 2 import edits)

Source: `backend/research/lib/fade_strategy.py`
Target: `src/domain/strategy/fade.py`

Prepend provenance header (3 lines — the third documents the import repoint):

```
# VENDORED FROM: backend/research/lib/fade_strategy.py @ <GIT_SHA> (<VENDOR_DATE>)
# Frozen strategy — DO NOT EDIT. Re-vendor via SYNC.md when parent research changes constants.
# Internal imports repointed research.lib.* -> domain.strategy.* (relative); no logic change.
```

Permitted edits (exactly 2 lines changed, no other modifications):

```diff
- from research.lib.runs import compute_atr, identify_runs
+ from .runs import compute_atr, identify_runs

- from research.lib.trajectory import extract_trajectory_features
+ from .trajectory import extract_trajectory_features
```

Verify all constants are present with required values:
`L_FROZEN=32`, `DIR_THRESHOLD_FROZEN=0.60`, `ATR_PERIOD=14`, `MIN_DISP_ATR=5.6`,
`MIN_STRAIGHTNESS=0.37`, `SL_ATR_MULT=2.0`, `RR=1.0`, `TIME_STOP_BARS=48`.

### 2e — Create `src/domain/strategy/SYNC.md`

Document the manual re-vendor procedure:

```markdown
# Re-vendor Procedure

Run when `backend/research/lib/` constants or logic change and you want to absorb the update.

## Steps

1. Capture parent SHA: `git -C /path/to/parent rev-parse HEAD`
2. Copy files byte-identical:
   - `runs.py` ← `backend/research/lib/runs.py`
   - `trajectory.py` ← `backend/research/lib/trajectory.py`
   - `fade.py` ← `backend/research/lib/fade_strategy.py`
3. Prepend provenance header to each file (update SHA and date).
4. Re-apply the two relative import edits in `fade.py`:
   - `from research.lib.runs import ...` → `from .runs import ...`
   - `from research.lib.trajectory import ...` → `from .trajectory import ...`
5. Verify: `EURUSD_FIXTURE_PATH=<csv> python3 -m pytest tests/integration/test_fade_strategy_anti_drift.py`
   All assertions must pass — confirms the vendored copy is behaviorally identical.
```

---

## Task 3 [x] — Update `src/domain/adapters/fade_strategy.py`

**Spec ref**: Standalone Boot; All Consumers Resolve Imports from Vendored Location.
**Parallel**: Sequential after Task 2. Independent of Tasks 4–5 (can run in any order after 2).

**Actions**:

1. Delete the `sys.path` shim block (lines ~20–22): `_BACKEND_ROOT = ...`, `if str(...) not in sys.path:`, `sys.path.append(...)`.
2. Drop the no-longer-needed `import sys` and `from pathlib import Path` if they have no other uses.
3. Replace:
   ```python
   from research.lib.fade_strategy import (ATR_PERIOD, RR, SL_ATR_MULT, _aggressive_episodes)
   from research.lib.runs import compute_atr
   ```
   With:
   ```python
   from domain.strategy.fade import (ATR_PERIOD, RR, SL_ATR_MULT, _aggressive_episodes)
   from domain.strategy.runs import compute_atr
   ```
4. Update the module docstring to reflect that the coupling is now a same-repo vendored import.
5. Confirm `SL_ATR_MULT` remains a module-level name so `trading_cycle`'s re-import survives.

---

## Task 4 [x] — Update `tests/conftest.py`

**Spec ref**: Standalone Boot; Full test suite passes standalone.
**Parallel**: Sequential after Task 2. Independent of Tasks 3 and 5.

**Actions**:

Delete the entire shim body (`import sys`, `from pathlib import Path`, `_BACKEND_ROOT = ...`,
`if str(...) not in sys.path:`, `sys.path.append(...)`). Leave the file empty or with a bare
module docstring. No `research.lib` import must remain.

---

## Task 5 [x] — Update test files: drop shims, repoint imports, wire CSV env-var

**Spec ref**: Signal Identity; Anti-drift skips cleanly; Full test suite passes standalone.
**Parallel**: Sequential after Task 2. Independent of Tasks 3 and 4.

### 5a — `tests/unit/test_fade_strategy.py`

1. Drop sys.path shim block (lines 11, 13, 19–21).
2. Replace:
   ```python
   from research.lib.fade_strategy import (ATR_PERIOD, MIN_DISP_ATR, MIN_STRAIGHTNESS, RR, SL_ATR_MULT, _aggressive_episodes, simulate_fades)
   from research.lib.runs import compute_atr
   ```
   With:
   ```python
   from domain.strategy.fade import (ATR_PERIOD, MIN_DISP_ATR, MIN_STRAIGHTNESS, RR, SL_ATR_MULT, _aggressive_episodes, simulate_fades)
   from domain.strategy.runs import compute_atr
   ```
3. Add the shared CSV resolver near the top of the file:
   ```python
   import os
   _FIXTURE_ENV = "EURUSD_FIXTURE_PATH"
   def _fixture_path():
       raw = os.environ.get(_FIXTURE_ENV)
       return Path(raw) if raw else None
   ```
4. In `_build_aggressive_window` and `test_zero_atr_returns_none`, replace the hardcoded
   `parents[3]/backend/research/data/eurusd_15m.csv` path with:
   ```python
   path = _fixture_path()
   if path is None or not path.exists():
       pytest.skip(f"{_FIXTURE_ENV} not set or file missing")
   ```
5. Confirm the 4 synthetic tests (`required_candles`, `too_few_*`, `non_aggressive`) have no CSV
   dependency and remain unconditional.

### 5b — `tests/integration/test_fade_strategy_anti_drift.py`

1. Drop sys.path shim block (lines 24, 31–33).
2. Replace the three `research.lib.*` imports with:
   ```python
   from domain.strategy.fade import simulate_fades, SL_ATR_MULT, RR
   from domain.strategy.runs import compute_atr
   from domain.strategy.trajectory import extract_trajectory_features
   ```
   (adjust to whatever names the file actually imports — keep the same identifiers, just change the source module path)
3. Replace `_CSV_PATH` construction (hardcoded parents path) with the same `_fixture_path()` resolver.
4. In the `fixture_data` pytest fixture, replace `_CSV_PATH.exists()` guard with:
   ```python
   path = _fixture_path()
   if path is None or not path.exists():
       pytest.skip(f"{_FIXTURE_ENV} not set or file missing")
   ```

---

## Task 6 [x] — Verification gate: full suite, no env var (all CSV tests SKIP)

**Spec ref**: Anti-drift skips cleanly; Full test suite passes standalone.
**Parallel**: Sequential after Tasks 3, 4, 5 complete. Must pass before Task 7.

**Actions**:

```bash
cd /home/alexis/Documents/Projects/TRADING_PROJECT_DEFINITIVE/operator
python3 -m pytest
```

**Expected**: All synthetic unit + journal tests PASS. Every CSV-dependent test (unit
`_build_aggressive_window`, `test_zero_atr_returns_none`, anti-drift) SKIPPED. Exit code 0.

**If any test FAILS** (not SKIPPED): stop, diagnose, fix before proceeding.

---

## Task 7 [x] — Verification gate: grep for residual shims (must return zero hits)

**Spec ref**: No sys.path shims remain in src/; No research.lib imports remain in src/.
**Parallel**: Can run in parallel with Task 6 after Tasks 3–5 complete.

**Actions**:

```bash
cd /home/alexis/Documents/Projects/TRADING_PROJECT_DEFINITIVE/operator
grep -r "sys.path" src/
grep -r "research\.lib" src/
```

**Expected**: Both commands return no output (zero matches). Any hit is a blocker.

---

## Task 8 [x] — KEYSTONE: anti-drift verification with `EURUSD_FIXTURE_PATH` set

**Spec ref**: Signal Identity — Anti-Drift Guarantee (primary keystone of this refactor).
**Parallel**: Sequential after Tasks 6 and 7 both pass.

```bash
cd /home/alexis/Documents/Projects/TRADING_PROJECT_DEFINITIVE/operator
EURUSD_FIXTURE_PATH=<path-to-eurusd_15m.csv> python3 -m pytest tests/integration/test_fade_strategy_anti_drift.py -v
```

**Expected**: Test PASSES (not skipped, not errored). This proves the vendored copy is
behaviorally identical to the pre-vendoring source on the full 330K-row fixture. This is the
**only gate that proves zero drift** — apply is NOT done until this passes.

---

## Task 9 [x] — Boot smoke test (standalone import, no backend)

**Spec ref**: Standalone Boot — Fresh checkout boots without parent repo.
**Parallel**: Can run alongside Task 8.

```bash
cd /home/alexis/Documents/Projects/TRADING_PROJECT_DEFINITIVE/operator
python3 -c "from src.domain.adapters.fade_strategy import FadeStrategy; print('ok')"
```

**Expected**: Prints `ok`, exit code 0. No `ModuleNotFoundError`.

---

## Dependency Order

```
Task 1
  └─→ Task 2 (2a, 2b, 2c, 2d, 2e)
        ├─→ Task 3  ─┐
        ├─→ Task 4   ├─→ Task 6 ─┐
        └─→ Task 5  ─┘           ├─→ Task 8 (KEYSTONE) ─→ done
              └──────→ Task 7 ───┘
                                  Task 9 (parallel with Task 8)
```

---

## Review Workload Forecast

| Metric | Value |
|---|---|
| New files | 5 (`__init__.py`, `runs.py`, `trajectory.py`, `fade.py`, `SYNC.md`) |
| Edited files | 4 (`fade_strategy.py` adapter, `conftest.py`, `test_fade_strategy.py`, `test_fade_strategy_anti_drift.py`) |
| Vendored lines (new) | ~366 (mechanical byte-identical copy, low review cost) |
| Edited lines | ~40 (import repoints + shim removal, high-signal diff) |
| Total | ~406 lines across all files |
| Chained PRs recommended | No — single cohesive PR (vendoring + consumers are one atomic change) |
| 400-line budget risk | Low — vendored lines are verbatim copies; reviewer effort maps to the ~40 edited lines |
| Decision needed before apply | No |
| Rollback | `git revert` — delete `domain/strategy/`, restore four shims |
