# Proposal: trading-engine

## 1. Intent / Why Now

The aggressive-exhaustion fade is **frozen and in-sample validated** on EURUSD
(E[R] +0.13, 14/14 years positive, beats random p95). Backtesting is done. The
single remaining unknown before any capital is at risk is **execution reality**:
does the strategy, when driven by live broker candles and live order placement,
behave the way the vectorized backtest predicts?

We build a process that runs the frozen fade **live on Capital.com demo** so we
can forward-test execution — candle delivery, closed-bar semantics, fill
variance, lot semantics, atomic SL/TP attachment — with **zero real-money
exposure**. Forward-test first, fund later. This change delivers the smallest
correct vertical slice that proves the loop end-to-end.

Success = a long-running process that, every 15 minutes on a closed candle,
fetches history, evaluates the frozen fade through the **exact research
helpers**, and — when and only when the strategy fires — places ONE demo order
with stop-loss and take-profit attached atomically, never stacking positions.

## 2. Scope (In)

Nine production files plus a test for each (TDD red-green-refactor, tests
written first), plus two unblocking fixes.

**Domain (pure, no I/O):**
1. `src/domain/entities/order.py` — `OrderResult` value object
   (`order_id: str`, `filled_price: float`, `status: str`). Unblocks the
   broken `BrokerPort` import.
2. `src/domain/ports/clock_port.py` — `ClockPort` ABC with `utcnow()`. Keeps
   time injectable so the loop is deterministically testable.
3. `src/domain/adapters/fade_strategy.py` — `FadeStrategy(StrategyPort)`. Bridges
   `Sequence[Candle]` to the **frozen research helpers** and emits a `Signal`
   with absolute SL/TP prices. `required_candles` = WARMUP (see §4).

**Application (orchestration, depends only on ports):**
4. `src/application/trading_cycle.py` — `RunTradingCycleUseCase`. One cycle:
   guard against open position, fetch candles, evaluate, place order if a signal
   exists. Sizing injected. No scheduling, no broker specifics here.

**Infrastructure (Capital.com adapters):**
5. `src/infrastructure/capital/session.py` — `CapitalSession`. Eager re-auth,
   exposes valid `CST`/`X-SECURITY-TOKEN` per cycle.
6. `src/infrastructure/capital/broker.py` — `CapitalBrokerAdapter(BrokerPort)`.
   Implements `recent_candles`, `open_position`, `has_open_position` against the
   Capital.com REST API. Strips the in-progress candle.
7. `src/infrastructure/capital/clock.py` — `SystemClock(ClockPort)`.

**Composition + config:**
8. `src/config.py` — env loading, MODE guard, trade params (symbol/epic, size,
   warmup, timeframe).
9. `src/__main__.py` — DI wiring + sleep-loop entry point aligned to 15-minute
   boundaries via the clock.

**Unblocking fixes:**
- Fix the broken `domain.entities.order.OrderResult` import in `BrokerPort`
  (resolved by file #1).
- Add `numpy` and `pandas` to `pyproject.toml` (the frozen helpers require them).

## 3. Scope (Out / Non-Goals)

- **Multi-strategy** in one process. v1 is ONE frozen fade.
- **Multi-provider in one process.** Capital.com REST only.
- **The FX basket.** ONE pair (EURUSD) in demo first. No multi-asset scan.
- **Live real-money trading.** Demo only; the live guard exists but live is not
  the goal of this change.
- **Backtesting / re-validation.** Already done and frozen. We do not touch
  `fade_strategy.py`.
- **WebSocket / streaming candles.** REST polling on a 15-minute cadence.
- **Swap, slippage, spread modeling.** Demo forward-test observes real fills; we
  do not model costs here.
- **Re-implementing any strategy decision logic.** Hard non-goal — see §4.

## 4. Locked Decisions

| Decision | Choice | Rationale |
|---|---|---|
| **Session expiry** | Eager re-auth per cycle | Idempotent, zero retry branching, no background thread. ~100ms on a 15-min tick is negligible. Simplest correct option. |
| **Scheduling** | Sleep loop driven by `ClockPort` | Zero new deps; deterministically testable by injecting a fake clock; computes the next 15-min boundary from `utcnow()`. |
| **Strategy bridge** | Import and call the frozen helpers DIRECTLY (`compute_atr`, `identify_runs`, `extract_trajectory_features`, and the frozen constants) | **#1 correctness guarantee.** Any re-implementation is silent logic drift. The live adapter converts candles to numpy arrays and asks the same code the backtest asks. |
| **Sizing** | Fixed lot from config, injected into the use case | Matches the existing `open_position(symbol, signal, size)` signature; no sizing logic in domain. |
| **Safety guard** | Replicate `MODE=demo/live` + `I_UNDERSTAND_THIS_IS_REAL_MONEY=YES` | Proven pattern from the IC Markets bot; live path is unreachable without explicit confirmation. |
| **TDD** | Tests-first, red-green-refactor, every file | Strict TDD Mode is active and this is real-money-adjacent software. |

**Strategy-bridge mechanics (locked detail).** The frozen pipeline is causal:
`identify_runs` and `extract_trajectory_features` look back only. The live
adapter:
1. Takes the last `required_candles` **closed** candles (in-progress candle
   already stripped by the broker adapter).
2. Builds the numpy `o/h/l/c` arrays + a DataFrame and computes ATR via
   `compute_atr` with the frozen `ATR_PERIOD`.
3. Reuses the frozen aggressiveness gate (`MIN_DISP_ATR`, `MIN_STRAIGHTNESS`,
   `L_FROZEN`, `DIR_THRESHOLD_FROZEN`) to decide whether the most recent closed
   bar is an aggressive run endpoint.
4. If it is, fades it (`-direction`), and computes absolute SL/TP from the same
   `SL_ATR_MULT`/`RR` arithmetic the backtest uses (SL = `2*ATR`, TP = `RR*SL`),
   emitting a `Signal` whose `entry_reference` is the signal-bar close.

`required_candles` must cover the helpers' burn-in
(`max(L_FROZEN, ATR_PERIOD)` = 32) with margin for stable ATR; we lock WARMUP
to **64** candles (matching the IC Markets `WARMUP_BARS`), giving the recursive
ATR ample convergence before the gate is evaluated.

**Entry reference is the signal-bar close.** Backtest enters at next-bar open;
live fills at market on the next tick. The ~1–3 pip difference on 15m EURUSD is
accepted for demo and must be logged so the forward-test can measure it.

## 5. Key Risks (carried from exploration)

1. **Logic drift (live vs backtest)** — the single most important risk.
   *Mitigation:* the live adapter calls the frozen helpers directly AND an
   integration test compares adapter signals to `simulate_fades` over the same
   candle window. If they disagree, the build fails.
2. **Entry-price variance** — live fill differs from backtest's next-open entry.
   *Mitigation:* documented and accepted for demo; log `entry_reference` vs
   actual `filled_price` to quantify it.
3. **Capital.com lot-size semantics** — Capital.com "size" is base-currency
   units, not MT-style lots. `0.01` must be confirmed before the first live-demo
   order. *Mitigation:* size is a config constant; verify against the demo
   account before funding anything real.
4. **Missing IDENTIFIER** — `.env` has key + password but no account email
   required for the REST session handshake. *Mitigation:* runtime input (§6).
5. **In-progress candle** — Capital.com history includes the still-open candle.
   *Mitigation:* the broker adapter strips the last candle; a unit test pins
   this so the strategy never sees an unclosed bar.

## 6. Open Inputs From User (runtime, NOT design blockers)

These are runtime configuration values, not architectural decisions. The
proposal, specs, design, and tasks proceed without them; they are required only
before the first live-demo run.

1. **`IDENTIFIER`** — Capital.com account email for the REST session handshake.
2. **EURUSD epic string** — e.g. `CS.D.EURUSD.MINI.IP`.
3. **Lot-size semantics** — confirm what `size=0.01` means on Capital.com.
4. **Demo account active** — confirm the Capital.com demo is registered before
   the first run.

## 7. First-Slice Boundary (minimal shippable vertical)

A single long-running process that:

1. **Authenticates** against Capital.com demo (eager, per cycle), refusing to
   touch live unless `MODE=live` AND `I_UNDERSTAND_THIS_IS_REAL_MONEY=YES`.
2. **Fetches** the last 64 **closed** EURUSD 15m candles (in-progress stripped).
3. **Evaluates** the frozen fade via the research helpers — no re-implementation.
4. **Avoids stacking**: if a position is already open for the symbol, it skips
   placement for that cycle.
5. **Places ONE demo order** with stop-loss and take-profit attached **atomically**
   when — and only when — the strategy fires.
6. **Loops every 15 minutes**, aligned to candle close via the `ClockPort`.

Everything in §3 is explicitly outside this slice. Shipping this slice proves
the live loop is correct end-to-end on demo, which is the precondition for any
future real-money or multi-asset work.
