# Tasks: sl-tp-relative-distance

## Review Workload Forecast

- Estimated changed lines: ~30 source + ~40 test edits = ~70 total
- Chained PRs recommended: No
- 400-line budget risk: Low
- Decision needed before apply: No

---

## Execution Notes

Strict TDD is ACTIVE. Test runner: `.venv/bin/pytest` (cwd: `capital_integration`).

Each group follows RED → GREEN → REFACTOR. Tasks within a group are sequential unless
marked `[parallel]`. Groups must execute in order — each group depends on the previous.

---

## Group 1 — Keystone RED test (Signal entity + fade producer)

These two tests must be written and confirmed RED before any production code is touched.
They fail at attribute resolution because `Signal` has no `sl_distance`/`tp_distance` yet.

### TASK-1.1 [x] Write `test_build_signal_returns_relative_distances`

- File: `tests/unit/test_fade_strategy.py`
- Add a test that calls `_build_signal(episode, atr_e)` (or drives `evaluate` on an
  aggressive window) and asserts:
  - `signal.sl_distance == pytest.approx(SL_ATR_MULT * atr_e)`
  - `signal.tp_distance == pytest.approx(RR * signal.sl_distance)`
- Run suite — test must fail (AttributeError on `sl_distance`).
- Satisfies: REQ-2 (Scenario 2.1 / 2.2)

### TASK-1.2 [x] Write `test_open_position_sends_stop_distance_not_level`

- File: `tests/unit/test_capital_broker.py`
- Build a `Signal` with `sl_distance=0.0020, tp_distance=0.0040` (will also fail at
  Signal construction once entity changes; acceptable — write it now so it gates GREEN).
- Assert `"stopDistance" in body` and `"profitDistance" in body`.
- Assert `"stopLevel" not in body` and `"profitLevel" not in body`.
- Run suite — test must fail.
- Satisfies: REQ-3 (Scenario 3.1 / 3.2)

---

## Group 2 — Signal entity GREEN

### TASK-2.1 [x] Rewrite `Signal` dataclass

- File: `src/domain/entities/signal.py`
- Replace fields `entry_reference`, `stop_loss`, `take_profit` with `sl_distance: float`
  and `tp_distance: float`.
- Replace `__post_init__` ordering invariant with:
  - `if self.sl_distance <= 0: raise ValueError("sl_distance must be > 0")`
  - `if self.tp_distance <= 0: raise ValueError("tp_distance must be > 0")`
- Keep `frozen=True, slots=True`.
- After edit: run only `tests/unit/test_signal.py` (if it exists) to confirm entity unit
  tests pass; expect other tests to go RED due to stale constructors.
- Satisfies: REQ-1 (Scenarios 1.1 / 1.2 / 1.3)

---

## Group 3 — Fade adapter GREEN

### TASK-3.1 [x] Rewrite `_build_signal` in `FadeStrategyAdapter`

- File: `src/domain/adapters/fade_strategy.py`
- Drop `entry_reference` parameter from `_build_signal` signature.
- Collapse the two direction branches into one:
  ```python
  fade = -episode.direction
  sl_dist = SL_ATR_MULT * atr_e
  tp_dist = RR * sl_dist
  direction = Direction.BUY if fade == 1 else Direction.SELL
  return Signal(direction=direction, sl_distance=sl_dist, tp_distance=tp_dist)
  ```
- Update the call site in `evaluate`: `return _build_signal(episode, atr_e)`.
- Update the inline comment at lines 51-54: remove the `entry_reference` clause;
  keep the entry-bar-not-fed-to-detector rationale.
- Run `tests/unit/test_fade_strategy.py` — TASK-1.1 must now be GREEN.
- Satisfies: REQ-2 (Scenarios 2.1 / 2.2)

---

## Group 4 — Broker POST body GREEN

### TASK-4.1 [x] Swap `stopLevel`/`profitLevel` for `stopDistance`/`profitDistance`

- File: `src/infrastructure/capital/broker.py`
- In `open_position`, replace:
  ```python
  "stopLevel": signal.stop_loss,
  "profitLevel": signal.take_profit,
  ```
  with:
  ```python
  "stopDistance": signal.sl_distance,
  "profitDistance": signal.tp_distance,
  ```
- No other lines in the method change.
- Run `tests/unit/test_capital_broker.py` — TASK-1.2 must now be GREEN.
- Satisfies: REQ-3 (Scenarios 3.1 / 3.2)

---

## Group 5 — Trading cycle log cleanup

### TASK-5.1 [x] Drop `entry_reference` from the log extra dict

- File: `src/application/trading_cycle.py`
- In `execute`, remove `entry_reference` from the `extra={}` dict passed to the
  "order placed" log call; keep `filled_price`.
- Run `tests/unit/test_trading_cycle.py` — suite must pass.
- Satisfies: REQ-1 (entity no longer has `entry_reference`); keeps log functional.

---

## Group 6 — Migrate stale existing tests

These tests went RED when `Signal` changed shape in Group 2. Fix them now.

### TASK-6.1 [x] Migrate `test_capital_broker.py` constructors

- File: `tests/unit/test_capital_broker.py`
- Replace all `Signal(entry_reference=..., stop_loss=..., take_profit=...)` calls
  with `Signal(direction=..., sl_distance=0.0020, tp_distance=0.0020)` (or values
  appropriate to each test's intent).
- Update `test_open_position_posts_correct_body`: assert `body["stopDistance"]` /
  `body["profitDistance"]` instead of `stopLevel`/`profitLevel`.
- Satisfies: REQ-3

### TASK-6.2 [x] Migrate `test_fade_strategy.py` existing assertions [parallel with 6.1]

- File: `tests/unit/test_fade_strategy.py`
- In `test_aggressive_bar_produces_valid_signal`:
  - Delete the `entry_reference == candles[-1].close` assertion.
  - Delete the BUY/SELL ordering block.
  - Replace `sl_dist = abs(signal.stop_loss - signal.entry_reference)` with
    `sl_dist = signal.sl_distance`.
  - Replace `tp_dist` derivation with `tp_dist = signal.tp_distance`.
  - Keep the `tp_dist == RR * sl_dist` check.
- Satisfies: REQ-2

### TASK-6.3 [x] Migrate `test_trading_cycle.py` `_make_signal` helper [parallel with 6.1]

- File: `tests/unit/test_trading_cycle.py`
- In `_make_signal`, swap to `sl_distance=0.0020, tp_distance=0.0020`; remove any
  `entry_reference` kwargs.
- No other assertions in this file reference the removed fields.
- Satisfies: REQ-1 (constructor compatibility)

---

## Group 7 — Anti-drift integration rename

### TASK-7.1 [x] Rename field reads in anti-drift test

- File: `tests/integration/test_fade_strategy_anti_drift.py`
- Lines ~176-177 only:
  - `actual_sl_dist = signal.sl_distance`  (was `abs(signal.stop_loss - signal.entry_reference)`)
  - `actual_tp_dist = signal.tp_distance`  (was `abs(signal.take_profit - signal.entry_reference)`)
- `expected_sl_dist`, `expected_tp_dist` expressions and the `1e-6` tolerance are
  unchanged.
- Do NOT touch the frozen research lib (`_aggressive_episodes`, `compute_atr`).
- Run the full integration test — must be GREEN.
- Satisfies: REQ-4 (Scenario 4.1)

---

## Group 8 — Full suite gate

### TASK-8.1 [x] Full suite green

- Run: `.venv/bin/pytest` from `capital_integration` root.
- All tests must pass.
- No new warnings introduced.
- Satisfies: all requirements

---

## Task Dependency Summary

```
TASK-1.1 (RED) ──┐
TASK-1.2 (RED) ──┤
                 ▼
TASK-2.1 (Signal entity) ──────────────────────────────────┐
                 ▼                                          │
TASK-3.1 (fade _build_signal) ─── GREEN 1.1               │
                 ▼                                          │
TASK-4.1 (broker POST body) ────── GREEN 1.2               │
                 ▼                                          │
TASK-5.1 (log cleanup)                                      │
                 ▼                                          │
TASK-6.1  TASK-6.2  TASK-6.3  (parallel, all after 2.1) ◄──┘
                 ▼
TASK-7.1 (anti-drift rename)
                 ▼
TASK-8.1 (full suite gate)
```
