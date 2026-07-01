# Design: vendor-frozen-strategy

## Technical Approach

Vendor the 3-file transitive closure of the frozen fade strategy into a new pure-domain
package `src/domain/strategy/`, then repoint every consumer (adapter + 3 test files) from
the `research.lib.*` shim to `domain.strategy.*`. `runs.py` and `trajectory.py` are copied
byte-identical. `fade.py` (from `fade_strategy.py`) is copied verbatim EXCEPT its two
internal imports, which must resolve to the vendored siblings — this is the only permitted
edit inside a vendored file and is called out in its provenance header. Since `pythonpath =
["src"]`, all imports root at `src/` (`domain.strategy.*`, not `src.domain...`).

## Architecture Decisions

| Decision | Options | Chosen — Rationale |
|---|---|---|
| Package location | `domain/strategy/` vs `infra/` vs new top pkg | `domain/strategy/` — frozen math is pure business policy (numpy+pandas only, zero I/O). Sits one level deeper than the adapter that consumes it. |
| `fade.py` internal imports | keep `research.lib.*` (fails) vs absolute `domain.strategy.*` vs relative `.runs` | **Relative** `from .runs import ...` / `from .trajectory import ...` — keeps the package self-contained and portable; the ONLY edit vs source. Header documents it as an import-repoint, not a logic change. |
| SYNC policy location | `__init__.py` docstring vs `SYNC.md` | **`SYNC.md`** in `src/domain/strategy/` — re-vendor procedure is prose (steps + verification command), too long for a module docstring; a dedicated file is discoverable by reviewers and greppable. |
| CSV fixture | commit 15-20MB vs slice vs env-var | **Env-var `EURUSD_FIXTURE_PATH` + skip when unset** — never slice (would change the trade list and weaken the test); keeps git lean; full-history run available on demand. |

## Import Graph (verified — pure domain, no outward edges)

    domain.adapters.fade_strategy ─┬─→ domain.strategy.fade  (_aggressive_episodes, ATR_PERIOD, RR, SL_ATR_MULT)
                                   └─→ domain.strategy.runs  (compute_atr)
    domain.strategy.fade ─┬─→ domain.strategy.runs        (compute_atr, identify_runs)
                          └─→ domain.strategy.trajectory   (extract_trajectory_features)
    application.trading_cycle ─→ domain.adapters.fade_strategy (SL_ATR_MULT re-export)

No `domain → adapter` and no `domain → infra` edge. `strategy` depends only on numpy/pandas.

## Module Layout — `src/domain/strategy/`

| File | Content |
|---|---|
| `__init__.py` | Package marker. Empty (no re-exports — consumers import submodules directly, matching current usage). |
| `runs.py` | Byte-identical copy of `backend/research/lib/runs.py` + provenance header. Exports `EURUSD_PIP`, `RunRecord`, `compute_atr`, `identify_runs`. |
| `trajectory.py` | Byte-identical copy of `backend/research/lib/trajectory.py` + provenance header. Exports `SHAPE_POINTS`, `extract_trajectory_features`. |
| `fade.py` | Copy of `backend/research/lib/fade_strategy.py` + provenance header. **Only edit**: two imports repointed to `.runs` / `.trajectory`. Exports all constants (`L_FROZEN`, `DIR_THRESHOLD_FROZEN`, `ATR_PERIOD`, `MIN_DISP_ATR`, `MIN_STRAIGHTNESS`, `SL_ATR_MULT`, `RR`, `TIME_STOP_BARS`), `FadeTrade`, `_aggressive_episodes`, `simulate_fades`. |
| `SYNC.md` | Manual re-vendor procedure (see below). |

**Provenance header** (top of each `.py`, apply captures the SHA live):

    # VENDORED FROM: backend/research/lib/<file>.py @ <git-sha> (<YYYY-MM-DD>)
    # Frozen strategy — DO NOT EDIT. Re-vendor via SYNC.md when parent research changes constants.
    # fade.py only: internal imports repointed research.lib.* -> domain.strategy.* (relative); no logic change.

Apply MUST run `git rev-parse HEAD` in the parent repo at vendor time and substitute the real
SHA. Do NOT hardcode. The `<date>` is the vendor date.

## Import Repoint Diffs (before → after)

**`fade.py` (vendored — the only in-file edit):**

    - from research.lib.runs import compute_atr, identify_runs
    - from research.lib.trajectory import extract_trajectory_features
    + from .runs import compute_atr, identify_runs
    + from .trajectory import extract_trajectory_features

**`src/domain/adapters/fade_strategy.py`** — drop shim (lines 12, 15, 20-22) and repoint:

    - import sys
      from collections.abc import Sequence
      from math import isnan
    - from pathlib import Path
      ...
    - _BACKEND_ROOT = Path(__file__).parents[4] / "backend"
    - if str(_BACKEND_ROOT) not in sys.path:
    -     sys.path.append(str(_BACKEND_ROOT))
    - from research.lib.fade_strategy import (ATR_PERIOD, RR, SL_ATR_MULT, _aggressive_episodes)
    - from research.lib.runs import compute_atr
    + from domain.strategy.fade import (ATR_PERIOD, RR, SL_ATR_MULT, _aggressive_episodes)
    + from domain.strategy.runs import compute_atr

Also update the module docstring (lines 2-8): the coupling is now a same-repo vendored import,
not a cross-project sys.path shim. `SL_ATR_MULT`, `RR`, `ATR_PERIOD` remain module-level names,
so `trading_cycle`'s `from domain.adapters.fade_strategy import SL_ATR_MULT` survives unchanged.

**`tests/conftest.py`** — delete the entire shim body; file becomes a bare docstring (or is
emptied). No `research.lib` import remains anywhere.

    - import sys
    - from pathlib import Path
    - _BACKEND_ROOT = Path(__file__).parents[3] / "backend"
    - if str(_BACKEND_ROOT) not in sys.path:
    -     sys.path.append(str(_BACKEND_ROOT))

**`tests/unit/test_fade_strategy.py`** — drop shim (lines 11, 13, 19-21), repoint imports,
route CSV through the env var:

    - import sys ... _BACKEND_ROOT = ... sys.path.append(...)
    - from research.lib.fade_strategy import (ATR_PERIOD, MIN_DISP_ATR, MIN_STRAIGHTNESS, RR, SL_ATR_MULT, _aggressive_episodes, simulate_fades)
    - from research.lib.runs import compute_atr
    + from domain.strategy.fade import (ATR_PERIOD, MIN_DISP_ATR, MIN_STRAIGHTNESS, RR, SL_ATR_MULT, _aggressive_episodes, simulate_fades)
    + from domain.strategy.runs import compute_atr

**`tests/integration/test_fade_strategy_anti_drift.py`** — drop shim (lines 24, 31-33),
repoint the three `research.lib.*` imports to `domain.strategy.fade` / `.runs` / `.trajectory`,
and route `_CSV_PATH` through the env var.

## CSV Fixture Wiring

`test_fade_strategy.py` (unit) DOES need the CSV: `_build_aggressive_window` and
`test_zero_atr_returns_none` build a hardcoded `parents[3]/backend/research/data/eurusd_15m.csv`
path — that path breaks standalone. Repoint BOTH test files to the same resolver:

    import os
    _FIXTURE_ENV = "EURUSD_FIXTURE_PATH"
    def _fixture_path() -> Path | None:
        raw = os.environ.get(_FIXTURE_ENV)
        return Path(raw) if raw else None

- Unit CSV-dependent tests: at top of each, resolve path; `pytest.skip(...)` when None or
  missing. The 4 synthetic tests (`required_candles`, `too_few*`, `non_aggressive`) need NO CSV
  and always run.
- Anti-drift `fixture_data` fixture: replace `_CSV_PATH.exists()` with
  `path = _fixture_path(); if path is None or not path.exists(): pytest.skip(...)`.

## Testing Strategy

| Run | Expectation |
|---|---|
| `.venv/bin/python3 -m pytest` (no env var) | All synthetic unit + journal tests PASS; every CSV-dependent test (unit build-window, zero-atr, anti-drift) SKIPS. Exit 0. |
| `EURUSD_FIXTURE_PATH=<full csv> .venv/bin/python3 -m pytest` | Anti-drift + CSV unit tests RUN and PASS (adapter == oracle on every window). |
| Boot smoke | `python -c "from src.domain.adapters.fade_strategy import FadeStrategy"` exits 0 with no `backend/` present. |
| Grep gates | `grep -r "sys.path" src/` and `grep -r "research\.lib" src/` return no matches. |

**Refactor discipline (Strict TDD context):** this is a behavior-preserving refactor — tests
stay GREEN throughout, no red-first cycle. The anti-drift test is the safety net proving the
vendored copy is byte-identical in behavior; apply MUST run it with `EURUSD_FIXTURE_PATH` set to
PROVE zero drift before declaring done.

## Migration / Rollout

No migration. Single cohesive PR: 3 new vendored files (~366 lines, mechanical copy) + `SYNC.md`
+ `__init__.py`, and ~4 edited consumers (~40 lines of import/shim removal). Total well under the
400-line review budget; vendored lines are low-review-cost verbatim copies. Rollback = git revert
(delete `domain/strategy/`, restore the four shims).

## Open Questions

- [ ] None blocking. CI wiring of `EURUSD_FIXTURE_PATH` (secret path vs vendored full CSV) is a
      deploy-pipeline concern, out of scope for this refactor; the env-var contract is sufficient.
