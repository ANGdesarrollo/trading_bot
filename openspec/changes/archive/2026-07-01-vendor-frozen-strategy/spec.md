# Spec: vendor-frozen-strategy

## Purpose

Contract-preservation spec for the vendoring refactor. No new behavior is introduced.
All requirements are INVARIANTS that MUST hold after the refactor — the system behavior is otherwise identical to pre-refactor.

---

## Requirements

### Requirement: Standalone Boot — No Backend Dependency

`operator/` MUST import and start with zero dependency on the parent `backend/` repo.
No `sys.path` manipulation that reaches outside `operator/` SHALL exist anywhere in `src/`.

#### Scenario: Fresh checkout boots without parent repo

- GIVEN a fresh checkout of `operator/` in isolation (no `backend/` directory on the filesystem)
- WHEN `python -c "from src.domain.adapters.fade_strategy import FadeStrategy"` is executed
- THEN the import succeeds with exit code 0
- AND no `ModuleNotFoundError` is raised

#### Scenario: No sys.path shims remain in src/

- GIVEN the vendored state of `operator/src/`
- WHEN `grep -r "sys.path" src/` is run
- THEN the command returns no matches

#### Scenario: No research.lib imports remain in src/

- GIVEN the vendored state of `operator/src/`
- WHEN `grep -r "research\.lib" src/` is run
- THEN the command returns no matches

---

### Requirement: Frozen Constants Preserved Verbatim

The vendored copy MUST carry the exact frozen constant values established at the time of vendoring.
Any deviation constitutes an accidental edit and MUST be caught by the test suite.

| Constant | Required Value |
|---|---|
| `L_FROZEN` | `32` |
| `DIR_THRESHOLD_FROZEN` | `0.60` |
| `ATR_PERIOD` | `14` |
| `MIN_DISP_ATR` | `5.6` |
| `MIN_STRAIGHTNESS` | `0.37` |
| `SL_ATR_MULT` | `2.0` |
| `RR` | `1.0` |
| `TIME_STOP_BARS` | `48` |

#### Scenario: Constants retain exact frozen values

- GIVEN the vendored `src/domain/strategy/` package is imported
- WHEN each constant is read from the module
- THEN each constant equals the value in the table above

---

### Requirement: Signal Identity — Anti-Drift Guarantee

The vendored strategy MUST produce signals identical to the pre-vendoring source.
Both the backtest oracle (`simulate_fades`) and the live adapter (`FadeStrategy.evaluate`) MUST call the vendored code, preserving the cross-check.

#### Scenario: Anti-drift test passes with full fixture

- GIVEN `EURUSD_FIXTURE_PATH` is set to the path of the full `eurusd_15m.csv` dataset (~330K rows, 2011–2025)
- WHEN `.venv/bin/python3 -m pytest tests/integration/test_fade_strategy_anti_drift.py` is run
- THEN all assertions pass (live adapter output == backtest oracle output for every sampled window)

#### Scenario: Anti-drift test skips cleanly without fixture

- GIVEN `EURUSD_FIXTURE_PATH` is unset or the file does not exist
- WHEN `.venv/bin/python3 -m pytest tests/integration/test_fade_strategy_anti_drift.py` is run
- THEN the test is marked `SKIPPED` (not FAILED, not ERRORED)

---

### Requirement: Provenance Headers on All Vendored Files

Every file under `src/domain/strategy/` (except `__init__.py`) MUST carry a provenance header
recording the source path, git SHA, and date of vendoring.

#### Scenario: Provenance header present in each vendored file

- GIVEN the files `src/domain/strategy/runs.py`, `trajectory.py`, and `fade.py`
- WHEN each file's header is inspected
- THEN each contains a comment matching the pattern `VENDORED FROM: backend/research/lib/<file>.py @ <sha> (<date>)`

---

### Requirement: All Consumers Resolve Imports from Vendored Location

Every file that previously reached into `backend/research/lib/` via a shim MUST now import from `domain.strategy.*` instead.
`src/application/trading_cycle.py` MUST continue to resolve `SL_ATR_MULT` from the adapter re-export without any change.

#### Scenario: Full test suite passes standalone

- GIVEN `operator/` checked out in isolation, `.venv` provisioned, `EURUSD_FIXTURE_PATH` unset
- WHEN `.venv/bin/python3 -m pytest` is run
- THEN all 57+ pre-existing tests (unit + journal) pass and the anti-drift test is `SKIPPED`
- AND exit code is 0

#### Scenario: trading_cycle resolves SL_ATR_MULT unchanged

- GIVEN the adapter re-exports `SL_ATR_MULT` from the vendored `domain.strategy.fade`
- WHEN `from src.domain.adapters.fade_strategy import SL_ATR_MULT` is executed
- THEN the import succeeds and the value equals `2.0`

---

## Non-Goals

- No strategy logic, math, or constant values are changed.
- No anti-drift test logic is changed beyond import repointing.
- No versioned package or submodule is created.
- CSV fixture is NOT committed to the repo (env-var pattern only; CI wiring deferred to design).
