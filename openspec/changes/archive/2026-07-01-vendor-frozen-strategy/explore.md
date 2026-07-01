# Exploration: vendor-frozen-strategy

## Current State

`operator/` is an independent git repo (extracted at commit 67077c0, git-ignored from the parent). However, `operator/src/domain/adapters/fade_strategy.py` imports strategy code from the PARENT `backend/` repo via a runtime sys.path shim:

```python
_BACKEND_ROOT = Path(__file__).parents[4] / "backend"
sys.path.append(str(_BACKEND_ROOT))
from research.lib.fade_strategy import ATR_PERIOD, RR, SL_ATR_MULT, _aggressive_episodes
from research.lib.runs import compute_atr
```

As a standalone deployment, `backend/` does not exist → `ModuleNotFoundError` → **the bot does not start**. Release blocker.

The same cross-repo coupling appears in three more locations:
- `tests/conftest.py` — adds `backend/` to sys.path for all tests
- `tests/unit/test_fade_strategy.py` — its OWN `_BACKEND_ROOT` shim + direct `research.lib.*` imports + reads `eurusd_15m.csv`
- `tests/integration/test_fade_strategy_anti_drift.py` — its OWN shim + all `research.lib.*` imports + reads `eurusd_15m.csv`

`src/application/trading_cycle.py` imports `SL_ATR_MULT` from `domain.adapters.fade_strategy` (a re-export), NOT directly from `research.lib`. If the adapter keeps re-exporting `SL_ATR_MULT`, that import survives the refactor UNCHANGED.

`src/config.py` does NOT import `research.lib` — only a docstring mentions the constants by name. No code change.

## Transitive Dependency Closure

The adapter uses: `ATR_PERIOD`, `RR`, `SL_ATR_MULT`, `_aggressive_episodes` (from `fade_strategy.py`) and `compute_atr` (from `runs.py`).

`_aggressive_episodes` internally calls `identify_runs` (runs.py), `extract_trajectory_features` (trajectory.py), and constants `L_FROZEN`, `DIR_THRESHOLD_FROZEN`, `MIN_DISP_ATR`, `MIN_STRAIGHTNESS`.

Full closure — THREE self-contained files, numpy+pandas only (~366 lines):

1. `backend/research/lib/runs.py` (~95 lines) — `RunRecord`, `EURUSD_PIP`, `compute_atr`, `identify_runs`
2. `backend/research/lib/trajectory.py` (~135 lines) — `SHAPE_POINTS`, `_theil_sen_slope`, `_normalized_path`, `extract_trajectory_features`
3. `backend/research/lib/fade_strategy.py` (~136 lines) — 8 frozen constants (`L_FROZEN`, `DIR_THRESHOLD_FROZEN`, `ATR_PERIOD`, `MIN_DISP_ATR`, `MIN_STRAIGHTNESS`, `SL_ATR_MULT`, `RR`, `TIME_STOP_BARS`), `FadeTrade`, `_aggressive_episodes`, `simulate_fades`

External deps: `numpy`, `pandas` — both already in `operator/pyproject.toml`. No dependency change.

## Target Module Location

Recommended: `src/domain/strategy/` package (`__init__.py`, `runs.py`, `trajectory.py`, `fade.py`). This is pure domain policy (decides whether to trade) — it belongs one level deeper than the adapter in the domain layer, consistent with hexagonal architecture. Alternatives (`src/vendor/`, `domain/adapters/strategy/`) either break the Clean Architecture convention or mislabel domain policy as adapter concerns.

## Consumers Whose Import Must Change

| File | Change |
|------|--------|
| `src/domain/adapters/fade_strategy.py` | drop sys.path shim; repoint to `domain.strategy.fade` + `domain.strategy.runs`; keep re-exporting `SL_ATR_MULT` |
| `src/application/trading_cycle.py` | **No change** — imports `SL_ATR_MULT` from the adapter re-export |
| `tests/conftest.py` | remove shim entirely |
| `tests/unit/test_fade_strategy.py` | drop its own shim; repoint imports; resolve CSV path |
| `tests/integration/test_fade_strategy_anti_drift.py` | drop shim; repoint imports; resolve CSV path |

## Anti-Drift Guarantee

Today the anti-drift test compares `simulate_fades` (backtest oracle) vs `FadeStrategy.evaluate` (live adapter). After vendoring, BOTH call the vendored code — the test still proves the adapter's causal-windowing logic matches the batch backtest. That guarantee is fully PRESERVED. The only thing lost is detecting drift between the vendored copy and upstream parent code — which becomes a POLICY matter (the vendored copy IS the frozen truth). A provenance comment header (source path + git SHA + date) gives reviewers a clear signal if someone edits the vendored files.

## CSV Fixture — Critical Finding

Both tests call `simulate_fades(df, ...)` over the FULL dataframe and iterate ALL resulting trades. The anti-drift test also samples non-entry windows starting at `_REQUIRED*3`. `backend/research/data/eurusd_15m.csv` is ~330K+ rows spanning 2011→2025 (~15-20MB). A truncated slice would change the trade list, ATR warm-up, and sampling — producing a DIFFERENT, WEAKER test. The anti-drift guarantee CANNOT be preserved with a small slice. Both tests already `pytest.skip()` when the CSV is absent.

## pyproject.toml

`numpy>=1.26.0` and `pandas>=2.2.0` already declared. No dependency change.

## Open Questions for Propose

1. CSV fixture strategy: vendor full CSV vs env-var + skip. Must NOT weaken anti-drift.
2. Provenance comment format (source path + git SHA + date).
3. Package name (`domain/strategy/`).
4. Long-term sync policy when parent research changes constants.

## Ready for Proposal

Yes. Scope: 3 vendored files + 1 adapter repoint + 3 test-file updates + CSV fixture resolution + provenance headers + sync-policy note. Byte-identical vendoring — NO strategy logic change.
