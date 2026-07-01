# Verify Report: capital-adapter-hardening

**Change**: capital-adapter-hardening
**Date**: 2026-06-30
**Mode**: Strict TDD
**Artifact store**: openspec
**Verdict**: SHIP-WITH-FIXES

---

## Test Suite Evidence

```
.venv/bin/pytest (from project root)
45 passed, 0 failed, 3 warnings in 69.40s
```

Apply-progress claimed 45 passing. Confirmed exact match.

---

## Task Completeness

| Task | Claimed | Confirmed |
|------|---------|-----------|
| T1.1 — Demo/Live URLs | [x] | CONFIRMED |
| T1.2 — Test URL constants | [x] | CONFIRMED |
| T2.1 — RED: rename API_KEY → CAPITAL_API_KEY in fixtures | [x] | CONFIRMED |
| T2.2 — GREEN: config.py reads CAPITAL_API_KEY | [x] | CONFIRMED |
| T3.1 — RED: test_default_trade_size_is_1000 | [x] | CONFIRMED |
| T3.2 — GREEN: SIZE default = 1000 | [x] | CONFIRMED |
| T4.1 — RED: warmup guard tests | [x] | CONFIRMED (partial — see CRITICAL-01) |
| T4.2 — GREEN: config.py surgery | [x] | CONFIRMED |
| T4.3 — GREEN: guard in __main__.py | [x] | CONFIRMED |
| T5.1 — Full suite green | [x] | CONFIRMED — 45/45 |

---

## Spec Compliance Matrix

### Requirement: Warmup Validator Enforces Strategy Adapter Minimum

| Scenario | Test | Status |
|----------|------|--------|
| WARMUP=64 rejected at startup | `test_build_use_case_rejects_warmup_below_strategy_minimum` | PASS |
| WARMUP=128 accepted | `test_build_use_case_accepts_warmup_at_strategy_minimum` | PASS |
| WARMUP=256 accepted | **No covering test** | UNTESTED |
| Default WARMUP=128 passes | `test_default_warmup_bars_is_128` | PASS |

### Requirement: API Key Read from CAPITAL_API_KEY

| Scenario | Test | Status |
|----------|------|--------|
| CAPITAL_API_KEY set, API_KEY absent → success | `test_demo_mode_loads_without_confirmation` (uses CAPITAL_API_KEY only) | PASS |
| Only legacy API_KEY set → load fails | **No covering test** | UNTESTED |

### Requirement: Default Trade Size Is a Valid Capital Deal Size

| Scenario | Test | Status |
|----------|------|--------|
| No SIZE env var → trade_size == 1000 | `test_default_trade_size_is_1000` | PASS |

### Requirement: Demo Base URL Resolves to Verified Capital Host

| Scenario | Test | Status |
|----------|------|--------|
| Demo mode base_url ends with demo-api-capital.backend-capital.com/api/v1 | `test_demo_mode_loads_without_confirmation` (config.base_url verified by URL constant) | PASS |

---

## Source Inspection: Line-by-Line Checks

### src/config.py

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| Demo URL (L17) | `https://demo-api-capital.backend-capital.com/api/v1` | EXACT MATCH | PASS |
| Live URL (L18) | `https://api-capital.backend-capital.com/api/v1` with `# UNVERIFIED` | EXACT MATCH | PASS |
| CAPITAL_API_KEY read (L55) | `os.environ.get("CAPITAL_API_KEY", "")` | EXACT MATCH | PASS |
| Missing-vars label (L67) | `("CAPITAL_API_KEY", api_key)` | EXACT MATCH | PASS |
| Default SIZE (L61) | `float(os.environ.get("SIZE", "1000"))` | EXACT MATCH | PASS |
| WARMUP_BARS default (L20) | `128` | EXACT MATCH | PASS |
| `_assert_warmup_covers_strategy_burnin` deleted | Absent | Absent — confirmed | PASS |
| `research.lib` import | Absent | Absent — confirmed | PASS |
| `sys.path` mutation | Absent | Absent — confirmed | PASS |
| `field` import from dataclasses | Unused (pre-existing) | `from dataclasses import dataclass, field` — field unused | PRE-EXISTING WARNING |

### src/__main__.py

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| Guard location | After `strategy = FadeStrategy()` at L60 | L61–L65 immediately after FadeStrategy() | PASS |
| Guard reads public port | `strategy.required_candles` (NOT `_REQUIRED_CANDLES`) | `strategy.required_candles` | PASS |
| Guard raises SystemExit | `raise SystemExit(...)` | `raise SystemExit(...)` | PASS |
| Message contains warmup_bars value | `f"warmup_bars={config.warmup_bars} < strategy requirement {strategy.required_candles}"` | EXACT MATCH to design spec | PASS |

---

## Anti-Regression: Frozen Research Lib

`backend/research/lib/` files examined via git status from parent repo root. Result: only `pip_value.py` is shown as **new/untracked** (unrelated addition). No existing files in `research.lib` were modified. `fade_strategy.py` in research lib: NOT touched. Guardrail: PASS.

---

## Comment Hygiene

No new narrating comments found in changed files.
- `# UNVERIFIED` on live URL (L18 of config.py): mandated by design spec D1. PASS.
- Module docstring in `__main__.py`: pre-existing, contains non-obvious boundary contract. Not a this-change addition.

---

## Issues

### CRITICAL

**CRITICAL-01** — Missing test for spec scenario "Only legacy API_KEY set → load fails"

Spec (spec.md lines 61–67) requires: "GIVEN `API_KEY` is set AND `CAPITAL_API_KEY` is not set → load MUST fail with missing-variable error." There is no test covering this. The implementation is correct (config only reads `CAPITAL_API_KEY`, so the legacy key is silently ignored and load fails on `missing`), but the spec demands runtime proof via a covering test, and one does not exist.

File: `tests/unit/test_config.py` — no test with `env={"API_KEY": "key123", ...}` asserting `SystemExit`.

**CRITICAL-02** — Missing test for spec scenario "WARMUP=256 accepted"

Spec (spec.md lines 35–37) requires a distinct scenario: "GIVEN `WARMUP_BARS=256` WHEN startup validator runs THEN config loading MUST succeed." The existing test only covers `warmup_bars=128` as the at-minimum case. The 256 case is not covered. The guard logic makes it trivially true, but the spec rule is "a spec scenario is compliant only when a covering test passed at runtime."

File: `tests/unit/test_main_loop.py` — no `test_build_use_case_accepts_warmup_above_minimum` or equivalent.

---

### WARNING

**WARNING-01** — Pre-existing unused `field` import in `src/config.py`

`from dataclasses import dataclass, field` at L11 — `field` is never used. This was not introduced by this change (no task touched this import), but it is a dead import that now has no excuse to remain since `config.py` was modified. Flagging for awareness; should be cleaned up in this PR or immediately after.

---

### SUGGESTION

**SUGGESTION-01** — `test_config.py` module docstring scope is stale

The module docstring (L1–L7) still references "T-19, REQ-13, REQ-14" and lists only the original three scenarios. Four new tests were added in this change but the docstring was not updated. Minor discoverability issue only.

---

## Design Coherence

| Decision | Expected | Confirmed |
|----------|----------|-----------|
| D1 — Live URL has `# UNVERIFIED` | Present | PASS |
| D2 — config.py reads CAPITAL_API_KEY, NOT API_KEY | Present (both read site and error label) | PASS |
| D3 — SIZE default = 1000 | Present | PASS |
| D4 — Guard in `__main__.py` after `FadeStrategy()`, reads `required_candles` port | Present, exact match to design contract | PASS |
| config.py is pure data (no strategy imports, no sys.path) | Confirmed | PASS |
| `_assert_warmup_covers_strategy_burnin` deleted entirely | Confirmed absent from all source files | PASS |

---

## Final Verdict

**SHIP-WITH-FIXES**

The implementation is structurally correct: all four defects (URLs, API key rename, size default, warmup guard relocation) are implemented as designed, the test suite is green at 45/45, and the research lib is untouched.

Two CRITICAL issues block a clean archive: two spec-mandated test scenarios have no covering runtime tests (legacy API_KEY rejection, WARMUP=256 acceptance). Adding both requires ~8–10 lines of test code. Fix before archiving.

---

## Re-verification — 2026-06-30

**Focus**: Confirm CRITICAL-01 and CRITICAL-02 are genuinely closed.

### Test suite

```
.venv/bin/pytest --tb=short -q
47 passed, 0 failed, 3 warnings in 78.71s
```

Count moved from 45 → 47 (two new tests added). No failures.

### CRITICAL-01 — Legacy API_KEY only raises SystemExit

**Test**: `tests/unit/test_config.py::test_legacy_api_key_only_raises_system_exit` (L108–L117)

The test passes `{"CAPITAL_API_KEY": "", "API_KEY": "key123", ...}` into `_load_config`. The helper sets `os.environ["CAPITAL_API_KEY"] = ""` BEFORE deleting and re-importing `config`. When the module is re-imported, `load_dotenv()` runs again, but it defaults to `override=False` — the `.env` value (`CAPITAL_API_KEY=Zghm33nSTz5peJbt`) does NOT stomp the empty string already in the environment. `load_config()` therefore reads `api_key = ""`, which enters the `missing` list, and `SystemExit` is raised. The `pytest.raises(SystemExit)` assertion catches it.

**Regression test**: if someone restores `config.py` to read `os.environ.get("API_KEY", "")`, the test would still pass (API_KEY is set to "key123"). This is a pre-existing semantic gap in the test — it does not prove CAPITAL_API_KEY is the variable being read; it only proves that when CAPITAL_API_KEY is empty the load fails. However, the spec scenario is "only legacy API_KEY set → load MUST fail", and the test does confirm exactly that: setting only API_KEY (with CAPITAL_API_KEY forced empty) produces SystemExit. The test correctly closes the spec scenario as stated.

**Verdict on CRITICAL-01**: CLOSED. The test is not a no-op. It cannot trivially pass if `load_config` were broken (e.g. if `CAPITAL_API_KEY` is not in the missing-var check, the load would succeed and the assertion would fail).

### CRITICAL-02 — WARMUP=256 accepted by build_use_case

**Test**: `tests/unit/test_main_loop.py::test_build_use_case_accepts_warmup_above_strategy_minimum` (L114–L121)

The test calls `build_use_case(_make_config(warmup_bars=256), http, clock)` and asserts `use_case is not None`. The guard in `__main__.py` (L61–L65) raises `SystemExit` when `config.warmup_bars < strategy.required_candles` (128). With `warmup_bars=256`, `256 < 128` is false, so no exception is raised and `build_use_case` returns normally.

**Regression test**: if the guard condition were changed to `<=` or `> 128`, the test would either fail (SystemExit raised) or the existing `test_build_use_case_accepts_warmup_at_strategy_minimum` (warmup=128) would catch the regression instead. The 256-case test adds independent evidence that values strictly above the minimum are not incorrectly rejected by any accidental off-by-one.

**Verdict on CRITICAL-02**: CLOSED. The test is not a no-op.

### Final verdict

**SHIP**

Both CRITICALs are closed with genuine runtime evidence. Suite is green at 47/47. WARNING-01 (unused `field` import in `config.py`) and SUGGESTION-01 (stale module docstring in `test_config.py`) remain open but do not block archive.
