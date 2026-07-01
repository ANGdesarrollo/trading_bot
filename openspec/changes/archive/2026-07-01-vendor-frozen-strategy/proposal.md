# Proposal: vendor-frozen-strategy

## Intent

**Problem.** `operator/` is a standalone git repo, but `src/domain/adapters/fade_strategy.py` still imports the frozen strategy (`research.lib.*`) from the PARENT `backend/` repo via a runtime sys.path shim (`Path(__file__).parents[4] / "backend"`). When deployed standalone, `backend/` does not exist → `ModuleNotFoundError` → **the bot does not start**. The same shim is duplicated in `tests/conftest.py`, `tests/unit/test_fade_strategy.py`, and `tests/integration/test_fade_strategy_anti_drift.py`.

**Why now.** This is a release blocker, not a feature. The extraction (commit 67077c0) is incomplete: the deployable unit cannot boot without the parent tree. This must ship before any standalone deployment.

**Success.** `operator/` boots and runs with zero reference to `backend/`. The frozen strategy math lives inside the repo, byte-identical to the validated source, and the anti-drift guarantee (live path == backtest path) stays fully intact.

## Scope

### In Scope
- Vendor the 3-file transitive closure BYTE-IDENTICAL into a new `src/domain/strategy/` package: `runs.py`, `trajectory.py`, `fade.py` (~366 lines, numpy+pandas only).
- Add a provenance header to each vendored file: `VENDORED FROM: backend/research/lib/<file>.py @ <git-sha> (<date>)` — a legitimate WHY/provenance comment.
- Repoint `src/domain/adapters/fade_strategy.py` imports to `domain.strategy.*`; drop its sys.path shim; keep re-exporting `SL_ATR_MULT`.
- Remove sys.path shims and repoint imports in `tests/conftest.py`, `tests/unit/test_fade_strategy.py`, `tests/integration/test_fade_strategy_anti_drift.py`.
- Resolve the `eurusd_15m.csv` fixture reference (see Approach — CSV Fixture).
- Add a SYNC note documenting the manual re-vendor step when parent research changes constants.

### Out of Scope
- **Any change to strategy logic, constants, or math** — vendoring is a verbatim copy. Zero behavior change.
- Changing the anti-drift TEST logic beyond import/path repointing.
- The trade-journal change or any unrelated operator work.
- Publishing the strategy as a versioned package / submodule.

## Approach

**Vendor verbatim + keep the existing anti-drift test.** Copy the 3 files unchanged into `domain/strategy/`. After vendoring, BOTH `simulate_fades` (backtest oracle) and `FadeStrategy.evaluate` (live adapter) call the vendored code, so the anti-drift test still proves the adapter matches the backtest. The guarantee is preserved; the only thing "lost" is drift-vs-upstream, which is now intentional policy (the vendored copy IS the frozen truth). Provenance headers make any accidental edit visible to reviewers.

**CSV Fixture — decision.** Both tests run `simulate_fades` over the FULL dataframe and iterate ALL trades; the anti-drift test also samples non-entry windows from `_REQUIRED*3`. `eurusd_15m.csv` is ~330K rows (2011→2025, ~15-20MB). A truncated slice would change the trade list and produce a WEAKER test — so it MUST NOT be sliced. **Chosen: env-var `EURUSD_FIXTURE_PATH` + existing `pytest.skip` when absent.** The default standalone suite stays green without committing 15-20MB into git; when the env var points to the full dataset, the identical full-history anti-drift check runs unweakened. Fallback if CI must run it unconditionally: vendor the full CSV (one-time git cost). Final CI wiring deferred to design.

**Package name:** `domain/strategy/` — confirmed. Pure domain policy, one level deeper than the adapter.

## Capabilities

### New Capabilities
None. This is a structural vendoring refactor — no new spec-level behavior.

### Modified Capabilities
None. Strategy behavior and the anti-drift guarantee are unchanged at the spec level; only the source location of the frozen code moves.

## Impact

| File | Change |
|---|---|
| `src/domain/strategy/__init__.py` | New (package marker) |
| `src/domain/strategy/runs.py` | New — vendored, provenance header |
| `src/domain/strategy/trajectory.py` | New — vendored, provenance header |
| `src/domain/strategy/fade.py` | New — vendored, provenance header |
| `src/domain/adapters/fade_strategy.py` | Drop shim; repoint to `domain.strategy.*`; keep `SL_ATR_MULT` re-export |
| `tests/conftest.py` | Remove sys.path shim |
| `tests/unit/test_fade_strategy.py` | Drop own shim; repoint imports; CSV via `EURUSD_FIXTURE_PATH` |
| `tests/integration/test_fade_strategy_anti_drift.py` | Drop shim; repoint imports; CSV via `EURUSD_FIXTURE_PATH` |

No change to: `src/application/trading_cycle.py` (imports `SL_ATR_MULT` from adapter re-export), `src/config.py` (docstring only), `pyproject.toml` (numpy+pandas already declared).

**PR footprint:** ~366 vendored lines + ~40 lines of import/shim edits. Vendored code is a mechanical copy (low review cost). Single-PR — well within budget.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Vendored copy silently diverges from upstream research | Med | Provenance headers (path + SHA + date) + SYNC note documenting the manual re-vendor step |
| Anti-drift test weakened by CSV handling | Low | Env-var points at FULL dataset; never slice; skip-when-absent keeps default suite green without weakening |
| Byte-identical copy accidentally altered on paste | Low | Copy verbatim; anti-drift test + provenance header catch edits |
| Anti-drift guarantee | ZERO | Both oracle and adapter call the vendored code — the cross-check is fully preserved |

## Rollback Plan

Delete `src/domain/strategy/`, restore the sys.path shims in the adapter and three test files (revert the single PR). No data migration, no schema, no external state — revert is a clean git revert.

## Dependencies

None. `numpy` and `pandas` already declared in `pyproject.toml`.

## Success Criteria

- [ ] `operator/` imports and boots with NO reference to `backend/` (no sys.path shim anywhere).
- [ ] Vendored files are byte-identical to `backend/research/lib/*` at the recorded SHA (verified by provenance header).
- [ ] Full test suite passes standalone; anti-drift test passes when `EURUSD_FIXTURE_PATH` points to the full dataset.
- [ ] SYNC note documents the manual re-vendor step.

## Deferred to Design

- Exact CSV wiring in CI (env-var default path vs vendor-full-CSV fallback).
- SYNC note location (`domain/strategy/__init__.py` header vs a `SYNC.md`).
