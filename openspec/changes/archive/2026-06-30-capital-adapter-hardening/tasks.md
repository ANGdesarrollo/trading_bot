# Tasks: Capital Adapter Hardening

## Delivery Context

- **Delivery strategy**: single-pr
- **Chain strategy**: n/a
- **TDD mode**: STRICT — every behavioral task follows RED → GREEN
- **Test runner**: `.venv/bin/pytest` (from project root)
- **Total estimated changed lines**: ~60–80 (well under 400-line budget)

---

## Review Workload Forecast

| Dimension | Assessment |
|-----------|-----------|
| Estimated changed lines | ~60–80 |
| Files touched | 5 (config.py, __main__.py, test_config.py, test_capital_broker.py, test_capital_session.py) |
| Chained PRs recommended | No |
| 400-line budget risk | Low |
| Decision needed before apply | No |
| size:exception needed | No |

Single PR is appropriate. No further decomposition required.

---

## Task Groups

### Group 1 — URL Constants (D1)

Sequential within group; can run before or after Group 2/3 without suite breakage.

- [x] **T1.1** — Update `_DEMO_BASE_URL` in `src/config.py` (L20) from
  `https://demo-api.capital.com/api/v1` to
  `https://demo-api-capital.backend-capital.com/api/v1`.
  Update `_LIVE_BASE_URL` (L21) to `https://api-capital.backend-capital.com/api/v1`
  and append an inline `# UNVERIFIED` comment.
  _Satisfies_: Requirement "Demo Base URL Resolves to Verified Capital Host".

- [x] **T1.2** — Update the `_BASE_URL` constant in
  `tests/unit/test_capital_broker.py` (L36) to
  `https://demo-api-capital.backend-capital.com/api/v1`.
  Update the `base_url` string literal in
  `tests/unit/test_capital_session.py` (L19) to the same value.
  Run `.venv/bin/pytest tests/unit/test_capital_broker.py tests/unit/test_capital_session.py`
  — both must pass (GREEN; no prior RED because these are cosmetic string updates).
  _Satisfies_: keeps test assertions consistent with the new URL constant.

---

### Group 2 — API Key Env Var Rename (D2)

Depends on nothing. Run RED → GREEN.

- [x] **T2.1** — RED: rename `API_KEY` to `CAPITAL_API_KEY` in the three fixtures
  inside `tests/unit/test_config.py` (L42, L55, L70). Run
  `.venv/bin/pytest tests/unit/test_config.py` — expect failures because
  `config.py` still reads `API_KEY`.

- [x] **T2.2** — GREEN: in `src/config.py` change:
  - L58: `os.environ.get("API_KEY", "")` → `os.environ.get("CAPITAL_API_KEY", "")`.
  - L70: the missing-vars label tuple entry `("API_KEY", api_key)` →
    `("CAPITAL_API_KEY", api_key)`.

  Run `.venv/bin/pytest tests/unit/test_config.py` — all must pass.
  _Satisfies_: Requirement "API Key Read from CAPITAL_API_KEY".

---

### Group 3 — Default Trade Size (D3)

Depends on nothing. Run RED → GREEN.

- [x] **T3.1** — RED: add a test to `tests/unit/test_config.py` that calls
  `_load_config` with all required vars set (using `CAPITAL_API_KEY`) but no
  `SIZE` variable, and asserts `config.trade_size == 1000`. Run
  `.venv/bin/pytest tests/unit/test_config.py` — expect failure because the
  default is currently `0.01`.

- [x] **T3.2** — GREEN: in `src/config.py` L64, change the `SIZE` default from
  `"0.01"` to `"1000"`:
  `float(os.environ.get("SIZE", "0.01"))` → `float(os.environ.get("SIZE", "1000"))`.
  Run `.venv/bin/pytest tests/unit/test_config.py` — all must pass.
  _Satisfies_: Requirement "Default Trade Size Is a Valid Capital Deal Size".

---

### Group 4 — Warmup Guard Relocation (D4)

**Load-bearing.** Must run after Groups 1–3 so the suite is green before this
intentional behavior break. Sequential within the group.

- [x] **T4.1** — RED: update the existing test in `tests/unit/test_config.py`
  that asserts `WARMUP=64` passes the old burn-in validator. Change it (or
  replace it) to assert that `warmup_bars=64` is BELOW the strategy minimum and
  must cause the startup guard to raise `SystemExit` with a message containing
  "warmup" or "WARMUP_BARS".

  Also add a test asserting `warmup_bars=128` passes, and a test asserting
  the default (no `WARMUP` env var) resolves to `128`.

  Run `.venv/bin/pytest tests/unit/test_config.py` — expect failures for
  the new/updated scenarios.

- [x] **T4.2** — GREEN (config.py surgery):
  - Bump `WARMUP_BARS = 64` → `WARMUP_BARS = 128` (L23).
  - Delete `_assert_warmup_covers_strategy_burnin` (L96–L110) entirely.
  - Delete its call `_assert_warmup_covers_strategy_burnin(warmup_bars)` (L78).
  - Update the module docstring (L7–L8) to remove the sentence about startup
    validation against burn-in requirement (config is now pure data).

  Run `.venv/bin/pytest tests/unit/test_config.py` — warmup-default and
  warmup-128-passes tests must be GREEN; the warmup-64-rejected test still
  FAILS (guard does not exist yet).

- [x] **T4.3** — GREEN (move guard to composition root):
  Add a test covering `build_use_case` or a thin wrapper that invokes the
  warmup check in `src/__main__.py`. Specifically:
  - `warmup_bars=64` (below `strategy.required_candles=128`) → `SystemExit`
    with a message containing "warmup_bars" and the numeric values.
  - `warmup_bars=128` → no exception.

  Then add the guard in `src/__main__.py` inside `build_use_case`, AFTER the
  `strategy = FadeStrategy()` line (L60):

  ```python
  if config.warmup_bars < strategy.required_candles:
      raise SystemExit(
          f"warmup_bars={config.warmup_bars} < strategy requirement "
          f"{strategy.required_candles}"
      )
  ```

  Run `.venv/bin/pytest tests/unit/` — all tests must be GREEN.
  _Satisfies_: Requirement "Warmup Validator Enforces Strategy Adapter Minimum"
  (all four scenarios: rejected-64, passes-128, passes-256, default-128).

---

### Group 5 — Full Suite Verification

Depends on Groups 1–4 all being GREEN.

- [x] **T5.1** — Run the complete test suite from project root:
  `.venv/bin/pytest`
  Confirm all tests pass (baseline was 40 tests before this change; expect
  ≥40 given new tests were added in T3.1 and T4.1/T4.3).
  _Satisfies_: no regression across the full project.

---

## Execution Order

```
T1.1 → T1.2          (parallel-safe with Groups 2 and 3)
T2.1 → T2.2          (parallel-safe with Groups 1 and 3)
T3.1 → T3.2          (parallel-safe with Groups 1 and 2)
            ↓ all three groups GREEN
T4.1 → T4.2 → T4.3
            ↓
          T5.1
```

Groups 1, 2, and 3 may be applied in any order or interleaved; they touch
disjoint lines. Group 4 must follow all three because T4.1 updates fixtures
that T2.2 just fixed (same file, avoid conflicts). Group 5 is final gate.

---

## Guardrails

- `research.lib.*` — DO NOT TOUCH under any circumstances.
- `src/domain/adapters/fade_strategy.py` — read-only reference for
  `required_candles`; do not modify.
- Each sub-task ends with a pytest invocation. Do not proceed to the next task
  if the relevant suite is red (except the deliberate RED steps).
- The `# UNVERIFIED` comment on the live URL must be preserved until a live
  cutover smoke test confirms the host.
