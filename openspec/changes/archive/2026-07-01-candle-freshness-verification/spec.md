# Spec: candle-freshness-verification

## Delta — What Must Be True After This Change

### 1. Freshness Gate

The `RunTradingCycleUseCase.execute()` method MUST verify the freshness of the decision candle before any strategy evaluation occurs.

**Expected decision-candle timestamp** is computed via epoch-modulo:

```
period_secs        = poll_minutes * 60
boundary_epoch     = floor(now_epoch / period_secs) * period_secs
expected_ts        = UTC datetime at (boundary_epoch - period_secs)
```

This formula must mirror `seconds_until_next_boundary` exactly (epoch-modulo, NOT `datetime.replace`). After `broker.py`'s `records[:-1]` drop, the decision candle is `candles[-1]`. Strategy evaluation proceeds only when `candles[-1].timestamp == expected_ts`.

**Invariant**: no strategy evaluation and no order submission may happen when `candles[-1].timestamp != expected_ts`.

---

### 2. Retry with Backoff

When `candles[-1].timestamp != expected_ts`, the use case MUST:

1. Sleep `freshness_retry_seconds` via `ClockPort.sleep`.
2. Re-fetch candles from the broker.
3. Re-evaluate freshness.

This retry cycle repeats up to `freshness_max_retries` additional times after the initial fetch. Total fetches = `1 + freshness_max_retries`; total sleeps (when all fetches are stale) = `freshness_max_retries`.

---

### 3. Skip-on-Stale (Safe Default)

When the candle remains stale after all retry attempts are exhausted, the use case MUST:

- Log a WARNING containing the retry count and the boundary timestamp.
- Return without opening any position (no signal emitted, no order submitted).

This is the safe default: a missed boundary is always preferred over trading on a stale candle.

---

### 4. Config Contract

`Config` MUST expose two new fields with the following defaults and environment variable bindings:

| Field | Type | Default | Env var |
|---|---|---|---|
| `freshness_max_retries` | `int` | `3` | `FRESHNESS_MAX_RETRIES` |
| `freshness_retry_seconds` | `float` | `2.0` | `FRESHNESS_RETRY_SECONDS` |

Both fields MUST be passed from `build_use_case` into `RunTradingCycleUseCase.__init__`.

`RunTradingCycleUseCase.__init__` MUST also accept `clock: ClockPort` and `poll_minutes: int`, sourced from `__main__.py` wiring.

`candle_settle_seconds` remains but its role changes to advisory (minimum head-start before the first fetch); it is no longer the correctness gate.

---

### 5. FakeClock.sleep Advancement

`FakeClock.sleep(seconds)` MUST advance `self._time` by `seconds`. This is required for retry-loop tests to be deterministic; without it, timestamp comparisons inside the loop never change.

---

### 6. Anti-Drift Invariant

The freshness gate MUST NOT alter the outcome of strategy evaluation. When a fresh candle is present, the signal produced by `FadeStrategy` MUST be identical to the signal produced before this change was applied. The gate is a pre-trade guard only; it does not touch `FadeStrategy` or any strategy math.

---

## Acceptance Scenarios

### Scenario 1 — Fresh candle on first attempt

```
Given  the use case is called at boundary B
And    candles[-1].timestamp == expected_decision_ts
When   execute() runs
Then   the freshness gate passes on the first attempt
And    the strategy is evaluated on candles[-1]
And    clock.sleep is NOT called by the freshness gate
And    the order flow proceeds normally
```

### Scenario 2 — Stale on attempt 1, fresh on attempt 2

```
Given  the use case is called at boundary B
And    candles[-1].timestamp != expected_decision_ts on the first fetch
And    candles[-1].timestamp == expected_decision_ts on the second fetch
When   execute() runs
Then   clock.sleep is called exactly once with freshness_retry_seconds
And    the broker is queried for candles exactly twice
And    the strategy is evaluated after the second fetch
And    no skip warning is logged
And    the order flow proceeds normally
```

### Scenario 3 — Stale on every attempt (max retries exhausted)

```
Given  the use case is called at boundary B
And    candles[-1].timestamp != expected_decision_ts on every fetch
And    freshness_max_retries == 3
When   execute() runs
Then   clock.sleep is called exactly freshness_max_retries times (3 sleeps when max_retries=3)
And    the broker is queried for candles exactly 1 + freshness_max_retries times (4 fetches when max_retries=3)
And    a WARNING is logged containing the retry count and boundary timestamp
And    execute() returns without opening any position
And    no order submission occurs
```

### Scenario 4 — Config defaults loaded from env

```
Given  FRESHNESS_MAX_RETRIES and FRESHNESS_RETRY_SECONDS are not set in the environment
When   Config is instantiated
Then   freshness_max_retries == 3
And    freshness_retry_seconds == 2.0
```

```
Given  FRESHNESS_MAX_RETRIES=5 and FRESHNESS_RETRY_SECONDS=1.5 are set in the environment
When   Config is instantiated
Then   freshness_max_retries == 5
And    freshness_retry_seconds == 1.5
```

### Scenario 5 — Anti-drift (signal unchanged when candle is fresh)

```
Given  a known set of candles with candles[-1].timestamp == expected_decision_ts
And    the frozen fade strategy produces signal S for that candle set (pre-change baseline)
When   execute() runs with the freshness gate active
Then   the signal produced is identical to S
And    no strategy parameter or calculation differs from the pre-change baseline
```

### Scenario 6 — FakeClock.sleep advances time

```
Given  a FakeClock initialised at time T
When   clock.sleep(2.0) is called
Then   clock.utcnow() returns T + 2.0 seconds
```

---

## Out of Scope

- Renaming or removing `candle_settle_seconds`.
- Websocket or push-based freshness sources.
- Multi-symbol freshness handling.
- Any change to `FadeStrategy`, its math, or its signal output.
- Any change to `broker_port`, `clock_port`, `broker.py`, or `candle.py`.
