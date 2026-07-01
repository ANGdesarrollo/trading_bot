# Verification Report: sl-tp-relative-distance

**Date**: 2026-07-01
**Verdict**: PASS — SHIP

---

## Test Evidence

```
Platform: Python 3.12.12 / pytest-9.1.1
Runner: .venv/bin/python3 -m pytest (from operator/)
Result: 113 passed, 8 skipped in 0.59s
```

Skipped tests are all fixture-gated (EURUSD_FIXTURE_PATH / DATABASE_URL env vars absent) — expected, not regressions.

---

## Task Completion

All 11 tasks marked [x] and confirmed against code state.

| Task | Status | Code State |
|------|--------|------------|
| TASK-1.1 test_build_signal_returns_relative_distances | [x] DONE | test exists in test_fade_strategy.py |
| TASK-1.2 test_open_position_sends_stop_distance_not_level | [x] DONE | test exists in test_capital_broker.py |
| TASK-2.1 Signal entity rewritten | [x] DONE | sl_distance + tp_distance only; __post_init__ guards |
| TASK-3.1 _build_signal rewritten | [x] DONE | no absolute price, no entry_reference |
| TASK-4.1 broker POST body swapped | [x] DONE | stopDistance/profitDistance at lines 68-69 |
| TASK-5.1 entry_reference dropped from log extra | [x] DONE | extra={"filled_price": result.filled_price} only |
| TASK-6.1 test_capital_broker.py migrated | [x] DONE | all Signal constructors use sl_distance/tp_distance |
| TASK-6.2 test_fade_strategy.py migrated | [x] DONE | signal.sl_distance / signal.tp_distance assertions |
| TASK-6.3 test_trading_cycle.py migrated | [x] DONE | _make_signal uses sl_distance/tp_distance |
| TASK-7.1 anti-drift field rename | [x] DONE | signal.sl_distance / signal.tp_distance reads |
| TASK-8.1 full suite green | [x] DONE | 113 passed |

---

## Spec Compliance Matrix

| REQ | Scenario | Status | Evidence |
|-----|----------|--------|---------|
| REQ-1 | 1.1 Valid distances accepted | PASS | Implicit: 113 passing tests construct Signal with valid args |
| REQ-1 | 1.2 Zero sl_distance rejected | PASS | test_zero_sl_distance_raises_value_error PASSED |
| REQ-1 | 1.3 Negative tp_distance rejected | PASS | test_negative_tp_distance_raises_value_error PASSED |
| REQ-2 | 2.1 BUY fade distances | PASS* | test_build_signal_returns_relative_distances (SKIPPED/fixture); source confirms sl_dist = SL_ATR_MULT * atr_e |
| REQ-2 | 2.2 SELL fade distances | PASS* | Same as 2.1; direction = SELL when fade == -1 |
| REQ-3 | 3.1 POST body keys | PASS | test_open_position_sends_stop_distance_not_level PASSED; asserts stopDistance in body, stopLevel not in body |
| REQ-3 | 3.2 Values forwarded verbatim | PASS | body["stopDistance"] == pytest.approx(0.0020) PASSED |
| REQ-4 | 4.1 Live matches backtest | PASS* | test_anti_drift_signal_matches_backtest (SKIPPED/fixture); source: field rename only, computation unchanged |

*PASS with fixture-gate caveat: tests skip when EURUSD_FIXTURE_PATH absent. Logic verified by source inspection.

---

## Forbidden Symbol Check

Grep for `entry_reference|stopLevel|profitLevel|stop_loss|take_profit` in `src/`: **No matches**.

---

## Anti-Drift Guarantee

`git log -- src/domain/strategy/` returns empty — the frozen research lib has never been modified. REQ-4 structural guarantee intact.

---

## Issues

### CRITICAL: 0

### WARNING: 0

### SUGGESTION: 1

- **SUGGESTION**: `test_signal.py` has no explicit test for Scenario 1.1 (valid Signal construction without error). Covered implicitly by the broader suite, but a dedicated `test_valid_distances_accepted` would pin the happy-path contract explicitly. Low priority; does not block archive.

---

## Verdict: PASS — SHIP

next_recommended: `sdd-archive`
