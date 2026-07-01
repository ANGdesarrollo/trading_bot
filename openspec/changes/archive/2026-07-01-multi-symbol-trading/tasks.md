# Tasks: Multi-Symbol Trading

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 120–180 (src) + 80–120 (tests) = ~200–300 total |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | single-pr |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | All changes (config + main + tests) | PR 1 | Single PR, size:exception pre-approved |

---

## Phase 1: Foundation — SymbolConfig value object + Config schema (config.py)

- [x] 1.1 **[RED]** In `tests/unit/test_config.py`, add failing test `test_symbol_config_is_a_frozen_dataclass` — assert `SymbolConfig("EURUSD", "CS.D.EURUSD.MINI.IP", 1000.0)` is importable and frozen (assigning an attribute raises `FrozenInstanceError`). Spec: multi-symbol config parsing.
- [x] 1.2 **[GREEN]** In `src/config.py`, define `@dataclass(frozen=True) class SymbolConfig(symbol: str, epic: str, size: float)`. Test 1.1 must pass.
- [x] 1.3 **[RED]** Add failing test `test_config_holds_symbols_tuple_and_drops_legacy_scalars` — assert `Config` has field `symbols: tuple[SymbolConfig, ...]` and no `symbol` or `trade_size` fields. Spec: multi-symbol config parsing.
- [x] 1.4 **[GREEN]** Replace `Config` fields `symbol`, `epics` (as map literal), and `trade_size` with `symbols: tuple[SymbolConfig, ...]`. Add `epics` as a `@property` returning `{s.symbol: s.epic for s in self.symbols}`. Test 1.3 must pass.

---

## Phase 2: Core — Multi-symbol load_config parsing (config.py)

- [x] 2.1 **[RED]** Add failing test `test_load_config_parses_six_symbols` — set `SYMBOLS=EURUSD,USDJPY,GBPUSD,AUDUSD,USDCAD,USDCHF` + six `EPIC_{SYMBOL}` vars; assert `len(config.symbols) == 6` and each `SymbolConfig.symbol` matches. Spec: scenario "All symbols configured correctly".
- [x] 2.2 **[RED]** Add failing test `test_per_symbol_size_overrides_global` — set `SYMBOLS=EURUSD,USDJPY`, `SIZE=1000`, `SIZE_USDJPY=2000`; assert EURUSD size is 1000, USDJPY size is 2000. Spec: scenario "Per-symbol size override".
- [x] 2.3 **[RED]** Add failing test `test_missing_epic_raises_value_error_naming_symbol` — set `SYMBOLS=EURUSD,GBPUSD`, provide `EPIC_EURUSD` but omit `EPIC_GBPUSD`; assert `ValueError` is raised and `"GBPUSD"` appears in the message. Spec: scenario "Missing epic for a listed symbol".
- [x] 2.4 **[RED]** Add failing test `test_blank_epic_raises_value_error` — set `EPIC_EURUSD=""` (blank); assert `ValueError` naming the symbol. Spec: missing-epic scenario (blank = missing).
- [x] 2.5 **[RED]** Add failing test `test_empty_symbols_raises_value_error` — set `SYMBOLS=""` or omit it; assert `ValueError` indicating no symbols configured. Spec: scenario "Empty SYMBOLS value".
- [x] 2.6 **[RED]** Add failing test `test_duplicate_symbol_raises_value_error` — set `SYMBOLS=EURUSD,EURUSD`; assert `ValueError` naming the duplicate. Spec: scenario "Duplicate symbol in list".
- [x] 2.7 **[GREEN]** Rewrite `load_config` in `src/config.py`: parse `SYMBOLS` (split, strip, deduplicate-check, empty-check); for each symbol resolve `EPIC_{SYMBOL}` (fail-fast `ValueError` if missing or blank); resolve `SIZE_{SYMBOL}` → `SIZE` → `1000`; build `SymbolConfig` per entry; assemble `Config(symbols=tuple(...), ...)`. Remove the old `symbol`/`epic`/`trade_size` parsing paths. All tests 2.1–2.6 must pass.
- [x] 2.8 Update existing tests in `tests/unit/test_config.py` that reference `config.symbol`, `config.trade_size`, or use the old `EPIC` env var (e.g. `test_default_trade_size_is_1000`, `_REQUIRED_ENV` dict) to use the new `SYMBOLS` + `EPIC_{SYMBOL}` schema. All pre-existing tests must remain green.

---

## Phase 3: Core — build_use_cases + run_forever (\_\_main\_\_.py)

- [x] 3.1 **[RED]** In `tests/unit/test_main_loop.py`, add failing test `test_build_use_cases_returns_one_per_symbol` — provide a config mock with `symbols = (SymbolConfig("EURUSD", ..., 1000), SymbolConfig("USDJPY", ..., 2000))` and `epics = {...}`; call `build_use_cases(config, http, clock, journal=FakeJournalPort())`; assert the returned list has length 2. Spec: scenario "Six symbols configured".
- [x] 3.2 **[RED]** Add failing test `test_run_forever_authenticates_once_per_boundary_with_two_symbols` — two spy use cases; assert `session.authenticate` call count equals number of boundaries fired (1), not number of symbols (2). Spec: scenario "Broker session authenticated once per boundary".
- [x] 3.3 **[RED]** Add failing test `test_run_forever_continues_remaining_symbols_after_one_raises` — three spy use cases where the second raises `RuntimeError`; assert third use case still executes and exception is logged with symbol name. Spec: scenario "One symbol raises an exception".
- [x] 3.4 **[RED]** Add failing test `test_run_forever_survives_all_symbols_raising` — all use cases raise; assert no unhandled exception escapes the boundary and the loop iterates a second boundary. Spec: scenario "All symbols raise exceptions in the same boundary".
- [x] 3.5 **[GREEN]** Rename `build_use_case` → `build_use_cases` in `src/__main__.py`: accept `config.symbols` (list), build one `RunTradingCycleUseCase` per `SymbolConfig`, return `(use_cases: list, session)`. All tests 3.1–3.2 must pass.
- [x] 3.6 **[GREEN]** Update `run_forever` in `src/__main__.py`: accept `use_cases: list`; authenticate once per boundary; iterate with `for uc in use_cases: try: uc.execute() except Exception: logger.exception("cycle failed for %s; continuing", uc._symbol)`. All tests 3.3–3.4 must pass.
- [x] 3.7 Update `tests/unit/test_main_loop.py` existing tests that reference `build_use_case` (singular) and single-use-case `run_forever` signature to use the new plural API. All pre-existing tests must remain green.

---

## Phase 4: Verification — no-touch confirmation

- [x] 4.1 Run `cd operator && .venv/bin/python3 -m pytest` and confirm all tests pass with zero failures. Result: 113 passed, 8 skipped.
- [x] 4.2 Verify that `src/infrastructure/capital/broker.py`, `src/application/trading_cycle.py`, `src/session.py`, `src/reconciler.py`, and all journal/ports files have zero `git diff` changes. Confirmed.
- [x] 4.3 Verify the `@property epics` on `Config` returns the correct `dict[str, str]` for the six-symbol scenario. Confirmed via test_config_holds_symbols_tuple_and_derived_epics.
