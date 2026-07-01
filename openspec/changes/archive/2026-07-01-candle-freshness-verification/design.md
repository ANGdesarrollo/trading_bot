# Design: candle-freshness-verification

## Technical Approach

Approach B (proposal): freshness is application policy, so the gate lives at the
top of `RunTradingCycleUseCase.execute()`. The use case gains a `ClockPort`,
`poll_minutes`, and two retry params. It computes the expected decision-candle
timestamp via epoch-modulo (mirroring `seconds_until_next_boundary`), compares it
to `candles[-1].timestamp`, retries with `clock.sleep` backoff, and skips the
boundary (`return None` + WARNING) if still stale after N retries. No new ports,
entities, or abstractions. `candle_settle_seconds` stays but becomes advisory.

## Architecture Decisions

| Decision | Choice | Rejected | Rationale |
|---|---|---|---|
| Gate location | Use case `execute()` | Loop (`run_forever`) / broker adapter | Policy belongs in application; ClockPort injectable → fully unit-testable via fakes; keeps infra + loop free of business rules (SRP) |
| Timestamp math | epoch-modulo `now % period_secs` | `datetime.replace(...)` | Must mirror `seconds_until_next_boundary` exactly to avoid off-by-one on boundary-exact times |
| Stale outcome | `return None` + `logger.warning` | Trade anyway / raise | Skip-on-stale is the safe default: no position ever opened on a stale candle |
| `candle_settle_seconds` | Keep as advisory minimum head-start | Remove / rename | Out of scope to rename; the retry loop is now the correctness gate, so a big fixed sleep is no longer needed |

## Interfaces / Contracts

**Config** (`src/config.py`) — 2 new fields + env parsing:

```python
freshness_max_retries: int      # env FRESHNESS_MAX_RETRIES, default 3
freshness_retry_seconds: float  # env FRESHNESS_RETRY_SECONDS, default 2.0
# parsing:
freshness_max_retries = int(os.environ.get("FRESHNESS_MAX_RETRIES", "3"))
freshness_retry_seconds = float(os.environ.get("FRESHNESS_RETRY_SECONDS", "2.0"))
```

**Use case constructor** — before/after:

```python
# before
def __init__(self, broker, strategy, symbol, size, logger): ...
# after (append new params; existing ones unchanged)
def __init__(self, broker, strategy, symbol, size, logger,
             clock: ClockPort, poll_minutes: int,
             freshness_max_retries: int, freshness_retry_seconds: float): ...
```

**Freshness gate** — top of `execute()`, after the has-open-position guard,
before/replacing the current `recent_candles` call:

```python
from datetime import datetime, timezone

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
# candles now fresh → continue to strategy.evaluate(candles)
```

Retry budget = `max_retries + 1` fetches (initial try + N retries). Worst case
3 retries × 2.0s = 6s, well within the 15m interval.

**FakeClock.sleep** (`tests/fakes/fake_clock.py`) — before/after:

```python
# before — frozen time (retry tests loop wrong / can't diverge)
def sleep(self, seconds): self.sleep_calls.append(seconds)
# after — advance virtual time
from datetime import timedelta
def sleep(self, seconds):
    self.sleep_calls.append(seconds)
    self._time = self._time + timedelta(seconds=seconds)
```

## File Changes

| File | Action | Description |
|---|---|---|
| `src/config.py` | Modify | 2 fields + env parsing (defaults 3 / 2.0) |
| `src/application/trading_cycle.py` | Modify | Store new deps; freshness gate at top of `execute()`; import datetime/timezone, ClockPort |
| `src/__main__.py` | Modify | `build_use_case` passes `clock=clock, poll_minutes=config.poll_minutes, freshness_max_retries=config.freshness_max_retries, freshness_retry_seconds=config.freshness_retry_seconds` |
| `tests/fakes/fake_clock.py` | Modify | `sleep` advances `_time` |
| `tests/unit/test_trading_cycle.py` | Modify | `_make_use_case` takes clock/poll_minutes; align candle ts; 3 new scenarios |
| `tests/unit/test_main_loop.py` | Modify | `_make_config` sets the 3 new fields |

`build_use_case` already receives `clock` positionally — only its internal
`RunTradingCycleUseCase(...)` call changes; no loop signature change.
`candle_settle_seconds` default may be lowered to `0` (advisory only) — kept as a
minimum head-start; not required for correctness. Recommend keeping default `5`
to preserve behavior, since the retry loop now covers late publishes.

## Testing Strategy

| Layer | What | Approach |
|---|---|---|
| Unit | FakeClock.sleep advances time | Seed clock; `sleep(2)`; assert `utcnow()` advanced 2s (prerequisite fix) |
| Unit | Fresh first try | Seed clock at boundary+6s; `candles[-1].timestamp == expected`; assert no sleep, evaluate runs |
| Unit | Stale then fresh | FakeBroker returns stale ts first, fresh after 1 fetch; assert `sleep_calls == [2.0]`, then evaluate runs |
| Unit | Always stale → skip | Broker always stale; assert `return None`, `len(sleep_calls) == max_retries`, WARNING logged, no `open_position` |
| Unit | Existing 4.1–4.3 | Align `_make_candles` ts to `expected_decision_ts` for a seeded clock; keep behavior |

**Test migration.** `_make_use_case` must inject `clock` (seeded FakeClock) +
`poll_minutes=15` + the two retry params. `_make_candles` must stamp candles with
the `expected_decision_ts` derived from the seeded clock time (e.g. seed
`2024-01-01 00:15:06Z` → expected `2024-01-01 00:00:00Z`), or the existing
no-signal/signal tests will now skip-on-stale. `test_main_loop._make_config` adds
`poll_minutes`, `freshness_max_retries`, `freshness_retry_seconds` (MagicMock
already tolerates attribute access, but `build_use_case` passes them to the real
use case, so set concrete ints/floats).

## Migration / Rollout

No data migration. New env vars have safe defaults; existing `.env` needs no
change. Backward compatible except the use case constructor gains required params
(all call sites updated in this change).

## Strict TDD Ordering

1. **RED/GREEN prerequisite** — FakeClock.sleep advances time (test-support fix + its own assertion test).
2. **RED** — always-stale skip test (strongest contract: proves `return None`, sleep count, WARNING, no order). Drives constructor + gate.
3. **GREEN** — implement constructor params + gate.
4. **RED/GREEN** — fresh-first-try, then stale-then-fresh.
5. Update existing 4.1–4.3 + main-loop config to compile against new signature.

## Open Questions

- [ ] Lower `candle_settle_seconds` default to 0? Recommendation: keep 5 (advisory head-start); retry loop is the real gate. Non-blocking.
