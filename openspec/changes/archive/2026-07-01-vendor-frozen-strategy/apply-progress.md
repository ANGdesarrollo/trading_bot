# Apply Progress: vendor-frozen-strategy

## Status: DONE — all 9 tasks complete + S-1 DRY fix applied

## Git SHA captured
`67077c0271af0efd9cd167a1791f20d50c68bb2c` (2026-07-01)

## Tasks

- [x] Task 1 — Capture parent git SHA
- [x] Task 2 — Create `src/domain/strategy/` package (5 files: __init__.py, runs.py, trajectory.py, fade.py, SYNC.md)
- [x] Task 3 — Update `src/domain/adapters/fade_strategy.py` (dropped sys.path shim, repointed imports)
- [x] Task 4 — Update `tests/conftest.py` (emptied — shim removed)
- [x] Task 5 — Updated test files (unit + integration): dropped shims, repointed imports, wired CSV env-var
- [x] Task 6 — Verification gate: no env var → 91 passed, 8 skipped, exit 0
- [x] Task 7 — Grep gate: zero `sys.path` hits in src/*.py; zero `from research` / `import research` hits in src/*.py
- [x] Task 8 — KEYSTONE: with EURUSD_FIXTURE_PATH set → 96 passed, 3 skipped, exit 0 (anti-drift PASSED)
- [x] Task 9 — Boot smoke: `PYTHONPATH=src python3 -c "from domain.adapters.fade_strategy import FadeStrategy"` → ok
- [x] S-1 DRY fix — Extract `_FIXTURE_ENV`/`_fixture_path()` duplication into `tests/conftest.py` as `eurusd_fixture_path` module-scoped pytest fixture; removed from both test files

## Verification Results

### No env var
```
91 passed, 8 skipped in 0.53s
```
CSV-dependent tests (build_aggressive_window, zero_atr_returns_none, anti-drift) SKIP cleanly.

### With EURUSD_FIXTURE_PATH set
```
96 passed, 3 skipped, 4 warnings in 81.20s
```
Anti-drift test PASSES. Vendored copy is byte-identical in behavior.
3 remaining skips are ATR warm-up boundary cases documented in the test module (expected).

### Grep gates
- `grep -r "sys.path" src/ --include="*.py"` → ZERO HITS
- `grep -r "from research" src/ --include="*.py"` → ZERO HITS
- `grep -r "import research" src/ --include="*.py"` → ZERO HITS
- Note: provenance header comment in `fade.py` contains "research.lib.*" text (by design — documents the import repoint)

### S-1 DRY grep gate
- `_fixture_path` / `_FIXTURE_ENV` defined only in `tests/conftest.py` — zero hits in unit or integration test files

### Boot smoke
- `PYTHONPATH=src python3 -c "from domain.adapters.fade_strategy import FadeStrategy; print('ok')"` → ok

## Files Changed

### New files
- `operator/src/domain/strategy/__init__.py`
- `operator/src/domain/strategy/runs.py`
- `operator/src/domain/strategy/trajectory.py`
- `operator/src/domain/strategy/fade.py`
- `operator/src/domain/strategy/SYNC.md`

### Edited files
- `operator/src/domain/adapters/fade_strategy.py` — dropped sys.path shim, repointed imports, updated docstring
- `operator/src/config.py` — updated stale docstring comment (was referencing research.lib)
- `operator/tests/conftest.py` — now holds `eurusd_fixture_path` module-scoped fixture (single source of truth for CSV env-var resolution)
- `operator/tests/unit/test_fade_strategy.py` — dropped shim, repointed imports; S-1: removed `_FIXTURE_ENV`/`_fixture_path`, uses `eurusd_fixture_path` fixture via injection
- `operator/tests/integration/test_fade_strategy_anti_drift.py` — dropped shim, repointed imports; S-1: removed `_FIXTURE_ENV`/`_fixture_path`, `fixture_data` receives `eurusd_fixture_path` fixture
