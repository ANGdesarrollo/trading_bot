# Apply Progress: multi-symbol-trading

**Status**: done (all tasks complete)
**Mode**: Strict TDD
**Delivery**: single-PR, size:exception (pre-approved)

## Completed Tasks

- [x] 1.1 [RED] test_symbol_config_is_a_frozen_dataclass
- [x] 1.2 [GREEN] SymbolConfig frozen dataclass in config.py
- [x] 1.3 [RED] test_config_holds_symbols_tuple_and_derived_epics
- [x] 1.4 [GREEN] Config.symbols tuple + derived epics property
- [x] 2.1 [RED] test_load_config_parses_six_symbols
- [x] 2.2 [RED] test_per_symbol_size_overrides_global
- [x] 2.3 [RED] test_missing_epic_raises_value_error_naming_symbol
- [x] 2.4 [RED] test_blank_epic_raises_value_error
- [x] 2.5 [RED] test_empty_symbols_raises_value_error
- [x] 2.6 [RED] test_duplicate_symbol_raises_value_error
- [x] 2.7 [GREEN] load_config with full multi-symbol parsing logic
- [x] 2.8 Updated existing test_config.py tests to new schema (EPIC→EPIC_EURUSD, SYMBOLS, trade_size→symbols[0].size)
- [x] 3.1 [RED] test_build_use_cases_returns_one_per_symbol
- [x] 3.2 [RED] test_run_forever_authenticates_once_per_boundary_with_two_symbols
- [x] 3.3 [RED] test_run_forever_continues_remaining_symbols_after_one_raises
- [x] 3.4 [RED] test_run_forever_survives_all_symbols_raising
- [x] 3.5 [GREEN] build_use_case → build_use_cases, returns list[RunTradingCycleUseCase]
- [x] 3.6 [GREEN] run_forever auth-once + per-symbol try/except loop
- [x] 3.7 Updated existing test_main_loop.py (build_use_case→build_use_cases, run_forever signature [list])
- [x] 4.1 Full test suite: 113 passed, 8 skipped (EURUSD_FIXTURE_PATH skips, expected)
- [x] 4.2 Zero git diff on broker.py, trading_cycle.py, session.py, reconciler.py, journal, ports
- [x] 4.3 Config.epics property verified via test_config_holds_symbols_tuple_and_derived_epics

## Files Changed
| File | Action |
|------|--------|
| operator/src/config.py | Modified — SymbolConfig, Config.symbols, Config.epics, multi-symbol load_config |
| operator/src/__main__.py | Modified — build_use_cases (list), run_forever (per-symbol loop, auth-once) |
| operator/tests/unit/test_config.py | Modified — updated _REQUIRED_ENV + all existing tests; added Phase 1+2 tests |
| operator/tests/unit/test_main_loop.py | Modified — updated imports + existing tests; added Phase 3 tests |

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1+1.2 | test_config.py | Unit | ✅ 11/11 | ✅ Written | ✅ Passed | ✅ 2 cases (frozen + fields) | ✅ Clean |
| 1.3+1.4 | test_config.py | Unit | ✅ | ✅ Written | ✅ Passed | ✅ epics property | ✅ Clean |
| 2.1-2.7 | test_config.py | Unit | ✅ | ✅ Written (6 RED before GREEN) | ✅ Passed | ✅ 6 scenarios | ✅ Clean |
| 2.8 | test_config.py | Unit | N/A (existing updated) | ✅ Approval tests updated | ✅ Passed | ➖ Migration | ✅ Clean |
| 3.1 | test_main_loop.py | Unit | ✅ 8/8 | ✅ Written | ✅ Passed | ✅ 2+3 symbol counts | ✅ Clean |
| 3.2 | test_main_loop.py | Unit | ✅ | ✅ Written | ✅ Passed (fixed boundary logic) | ✅ 2-boundary verify | ✅ Clean |
| 3.3 | test_main_loop.py | Unit | ✅ | ✅ Written | ✅ Passed | ✅ ordered execution check | ✅ Clean |
| 3.4 | test_main_loop.py | Unit | ✅ | ✅ Written | ✅ Passed | ✅ 2-boundary survive | ✅ Clean |
| 3.5+3.6 | test_main_loop.py | Unit | ✅ | ✅ Written | ✅ Passed | ✅ | ✅ Clean |
| 3.7 | test_main_loop.py | Unit | N/A (existing updated) | ✅ Updated | ✅ Passed | ➖ Migration | ✅ Clean |
| 4.1-4.3 | Full suite | — | — | — | ✅ 113 passed, 8 skipped | — | — |

## Gotchas / Deviations
- `_load_config` test helper needed a broader env-wipe to avoid leakage from EPIC_*/SIZE_*/SYMBOLS vars already set in the real environment. The new helper clears all relevant keys before patching, restoring them after.
- `isinstance(cfg.symbols[0], SymbolConfig)` fails across module reloads (different class objects). Used `__class__.__name__` check instead.
- `test_run_forever_authenticates_once_per_boundary_with_two_symbols` required a clock-based 2-boundary stop rather than a use-case-based stop, to correctly count 2 authenticate() calls.
- `run_forever` uses `getattr(use_case, "_symbol", "unknown")` to log the failing symbol name without adding a public attribute to the port contract.
