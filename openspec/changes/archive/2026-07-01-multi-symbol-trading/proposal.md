# Proposal: multi-symbol-trading

## Intent

### Problem
The live fade bot trades a single hard-wired symbol (EURUSD) per process. The
fade edge that was walk-forward validated on EURUSD is currently confined to one
instrument. Running the exact same frozen strategy on additional FX majors is a
low-cost way to diversify the edge across more uncorrelated (or partially
correlated) instruments, spreading opportunity across more decision boundaries
per day without changing the strategy itself.

### Why now
The codebase is ALREADY multi-symbol-capable everywhere except two files. The
broker adapter takes `epics: dict[str, str]`, every port method takes
`symbol: str`, the use case is per-symbol-parameterized at construction, and the
journal already persists a `symbol` column. The single-symbol assumption survives
only in `config.py` and `__main__.py`. This is the cheapest possible moment to
generalize — before any real deployment locks in the single-symbol env scheme.

### Success looks like
- One process runs the SAME frozen fade strategy across SIX symbols: EURUSD,
  USDJPY, GBPUSD, AUDUSD, USDCAD, USDCHF.
- Each symbol independently fetches its own candles, evaluates its own signal,
  and opens its own position, gated by its own `has_open_position` check.
- A failure on any one symbol (network, API, stale candle) does NOT stop the
  other five within the same boundary.
- Per-symbol position size is configurable but defaults so it works out of the box.
- Zero changes to the strategy, use case, broker, journal, reconciler, or ports.

## Scope

### In scope
- **`config.py`**: replace the scalar `symbol` / single `EPIC` / scalar
  `trade_size` scheme with a per-symbol config list (`symbols: list[SymbolConfig]`,
  where `SymbolConfig` carries `symbol`, `epic`, `size`). Build the `epics` dict
  from that list.
- **`__main__.py`**: `build_use_case()` -> a `build_use_cases()` that returns a
  LIST of `RunTradingCycleUseCase` (one per symbol); `run_forever()` iterates the
  list every boundary with per-symbol try/except isolation.
- **`tests/unit/test_config.py`**: new cases for multi-symbol config parsing,
  defaults, and validation errors.
- **`tests/unit/test_main_loop.py`**: new cases for multi-symbol build and
  per-symbol loop iteration with failure isolation.

### Out of scope / non-goals
- **NO strategy re-tuning per pair.** The frozen fade constants are applied
  identically to all six symbols. This is the user's explicit research choice.
- **NO parallel execution.** Symbols run sequentially per boundary (Option A).
- **NO backfill / historical replay** across the new symbols.
- **NO cross-symbol position limits** (no global max-open cap across all six).
  Each symbol self-gates against stacking; that is the only limit.
- **NO epic/size verification in code.** Confirming the 5 unverified epics and
  the per-pair contract sizing is a MANUAL deployment gate, not a code task. The
  bot must NOT place orders autonomously to discover epics.
- **NO changes** to `trading_cycle.py`, `broker.py`, `session.py`,
  `reconcile_closed_trades.py`, journal entities/adapter, ports, or `FakeBroker`.

## Approach

Adopt **Option A** from exploration: build one `RunTradingCycleUseCase` per
symbol at startup; iterate them sequentially each boundary with per-symbol
isolation. The use case class is unchanged — it already represents exactly one
symbol's cycle, so N instances is the natural expression of N symbols.

Rationale: it keeps the use case SRP-compliant (Option B would push iteration
into the use case), it needs zero downstream code changes, and sequential timing
is trivially safe (6 symbols x ~2s fetch + freshness retries is well under the
900s boundary window). Option C (parallel) buys nothing and is blocked anyway by
the non-thread-safe `CapitalSession` token mutation.

### Resolved decisions

**1. Config schema — single canonical multi-symbol config (NO backward-compat).**
This is a fresh standalone bot with no production deployment yet, so carrying a
dual code path (Option A3's `SYMBOLS_JSON`-else-fallback) would be
over-engineering for a migration that does not exist. Recommend the cleanest
single scheme:

- `SYMBOLS` env var = comma-separated list, e.g. `SYMBOLS=EURUSD,USDJPY,GBPUSD,AUDUSD,USDCAD,USDCHF`.
- Per-symbol epic resolved via an explicit, overridable mapping. Default epic is
  derived by convention `CS.D.{SYMBOL}.MINI.IP`, but each can be overridden by an
  indexed env var `EPIC_{SYMBOL}` (e.g. `EPIC_USDJPY=...`). This keeps the happy
  path a single line while allowing any pair whose epic deviates from convention
  to be corrected without code changes.
- Per-symbol size resolved the same way: default `SIZE` (scalar, applies to all)
  overridable per symbol via `SIZE_{SYMBOL}`.
- `load_config()` builds `symbols: list[SymbolConfig]` and derives
  `epics = {c.symbol: c.epic for c in symbols}`, keeping a single source of truth.
- Validation: fail fast (SystemExit) if `SYMBOLS` is empty, if any resolved epic
  is blank, or if any size is non-positive.

Exact final schema (env var names, whether epic convention default is enabled or
every epic must be explicit) is an open question deferred to the design phase.

**2. Per-symbol SIZE — configurable, defaulting to 1000 for all six.**
Ships working out of the box (all six default to `SIZE=1000`) but any pair can be
tuned via `SIZE_{SYMBOL}` without code changes. JPY pairs in particular may need a
different size, so per-symbol override must exist even though the default is uniform.

**3. Epic mapping — EURUSD confirmed, other five UNVERIFIED (manual gate).**
`EURUSD` epic = `CS.D.EURUSD.MINI.IP` is confirmed by existing test fixtures. The
convention `CS.D.{SYMBOL}.MINI.IP` is a PLACEHOLDER for USDJPY, GBPUSD, AUDUSD,
USDCAD, USDCHF and is NOT verified. These five epics MUST be validated manually
against the Capital.com demo account before live use. A wrong epic silently trades
the wrong instrument. This is a documented DEPLOYMENT GATE, not a code task — the
bot must not probe or place orders to discover epics.

**4. Per-symbol position stacking — already handled, no new work.**
`RunTradingCycleUseCase.execute()` line 42 already calls
`self._broker.has_open_position(self._symbol)` and skips placement when a position
is open. Because each symbol has its own use case instance and `has_open_position`
filters by epic, every symbol self-gates against stacking automatically. Multi-
symbol inherits this per-symbol for free. No new logic.

**5. Per-symbol failure isolation — per-symbol try/except in `run_forever()`.**
Each `use_case.execute()` is wrapped in its own try/except inside the boundary
loop, mirroring the reconciler's per-entry isolation. One symbol raising (network,
API, stale candle) logs and continues to the next symbol; the boundary is not
aborted. `session.authenticate()` runs once per boundary before the loop, as today.

**6. Out-of-sample strategy on 5 new pairs — accepted research risk, not a defect.**
The frozen fade params were walk-forward validated on EURUSD only. Applying them
unchanged to USDJPY, GBPUSD, AUDUSD, USDCAD, USDCHF is the user's explicit,
accepted research bet. Re-validating per pair is NOT this change's job. Documented
as an accepted risk so it is a conscious decision, not a silent assumption.

## PR Footprint

Small. Two production edits plus two test files:
- `operator/src/config.py` (per-symbol config)
- `operator/src/__main__.py` (`build_use_cases` returns a list; `run_forever`
  iterates with isolation)
- `tests/unit/test_config.py` (new cases)
- `tests/unit/test_main_loop.py` (new cases)

Well within a single-PR / 400-line budget. No migration, no downstream churn.

## Risks

1. **Epics unverified (5 of 6).** Wrong epic silently trades the wrong instrument.
   Mitigation: manual demo verification gate before live; convention default is a
   placeholder only.
2. **JPY sizing.** `SIZE=1000` may not mean the same notional on USDJPY as on
   EURUSD. Mitigation: per-symbol `SIZE_{SYMBOL}` override; verify contract specs
   on demo per pair before live.
3. **Rate limiting.** Six sequential candle fetches per boundary may hit an
   unknown Capital.com throttle. Mitigation: sequential (not parallel) keeps call
   rate low; validate on demo.
4. **Out-of-sample strategy.** Frozen params validated on EURUSD only; performance
   on the other five is unknown. Accepted research risk, documented, not a code
   defect.
5. **Config schema is a breaking change** to the env scheme — acceptable because
   there is no existing deployment to migrate.

## Open Questions for Design

1. Final config schema details: exact env var names; whether the
   `CS.D.{SYMBOL}.MINI.IP` convention default is enabled or every epic must be set
   explicitly via `EPIC_{SYMBOL}`; how `SizeConfig` defaults and overrides compose.
2. Exact epic placeholder values to seed for the 5 unverified pairs (or leave
   blank and force explicit config + fail-fast).
3. Whether `run_forever()` should emit a per-boundary summary (symbols evaluated,
   skipped-because-open, failed) for observability, or keep current per-call logs.
