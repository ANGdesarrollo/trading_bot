# Tasks: candle-freshness-verification

## Disambiguation (authoritative)

`freshness_max_retries = 3` → **4 total fetches** (initial + 3 retries).
`clock.sleep` is called between attempts → **up to 3 sleeps** (attempts_made - 1).
The for-loop uses `range(freshness_max_retries + 1)` (indices 0–3).
All test assertions MUST reflect these counts.

---

## Review Workload Forecast

| Metric | Estimate |
|---|---|
| Source lines changed | ~65 (config ~8, trading_cycle ~25, __main__ ~5, fake_clock ~3) |
| Test lines changed | ~90 (migration + 3 new scenarios) |
| Total | ~155 lines |
| Chained PRs recommended | No |
| 400-line budget risk | Low |
| Decision needed before apply | No |

---

## Task Groups

### Group 0 — Prerequisite: FakeClock.sleep must advance time

Must complete before any retry-loop task can have a meaningful RED phase.

---

#### [x] Task 0.1 — RED: write test asserting FakeClock.sleep advances _time

**Spec requirement**: Section 5 — FakeClock.sleep Advancement / Scenario 6.

**File**: `tests/unit/test_fake_clock.py` (create if absent, else add to existing clock tests)

Write one test:
```python
def test_sleep_advances_time():
    clock = FakeClock(datetime(2024, 1, 1, 0, 15, 6, tzinfo=timezone.utc))
    clock.sleep(2.0)
    assert clock.utcnow() == datetime(2024, 1, 1, 0, 15, 8, tzinfo=timezone.utc)
```
Run `.venv/bin/pytest` — must FAIL because current `sleep` does not advance `_time`.

**Sequential**: must be first.

---

#### [x] Task 0.2 — GREEN: implement FakeClock.sleep time advancement

**Spec requirement**: Section 5.

**File**: `tests/fakes/fake_clock.py`

Change `sleep` from:
```python
def sleep(self, seconds): self.sleep_calls.append(seconds)
```
to:
```python
from datetime import timedelta
def sleep(self, seconds):
    self.sleep_calls.append(seconds)
    self._time = self._time + timedelta(seconds=seconds)
```

Run suite — Task 0.1 must go GREEN. No other tests may break.

**Sequential after 0.1**.

---

### Group 1 — Config: two new fields

Parallel-safe with Group 0 (different files). Must complete before Group 2.

---

#### [x] Task 1.1 — RED: test Config defaults and env-override for freshness fields

**Spec requirement**: Section 4 / Scenario 4.

**File**: `tests/unit/test_config.py` (add to existing config tests)

Two test cases:
1. No env vars set → `config.freshness_max_retries == 3` and `config.freshness_retry_seconds == 2.0`.
2. `FRESHNESS_MAX_RETRIES=5`, `FRESHNESS_RETRY_SECONDS=1.5` set → fields equal those values.

Run suite — must FAIL (fields do not exist yet).

---

#### [x] Task 1.2 — GREEN: add freshness fields to Config

**Spec requirement**: Section 4.

**File**: `src/config.py`

Add:
```python
freshness_max_retries: int = int(os.environ.get("FRESHNESS_MAX_RETRIES", "3"))
freshness_retry_seconds: float = float(os.environ.get("FRESHNESS_RETRY_SECONDS", "2.0"))
```

Run suite — Task 1.1 must go GREEN. No other tests may break.

**Sequential after 1.1**.

---

### Group 2 — Use case: constructor + freshness gate

Depends on Group 0 (FakeClock.sleep works) and Group 1 (Config fields exist).
Internal tasks are sequential by RED → GREEN discipline.

**Keystone RED: Task 2.1 (always-stale-skip)**. This is the strongest invariant —
it forces the constructor signature, the full gate loop, `return None`, sleep count,
and WARNING log all at once. Choosing it over fresh-first-try means a single RED
test covers the entire gate contract; fresh-first-try only covers the pass-through path
and would leave the retry/skip logic untested until a later RED.

---

#### [x] Task 2.1 — RED: always-stale-skip scenario

**Spec requirement**: Section 3 / Scenario 3.

**File**: `tests/unit/test_trading_cycle.py`

Add `_make_use_case` helper that constructs `RunTradingCycleUseCase` with:
- `clock=FakeClock(seed)` where seed is `2024-01-01T00:15:06Z`
- `poll_minutes=15`
- `freshness_max_retries=3`
- `freshness_retry_seconds=2.0`

Add test `test_always_stale_skips_boundary`:
- FakeBroker returns candles where `candles[-1].timestamp` is always one period behind `expected_decision_ts`.
- Assert `execute()` returns `None`.
- Assert `len(clock.sleep_calls) == 3` (3 sleeps for 4 total fetches: sleep called between attempts).
- Assert broker's `recent_candles` was called exactly 4 times.
- Assert a WARNING was logged containing retry count and boundary timestamp.
- Assert `broker.open_position` was NOT called.

Run suite — must FAIL (constructor rejects new params / gate not implemented).

---

#### [x] Task 2.2 — GREEN: implement constructor params + freshness gate in execute()

**Spec requirement**: Sections 1, 2, 3, 4.

**Files**: `src/application/trading_cycle.py`

1. Extend `__init__` signature (append new params — do not reorder existing ones):
   ```python
   def __init__(self, broker, strategy, symbol, size, logger,
                clock: ClockPort, poll_minutes: int,
                freshness_max_retries: int, freshness_retry_seconds: float):
   ```
   Store all four as `self._clock`, `self._poll_minutes`, `self._freshness_max_retries`, `self._freshness_retry_seconds`.

2. Add freshness gate at top of `execute()`, after the has-open-position guard, before (replacing) the `recent_candles` call:
   ```python
   period_secs = self._poll_minutes * 60
   now_epoch = self._clock.utcnow().timestamp()
   boundary_epoch = now_epoch - (now_epoch % period_secs)
   expected_decision_ts = datetime.fromtimestamp(
       boundary_epoch - period_secs, tz=timezone.utc)

   for attempt in range(self._freshness_max_retries + 1):
       candles = self._broker.recent_candles(
           self._symbol, self._strategy.required_candles)
       if candles[-1].timestamp == expected_decision_ts:
           break
       if attempt < self._freshness_max_retries:
           self._clock.sleep(self._freshness_retry_seconds)
   else:
       self._logger.warning(
           "stale candle after %d retries at boundary %s; skipping",
           self._freshness_max_retries, expected_decision_ts)
       return None
   ```

3. Add required imports: `from datetime import datetime, timezone` and the `ClockPort` import.

Run suite — Task 2.1 must go GREEN.

**Sequential after 2.1**.

---

#### [x] Task 2.3 — RED+GREEN: fresh-first-try scenario

**Spec requirement**: Scenario 1.

**File**: `tests/unit/test_trading_cycle.py`

Add test `test_fresh_candle_first_try_no_sleep`:
- Seed clock at `2024-01-01T00:15:06Z` → expected_decision_ts = `2024-01-01T00:00:00Z`.
- FakeBroker returns candles with `candles[-1].timestamp == expected_decision_ts` on first call.
- Assert `clock.sleep_calls == []`.
- Assert broker's `recent_candles` called exactly once by the gate.
- Assert execute() does NOT return None (strategy evaluates normally).

Run RED (verify it fails for the right reason if gate logic has a bug), then GREEN (should pass with Task 2.2 already implemented).

**Sequential after 2.2**.

---

#### [x] Task 2.4 — RED+GREEN: stale-then-fresh scenario

**Spec requirement**: Scenario 2.

**File**: `tests/unit/test_trading_cycle.py`

Add test `test_stale_then_fresh_retries_once`:
- FakeBroker returns stale candle on first call, fresh candle on second call.
- Assert `clock.sleep_calls == [2.0]` (exactly one sleep).
- Assert broker's `recent_candles` called exactly twice.
- Assert execute() does NOT return None.

Run RED then GREEN (should pass with Task 2.2 already implemented).

**Sequential after 2.3**.

---

### Group 3 — __main__.py wiring

Depends on Group 2 (constructor signature locked). Single task.

---

#### [x] Task 3.1 — GREEN: wire new use-case params in build_use_case

**Spec requirement**: Section 4 (both fields passed from `build_use_case`).

**File**: `src/__main__.py`

In `build_use_case`, pass four new kwargs to `RunTradingCycleUseCase(...)`:
```python
clock=clock,
poll_minutes=config.poll_minutes,
freshness_max_retries=config.freshness_max_retries,
freshness_retry_seconds=config.freshness_retry_seconds,
```

No test for this task beyond the existing `test_main_loop` tests (updated in Group 4).

**Sequential after Task 2.2**.

---

### Group 4 — Test migration: align existing tests + update test_main_loop config

Depends on Groups 2 and 3. Can proceed once constructor signature and gate are locked (Task 2.2 done).

---

#### [x] Task 4.1 — Fix existing test_trading_cycle tests (align candle timestamps)

**Spec requirement**: Section 6 (anti-drift invariant — existing behavior preserved).

**File**: `tests/unit/test_trading_cycle.py`

For every existing test that constructs a use case (tests 4.1–4.3 in the design):
1. Update `_make_use_case` call to include `clock`, `poll_minutes`, `freshness_max_retries`, `freshness_retry_seconds`.
2. Update `_make_candles` (or inline candle construction) to stamp `candles[-1].timestamp` with the `expected_decision_ts` derived from the seeded clock (`2024-01-01T00:00:00Z` for seed `2024-01-01T00:15:06Z`).

These tests must remain GREEN — no behavior change, just timestamp alignment so the gate passes.

**Sequential after Task 2.2**.

---

#### [x] Task 4.2 — Update test_main_loop config

**Spec requirement**: Section 4 (fields passed through from Config).

**File**: `tests/unit/test_main_loop.py`

In `_make_config` (or equivalent fixture), set concrete values for the three new fields that `build_use_case` will now forward:
```python
config.poll_minutes = 15
config.freshness_max_retries = 3
config.freshness_retry_seconds = 2.0
```

Run suite — existing main-loop tests must stay GREEN.

**Sequential after Task 3.1**.

---

### Group 5 — Full suite green

Depends on all prior groups completing.

---

#### [x] Task 5.1 — Full suite green + smoke check

Run `.venv/bin/pytest` from `operator/`.

Expected: all tests pass, zero warnings about unknown Config fields, no `TypeError` on use-case construction anywhere in the suite.

If any test fails, diagnose and fix within the scope of this change before marking done.

**Sequential after Groups 0–4 complete**.

---

## Execution Order Summary

```
0.1 → 0.2 (FakeClock fix — prerequisite)
          ↓
1.1 → 1.2 (Config fields — can start in parallel with 0.x)
          ↓
2.1 → 2.2 → 2.3 → 2.4 (gate + scenarios — sequential)
                        ↓
               3.1 (wiring — after 2.2)
                        ↓
               4.1, 4.2 (migration — after 2.2 and 3.1 respectively)
                        ↓
                      5.1 (full suite — after all above)
```

Groups 0 and 1 can start in parallel. Groups 2–5 are sequentially gated.
