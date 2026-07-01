# Archive Report: sl-tp-relative-distance

**Date**: 2026-07-01
**Status**: ARCHIVED — SHIP
**Change**: sl-tp-relative-distance

---

## Executive Summary

The `sl-tp-relative-distance` SDD change has been successfully completed, verified, and is ready for production deployment. The change replaces Signal's absolute SL/TP price levels with relative risk distances (sl_distance/tp_distance) anchored to the actual fill, fixing a structural entry-anchor misalignment between signal-bar close and real fill.

**Verdict**: PASS — SHIP (0 CRITICAL, 0 WARNING, 1 non-blocking suggestion)

---

## What Shipped

### Entity Contract
- **Signal** dataclass: replaced `entry_reference`, `stop_loss`, `take_profit` with `sl_distance: float` and `tp_distance: float`
- `__post_init__` guards: both fields must be > 0, else ValueError
- frozen=True, slots=True preserved

### Fade Adapter
- `_build_signal()`: computes `sl_dist = SL_ATR_MULT * atr_e` and `tp_dist = RR * sl_dist`
- Removed entry_reference parameter; direction inference unchanged (fade = -episode.direction)
- Comment lines 51-54 updated to remove entry_reference clause

### Broker Integration
- **open_position()** POST body: replaced `"stopLevel"` and `"profitLevel"` keys with `"stopDistance"` and `"profitDistance"`
- Values forwarded verbatim from Signal fields

### Application Log
- **trading_cycle.py**: removed `entry_reference` from log extra dict; kept `filled_price`

### Test Migration
- **test_fade_strategy.py**: migrated stale constructors to new Signal shape; rewrote assertions to use signal.sl_distance / signal.tp_distance
- **test_capital_broker.py**: updated POST body assertions; added new test_open_position_sends_stop_distance_not_level
- **test_trading_cycle.py**: updated _make_signal helper
- **test_fade_strategy_anti_drift.py**: renamed field reads only (computation unchanged)

### Anti-Drift Guarantee
- Research library (`src/domain/strategy/`) remains untouched
- Distance computation mathematically identical to pre-change backtest model
- 1e-6 tolerance preserved

---

## Verification Results

### Test Evidence
```
Platform: Python 3.12.12 / pytest-9.1.1
Runner: .venv/bin/python3 -m pytest (from operator/)
Result: 113 passed, 8 skipped in 0.59s
```

8 skipped tests are fixture-gated (EURUSD_FIXTURE_PATH / DATABASE_URL env vars absent) — expected, not regressions.

### Task Completion
All 11 implementation tasks marked [x] and verified:
- TASK-1.1 [x] — test_build_signal_returns_relative_distances (RED gate)
- TASK-1.2 [x] — test_open_position_sends_stop_distance_not_level (RED gate)
- TASK-2.1 [x] — Signal entity rewritten
- TASK-3.1 [x] — _build_signal rewritten
- TASK-4.1 [x] — broker POST body swapped
- TASK-5.1 [x] — entry_reference dropped from log extra
- TASK-6.1 [x] — test_capital_broker.py migrated
- TASK-6.2 [x] — test_fade_strategy.py migrated
- TASK-6.3 [x] — test_trading_cycle.py migrated
- TASK-7.1 [x] — anti-drift test field rename
- TASK-8.1 [x] — full suite green

### Spec Compliance
| REQ | Scenario | Status | Evidence |
|-----|----------|--------|----------|
| REQ-1 | 1.1 Valid distances accepted | PASS | 113 passing tests construct Signal with valid args |
| REQ-1 | 1.2 Zero sl_distance rejected | PASS | test_zero_sl_distance_raises_value_error PASSED |
| REQ-1 | 1.3 Negative tp_distance rejected | PASS | test_negative_tp_distance_raises_value_error PASSED |
| REQ-2 | 2.1 BUY fade distances | PASS | test_build_signal_returns_relative_distances; source confirms sl_dist = SL_ATR_MULT * atr_e |
| REQ-2 | 2.2 SELL fade distances | PASS | Same as 2.1; direction = SELL when fade == -1 |
| REQ-3 | 3.1 POST body stopDistance/profitDistance | PASS | test_open_position_sends_stop_distance_not_level PASSED |
| REQ-3 | 3.2 Distance values forwarded verbatim | PASS | body["stopDistance"] == pytest.approx(0.0020), body["profitDistance"] == pytest.approx(0.0040) |
| REQ-4 | 4.1 Live matches backtest distances | PASS | test_anti_drift_signal_matches_backtest; field rename only, computation unchanged |

### Forbidden Symbol Verification
Grep for `entry_reference|stopLevel|profitLevel|stop_loss|take_profit` in `src/`: **No matches** ✅

---

## Issues

### CRITICAL: 0
### WARNING: 0
### SUGGESTION: 1

**SUGGESTION**: `test_signal.py` should include an explicit test for Scenario 1.1 (valid Signal construction without error). Currently covered implicitly by the broader suite, but a dedicated `test_valid_distances_accepted` would pin the happy-path contract explicitly. Low priority; does not block archive or deployment.

---

## Deployment Gate — MANUAL VERIFICATION REQUIRED

**Capital.com Distance Unit Confirmation (EURUSD only)**

The specification uses distance in **price units** (not pips). This was confirmed via live demo order to Capital.com:
- BUY order: stopDistance=0.0020 → fill=1.14074 → stopLevel=1.13874 (confirmed 0.0020 = 20 pips for EURUSD)
- profitDistance=0.0040 (confirmed works as expected)

**BEFORE GOING LIVE**, verify per additional symbols:
1. Confirm Capital.com distance units match your expectations (price units vs. pips) for each tradable symbol
2. Verify Capital.com API accepts stopDistance/profitDistance parameters on open_position POST
3. Run a demo order for each new symbol to confirm distance interpretation

This is a MANUAL gate, not automated. Documented in proposal as "Open risk: pips-vs-price-units may vary per instrument; confirmed price units on EURUSD only, verify other symbols before live."

---

## Archive Artifacts

The following artifacts are now archived:
- **proposal.md** (Observation #1001) — Change rationale, Approach A selection, risk/debt tracking
- **spec.md** (Observation #1002) — Four requirements with Given/When/Then scenarios
- **design.md** (Observation #1003) — Technical design decisions, strict TDD order
- **tasks.md** (Observation #1004) — 11-task breakdown, 8 groups, single PR, ~70 lines changed
- **verify-report.md** (Observation #1008) — Verification results, test evidence, spec compliance matrix

All artifacts are stored in Engram with topic_key prefix `sdd/sl-tp-relative-distance/` for traceability.

---

## SDD Cycle Complete

- ✅ Proposal: defined scope, approach, rollback plan
- ✅ Spec: four requirements with scenarios
- ✅ Design: technical decisions and strict TDD order
- ✅ Tasks: 11-task breakdown
- ✅ Apply: all tasks [x] and verified
- ✅ Verify: PASS — SHIP verdict (113 passed, 0 CRITICAL, 0 WARNING)
- ✅ Archive: this report persisted to engram

**Ready for the next change.**

---

## Artifact Observation IDs (Traceability)

| Artifact | ID | Created | Topic Key |
|----------|-----|---------|-----------|
| Proposal | 1001 | 2026-06-30 22:13:51 | sdd/sl-tp-relative-distance/proposal |
| Spec | 1002 | 2026-06-30 22:15:18 | sdd/sl-tp-relative-distance/spec |
| Design | 1003 | 2026-06-30 22:15:49 | sdd/sl-tp-relative-distance/design |
| Tasks | 1004 | 2026-06-30 22:17:06 | sdd/sl-tp-relative-distance/tasks |
| Verify-Report | 1008 | 2026-06-30 22:26:30 | sdd/sl-tp-relative-distance/verify-report |
| Archive-Report | (this) | 2026-07-01 | sdd/sl-tp-relative-distance/archive-report |
