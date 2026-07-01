# Exploration: candle-freshness-verification

## Problem (measured against the REAL Capital.com demo API)

The bot polls on a 15-minute boundary and evaluates the frozen fade strategy on the just-CLOSED candle, entering at the next bar's open. Two facts measured against the demo:

1. Capital.com publishes the just-closed candle **~6 seconds AFTER** the boundary (not instantly). Measured: at boundary 01:45:00 UTC, the new row 01:45 appeared at T+6.0s.
2. The API's LAST row is always the IN-PROGRESS candle. `broker.py:54` does `records[:-1]` to drop it — this is CORRECT (verified mid-interval: last row == current forming candle).

**The bug**: `__main__.py:79` waits only `boundary + candle_settle_seconds` (default 5s), but the closed candle is published at ~6s. So the bot can query BEFORE the decision candle is firm and evaluate on a STALE candle. A fixed sleep is fragile against variable publish latency.

The DECISION candle is the one that closed AT the boundary (boundary 22:45:00 → decision candle 22:30→22:45, snapshot 22:30:00). After `records[:-1]`, the decision candle is `candles[-1]`.

## Chosen fix

Verify by timestamp + retry + skip-on-stale. Verify that `candles[-1].timestamp == boundary - poll_minutes`. If stale, retry a few times with short backoff; if still stale after N tries, SKIP the boundary and log (NEVER trade on a stale candle). Removes dependence on guessing settle latency.

## Current State

Loop (`src/__main__.py:76-84`):
```python
clock.sleep(wait + config.candle_settle_seconds)   # line 79 — THE BUG
session.authenticate()
use_case.execute()
```
`candle_settle_seconds` defaults to 5; Capital publishes at ~T+6s. No retry, no freshness check anywhere.

Decision candle timestamp: `candles[-1].timestamp` after `records[:-1]`, parsed from `snapshotTimeUTC` as UTC-aware datetime (`broker.py:121-123`).

Expected timestamp formula (must mirror `seconds_until_next_boundary`, which uses `epoch % period`, NOT `datetime.replace`):
```python
period_secs = poll_minutes * 60
now_epoch = clock.utcnow().timestamp()
boundary_epoch = now_epoch - (now_epoch % period_secs)
expected_decision_ts = datetime.fromtimestamp(boundary_epoch - period_secs, tz=timezone.utc)
```
Measured check: boundary 01:45:00 → expected_decision_ts 01:30:00. ✓

`FakeClock.sleep` does NOT advance `_time` — MUST be fixed for retry-loop tests.

## Approaches

| Approach | Pros | Cons |
|---|---|---|
| A. Check in `run_forever` (__main__) | boundary math + clock in scope | mixes timing with trading policy (SRP), hard to unit-test |
| **B. Check in `RunTradingCycleUseCase` (application)** (recommended) | application policy belongs here; ClockPort injectable; fully testable via fakes; hexagonally pure; skip-on-stale = return None | +clock, +poll_minutes to constructor |
| C. Check in `CapitalBrokerAdapter` (infra) | co-located with parsing | infra must not encode business policy; adapter shouldn't hold a clock |

## Recommendation: Approach B

The question "is this candle fresh enough to trade on?" is application policy — the use case is where pre-trade guards belong.

Shape:
1. `Config` gains `freshness_max_retries: int = 3` (env `FRESHNESS_MAX_RETRIES`), `freshness_retry_seconds: float = 2.0` (env `FRESHNESS_RETRY_SECONDS`).
2. `RunTradingCycleUseCase.__init__` gains `clock: ClockPort`, `poll_minutes: int`, `freshness_max_retries`, `freshness_retry_seconds`.
3. `execute()` computes `expected_decision_ts` via the epoch-modulo formula above.
4. Fetch candles. If `candles[-1].timestamp != expected_decision_ts`: `clock.sleep(freshness_retry_seconds)` and retry. After max retries, log WARNING and return None.
5. `build_use_case` passes clock, poll_minutes and the two retry params.
6. `candle_settle_seconds` becomes advisory (minimum head-start), no longer the correctness gate.

Skip-on-stale: `logger.warning("stale candle after %d retries at boundary %s; skipping", ...)` then `return None`. No position ever opened on a stale candle. Worst case: 3×2s = 6s overhead, well within 15m.

## Files to change

| File | Change |
|---|---|
| `src/config.py` | add `freshness_max_retries`, `freshness_retry_seconds` fields + env parsing |
| `src/application/trading_cycle.py` | inject ClockPort + retry params; freshness gate at top of execute() |
| `src/__main__.py` | pass clock, poll_minutes, retry config into build_use_case |
| `tests/fakes/fake_clock.py` | `sleep` must advance `self._time` (CRITICAL) |
| `tests/unit/test_trading_cycle.py` | new fresh/retry/skip-on-stale scenarios + fix existing candle timestamps |
| `tests/unit/test_main_loop.py` | update config + build_use_case for new fields |

No change: broker_port, clock_port, broker.py, candle.py (timestamp parsing already correct).

## Risks

- **`FakeClock.sleep` frozen time** (highest): retry tests need sleep to advance time. Fix first.
- **Floor formula precision**: mirror epoch-modulo exactly to avoid off-by-one on boundary-exact times.
- **`candle_settle_seconds` role ambiguity**: becomes advisory; clarify in spec.
- **Anti-drift guarantee**: ZERO risk. Freshness gate does not touch FadeStrategy or strategy math; only gates whether execute() proceeds.
