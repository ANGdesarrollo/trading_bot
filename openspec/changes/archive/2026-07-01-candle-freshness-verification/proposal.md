# Proposal: candle-freshness-verification

## Intent

**Problem.** The bot polls on each 15m boundary and evaluates the frozen fade strategy on the just-closed candle. Measured against the REAL Capital.com demo, the just-closed candle is published **~6 seconds AFTER** the boundary (boundary 01:45:00 UTC → row 01:45 appeared at T+6.0s). But the loop (`__main__.py:79`) waits only `boundary + candle_settle_seconds` (default **5s**) before querying. So the bot can read BEFORE the decision candle is firm and evaluate the strategy on a **stale** candle. A single fixed sleep is fundamentally fragile against variable publish latency.

**Why now.** This is a correctness/reliability defect, not a feature. The bot's entire edge depends on acting on the CORRECT just-closed candle. Trading on a stale candle silently corrupts every downstream decision. The 5s-vs-6s gap is small but reproducible on the demo, so it will fire in production.

**Success.** The bot only ever acts on the exact expected just-closed candle. When the candle is not yet fresh, the bot waits and retries; if still stale after N retries, it SKIPS the boundary and logs — it NEVER trades on a stale candle. Correctness no longer depends on guessing publish latency.

## Scope

### In Scope
- **Freshness gate** in `RunTradingCycleUseCase.execute()` (application layer, Approach B): compute the expected decision-candle timestamp via epoch-modulo, compare against `candles[-1].timestamp`, retry with backoff, skip-on-stale.
- **2 new `Config` fields**: `freshness_max_retries: int = 3` (env `FRESHNESS_MAX_RETRIES`), `freshness_retry_seconds: float = 2.0` (env `FRESHNESS_RETRY_SECONDS`), with env parsing.
- **Inject `ClockPort` + `poll_minutes` + the two retry params** into the use case constructor; wire them through `build_use_case` in `__main__.py`.
- **`FakeClock.sleep` advances `_time`** (currently frozen) — required so retry-loop tests are deterministic.
- **Tests**: fresh-candle pass-through, stale-then-fresh retry, stale-after-max-retries skip; fix existing candle timestamps; update main-loop config/build wiring.
- Make `candle_settle_seconds` **advisory** (a minimum head-start), no longer the correctness gate.

### Out of Scope
- Renaming or deprecating `candle_settle_seconds` beyond making it advisory.
- Websocket / streaming candles or any push-based freshness source.
- Multi-symbol freshness handling.
- Any change to the frozen fade strategy, its math, or the anti-drift guarantee.

## Approach — B: gate in the use case

Freshness is **application policy** ("is this candle fresh enough to trade on?"), so it belongs in `RunTradingCycleUseCase`, not in the loop (mixes timing with policy, hard to unit-test) nor in the broker adapter (infra must not encode business policy).

1. `execute()` computes the expected decision timestamp mirroring `seconds_until_next_boundary` exactly (epoch-modulo, NOT `datetime.replace`):
   ```python
   period_secs = poll_minutes * 60
   now_epoch = clock.utcnow().timestamp()
   boundary_epoch = now_epoch - (now_epoch % period_secs)
   expected_decision_ts = datetime.fromtimestamp(boundary_epoch - period_secs, tz=timezone.utc)
   ```
2. Fetch candles. If `candles[-1].timestamp != expected_decision_ts`: `clock.sleep(freshness_retry_seconds)` and retry.
3. After `freshness_max_retries`, log a WARNING and `return None` (skip the boundary).

**Skip-on-stale is the SAFE default**: no position is ever opened on a stale candle. Worst case overhead is `3 × 2s = 6s`, well within the 15m interval. Validated against the demo (boundary 01:45:00 → expected 01:30:00 ✓).

## Impact

| File | Change |
|---|---|
| `src/config.py` | add `freshness_max_retries`, `freshness_retry_seconds` + env parsing |
| `src/application/trading_cycle.py` | inject ClockPort + poll_minutes + retry params; freshness gate at top of `execute()` |
| `src/__main__.py` | pass clock, poll_minutes, retry config into `build_use_case` |
| `tests/fakes/fake_clock.py` | `sleep` advances `self._time` (CRITICAL) |
| `tests/unit/test_trading_cycle.py` | fresh/retry/skip-on-stale scenarios; fix existing candle timestamps |
| `tests/unit/test_main_loop.py` | update config + `build_use_case` for new fields |

No change to: `broker_port`, `clock_port`, `broker.py`, `candle.py` (timestamp parsing already correct; `records[:-1]` verified correct).

## Risks

- **`FakeClock.sleep` frozen time (highest).** Retry-loop tests need `sleep` to advance time or they hang/loop wrong. Fix this FIRST.
- **Epoch-modulo precision.** Must mirror `seconds_until_next_boundary` exactly to avoid off-by-one on boundary-exact times. Anchor tests on the measured 01:45:00 → 01:30:00 case.
- **`candle_settle_seconds` role ambiguity.** Becomes advisory; clarify in the spec so it is not mistaken for the correctness gate.
- **Anti-drift guarantee: ZERO risk.** The gate does not touch `FadeStrategy` or any strategy math; it only decides whether `execute()` proceeds. Guarantee untouched.

## Delivery

Single-PR small change. Localized to config + one use case + wiring + tests.
