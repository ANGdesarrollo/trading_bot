# Exploration: trading-engine

## Current State

The `capital_integration/` project has a clean hexagonal skeleton at the domain
layer — `Candle`, `Direction`, `Signal`, `StrategyPort`, and `BrokerPort` are
well-designed and solid. Nothing else exists: zero application layer, zero
infrastructure, zero tests, no entry point.

`BrokerPort` has a broken import: it references `domain.entities.order.OrderResult`
which does not exist. This is the first thing that must be created before anything
else compiles.

The IC Markets bot (`integration_icmarkets/`) only implemented Step 1 (connect +
auth via Twisted/TCP). It never reached the trading loop. Useful patterns it
established: the `MODE="demo"/"live"` guard with
`I_UNDERSTAND_THIS_IS_REAL_MONEY=YES` confirmation, `WARMUP_BARS=64`,
`LOT_SIZE=0.01`, `SYMBOL_NAME="EURUSD"`.

## Affected Areas

- `capital_integration/src/domain/entities/` — `order.py` missing
- `capital_integration/src/domain/ports/broker_port.py` — broken import, unblocked by `order.py`
- `capital_integration/src/domain/` — new `ports/clock_port.py` + `adapters/fade_strategy.py`
- `capital_integration/src/application/` — entire layer to create
- `capital_integration/src/infrastructure/capital/` — entire layer to create
- `capital_integration/.env` — missing `IDENTIFIER`
- `capital_integration/pyproject.toml` — missing `numpy` and `pandas`
- `backend/research/lib/fade_strategy.py` — READ ONLY, source of truth the live adapter must call directly

## Approaches

### Fork 1: Session Expiry (15-min polling, 10-min session TTL)

| Approach | Pros | Cons | Complexity |
|---|---|---|---|
| A. Background keep-alive ping every ~8 min | Session always warm; no retry | Requires thread/async; more moving parts | Medium |
| B. Lazy re-auth on 401 | No background task | Retry branching on every broker call | Low-Medium |
| **C. Eager re-auth per cycle** | Dead simple; idempotent; zero branching | ~100ms overhead per 15-min tick | **Low** |

### Fork 2: Trading Loop / Scheduling

| Approach | Pros | Cons | Complexity |
|---|---|---|---|
| **A. Sleep loop** | Zero deps; easy to test with ClockPort | Clock drift over days; must compute next boundary | **Low** |
| B. APScheduler | Drift correction | Extra dep; harder to test | Medium |
| C. System cron | OS-managed | No shared state; can't hold session | High |

### Fork 3: FadeStrategy Backtest -> Live Bridge

The vectorized `simulate_fades` cannot be called directly on a rolling window —
but `identify_runs` and `extract_trajectory_features` ARE causal, purely
functional, and can be called on a numpy slice of the last 64 candles. The live
adapter converts `Sequence[Candle]` -> numpy arrays, calls the frozen helpers,
checks whether bar `N-1` is an aggressive run endpoint, and emits a Signal if so.
The `entry_reference` is set to the close of the signal bar (bar N-1 close ~=
next open); actual fill will differ by a few pips.

**Critical risk**: the live adapter must import and call the frozen research
helpers DIRECTLY — never re-implement them. Any re-implementation is a silent
logic drift risk.

### Fork 4: Position Sizing

Fixed `TRADE_SIZE = 0.01` lives in config, passed into the application use case,
which calls `broker.open_position(symbol, signal, config.trade_size)`. Consistent
with the existing `BrokerPort` signature.

## Recommendation

1. **Session**: Approach C (eager re-auth per cycle)
2. **Scheduling**: Approach A (sleep loop with `ClockPort` abstraction)
3. **FadeStrategy**: import frozen helpers directly; never re-implement; `required_candles = 64`
4. **Entry reference**: signal-bar close as `entry_reference`, accepting fill variance
5. **Sizing**: config constant injected into the use case
6. **MODE guard**: replicate the `I_UNDERSTAND_THIS_IS_REAL_MONEY=YES` pattern

## What to Build (ordered)

```
capital_integration/src/
├── domain/entities/order.py           — OrderResult (order_id, filled_price, status)
├── domain/ports/clock_port.py         — ClockPort (utcnow abstract method)
├── domain/adapters/fade_strategy.py   — FadeStrategy(StrategyPort), calls frozen helpers
├── application/trading_cycle.py       — RunTradingCycleUseCase
├── infrastructure/capital/session.py  — CapitalSession (per-cycle eager re-auth)
├── infrastructure/capital/broker.py   — CapitalBrokerAdapter(BrokerPort)
├── infrastructure/capital/clock.py    — SystemClock(ClockPort)
├── config.py                          — MODE guard, trade params, env loading
└── __main__.py                        — DI wiring + sleep loop entry point
```

## Risks

1. **Logic drift** — live FadeStrategy subtly diverges from backtest. Mitigated by
   calling frozen helpers directly and adding integration tests comparing adapter
   output to `simulate_fades` on the same candle window.
2. **Entry price slippage** — live fill ~= bar-N close, backtest entry = bar-N+1
   open. 1–3 pip difference on 15m EURUSD; acceptable for demo, must be documented.
3. **Capital.com lot sizing ambiguity** — Capital.com "size" is in base currency
   units, not lots. 0.01 must be verified.
4. **Missing IDENTIFIER** — `.env` has API key and password but no account email.
5. **Closed candle detection** — Capital.com returns the in-progress candle in
   price history. The adapter must strip the last (open) candle.
6. **numpy/pandas missing from pyproject.toml** — import errors on first run.

## Open Questions / Inputs Needed from User

1. **`IDENTIFIER`** — the Capital.com account email must be added to `.env`
2. **EURUSD epic string** — Capital.com uses epics (e.g., `CS.D.EURUSD.MINI.IP`)
3. **Lot size verification** — confirm what "size=0.01" means in Capital.com terms
4. **Demo account active?** — confirm Capital.com demo is registered before first run

## Ready for Proposal

Yes. The propose phase should lock down the session strategy, scheduling approach,
`OrderResult` shape, and the lot-sizing question before writing tasks.
