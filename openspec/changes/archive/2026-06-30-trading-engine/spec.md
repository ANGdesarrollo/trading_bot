# Spec: trading-engine

## 1. OrderResult Entity

**REQ-01** — `OrderResult` is an immutable value object in `domain.entities.order`
with three fields: `order_id: str`, `filled_price: float`, `status: str`.
It carries no behavior and enforces no field invariants beyond type.

**Scenario 1.1 — construction**
```
Given order_id="abc", filled_price=1.0852, status="OPEN"
When OrderResult is constructed with those values
Then order_id == "abc", filled_price == 1.0852, status == "OPEN"
```

**Scenario 1.2 — immutability**
```
Given an OrderResult instance
When any field assignment is attempted after construction
Then an AttributeError (or equivalent frozen-dataclass error) is raised
```

---

## 2. ClockPort Abstraction

**REQ-02** — `ClockPort` is an abstract base class in `domain.ports.clock_port`
with a single abstract method `utcnow() -> datetime` (timezone-aware UTC).
Concrete implementations must never be imported by domain or application code
directly — only the port is referenced.

**Scenario 2.1 — SystemClock delegation**
```
Given a SystemClock instance (implementing ClockPort)
When utcnow() is called
Then it returns a timezone-aware datetime with tzinfo == UTC
  And the returned time is within 2 seconds of the actual wall-clock UTC time
```

**Scenario 2.2 — FakeClock for tests**
```
Given a FakeClock seeded with datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
When utcnow() is called
Then it returns exactly datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
  And the result is timezone-aware
```

---

## 3. FadeStrategy Adapter (StrategyPort)

**REQ-03** — `FadeStrategy` implements `StrategyPort`.
Its `required_candles` property returns `64`.
Its `evaluate` method calls the frozen helpers (`compute_atr`, `identify_runs`,
`extract_trajectory_features`) using the frozen constants (`L_FROZEN`,
`DIR_THRESHOLD_FROZEN`, `ATR_PERIOD`, `MIN_DISP_ATR`, `MIN_STRAIGHTNESS`,
`SL_ATR_MULT`, `RR`) imported directly from `research.lib.fade_strategy`.
It never re-implements any strategy logic.

**REQ-04** — When `evaluate` receives fewer than 64 candles it returns `None`
immediately without invoking any helper.

**Scenario 3.1 — insufficient candles**
```
Given a FadeStrategy instance
  And a sequence of 63 valid Candle objects
When evaluate(candles) is called
Then the return value is None
  And no call to compute_atr or identify_runs is made
```

**Scenario 3.2 — no aggressive run at the last bar**
```
Given a FadeStrategy instance
  And exactly 64 closed Candle objects whose most recent bar does NOT satisfy
    the aggressiveness gate (total_disp_atr < MIN_DISP_ATR or
    straightness < MIN_STRAIGHTNESS)
When evaluate(candles) is called
Then the return value is None
```

**Scenario 3.3 — aggressive run at the last bar produces a valid Signal**
```
Given a FadeStrategy instance
  And exactly 64 closed Candle objects whose most recent bar IS an aggressive
    run endpoint (satisfies both displacement and straightness gates)
  And the frozen strategy would fade that run in direction D
    with SL = 2*ATR and TP = RR*SL
When evaluate(candles) is called
Then the return value is a Signal with:
    direction == Direction.BUY if D == +1 (fading a down-run)
    direction == Direction.SELL if D == -1 (fading an up-run)
    entry_reference == close price of the last candle
    stop_loss and take_profit satisfy the Signal invariant:
      BUY: stop_loss < entry_reference < take_profit
      SELL: take_profit < entry_reference < stop_loss
    |stop_loss - entry_reference| == 2 * ATR(last bar) (within float tolerance)
    |take_profit - entry_reference| == RR * 2 * ATR(last bar) (within float tolerance)
```

**REQ-05 — Anti-drift guarantee (CRITICAL)**

The signal produced by `FadeStrategy.evaluate` for any given candle window MUST
agree with what `simulate_fades` from the frozen module would decide for the same
window. Disagreement on direction, SL, or TP (beyond float rounding) constitutes
a regression and MUST fail the test suite.

**Scenario 3.4 — adapter signal matches simulate_fades (anti-drift)**
```
Given a 65-candle historical window W (64 closed candles + boundary candles
  from a known EURUSD fixture where simulate_fades produces exactly one trade)
  And the last candle in the 64-candle slice is the run_end_idx bar of that trade
When FadeStrategy.evaluate(W[-64:]) is called
  And simulate_fades is called over the full fixture
Then the adapter's Signal.direction matches the FadeTrade.direction
  And |adapter.stop_loss - FadeTrade.sl_price| < 1e-6
  And |adapter.take_profit - FadeTrade.tp_price| < 1e-6
```

Note: `simulate_fades` enters at next-bar open; the adapter uses the signal-bar
close as `entry_reference`. The anti-drift check targets SL/TP absolute prices
and direction — NOT entry price. Entry price divergence is expected and logged.

---

## 4. RunTradingCycleUseCase

**REQ-06** — `RunTradingCycleUseCase` lives in `application.trading_cycle`.
It depends only on `BrokerPort`, `StrategyPort`, a symbol string, and a size
float. It has no direct dependency on any infrastructure class.

**REQ-07** — When `broker.has_open_position(symbol)` returns `True`, the use
case skips all further work for that cycle (no candle fetch, no strategy call,
no order placement).

**Scenario 4.1 — position already open, nothing happens**
```
Given a RunTradingCycleUseCase with a stub BrokerPort
  And broker.has_open_position("EURUSD") returns True
When execute() is called
Then broker.recent_candles is NOT called
  And strategy.evaluate is NOT called
  And broker.open_position is NOT called
```

**REQ-08** — When `has_open_position` returns `False`, the use case fetches
`strategy.required_candles` candles via `broker.recent_candles(symbol, n)`.

**Scenario 4.2 — no signal, no order**
```
Given broker.has_open_position("EURUSD") returns False
  And broker.recent_candles returns 64 valid Candle objects
  And strategy.evaluate returns None
When execute() is called
Then broker.open_position is NOT called
```

**Scenario 4.3 — signal produced, one order placed**
```
Given broker.has_open_position("EURUSD") returns False
  And broker.recent_candles returns 64 valid Candle objects
  And strategy.evaluate returns a valid Signal S
When execute() is called
Then broker.open_position("EURUSD", S, size) is called exactly once
  And no second call to open_position is made within the same cycle
```

---

## 5. CapitalSession

**REQ-09** — `CapitalSession` in `infrastructure.capital.session` performs
authentication by POSTing to `POST /session` on the Capital.com REST API.
On success it stores and exposes `cst: str` and `security_token: str` (the
`X-SECURITY-TOKEN` header value).

**REQ-10** — Authentication is eager: `CapitalSession` re-authenticates at
the start of every cycle call. There is no background thread, no token-refresh
timer, and no retry branching.

**Scenario 5.1 — successful auth stores tokens**
```
Given a CapitalSession configured with valid credentials
  And the POST /session endpoint returns HTTP 200 with
    headers CST and X-SECURITY-TOKEN
When authenticate() is called
Then session.cst equals the CST header value
  And session.security_token equals the X-SECURITY-TOKEN header value
```

**Scenario 5.2 — expired/missing token triggers re-auth before request**
```
Given a CapitalSession where a previous auth produced tokens T1
  And those tokens have since expired (or were never obtained)
When a new cycle begins and authenticate() is called
Then POST /session is issued again
  And the new tokens T2 replace T1
  And subsequent API calls use T2
```

**Scenario 5.3 — auth failure raises**
```
Given POST /session returns HTTP 401 or any non-2xx status
When authenticate() is called
Then an exception is raised
  And no tokens are stored
```

---

## 6. CapitalBrokerAdapter (BrokerPort)

**REQ-11** — `CapitalBrokerAdapter` in `infrastructure.capital.broker`
implements `BrokerPort`. It depends on `CapitalSession` for authenticated
requests. It does not subclass `CapitalSession`.

**REQ-12 — Closed-candles-only contract.**
`recent_candles(symbol, count)` requests `count + 1` candles from the API and
drops the last one (the in-progress candle). It returns exactly `count` closed
candles, oldest first.

**Scenario 6.1 — strips in-progress candle**
```
Given the Capital.com candle endpoint returns N+1 candle records
  And the last record is the still-open (in-progress) candle
When recent_candles(symbol, N) is called
Then the returned sequence contains exactly N Candle objects
  And the last returned candle is NOT the in-progress candle
  And candles are ordered oldest-first
```

**Scenario 6.2 — open_position sends atomic order**
```
Given a valid CapitalSession with active tokens
  And a Signal with direction=BUY, entry_reference=1.0850,
    stop_loss=1.0830, take_profit=1.0870
When open_position("EURUSD", signal, size=0.01) is called
Then exactly one HTTP POST is made to the orders endpoint
  And the request body contains:
    epic == the configured epic string for EURUSD
    direction == "BUY"
    size == 0.01
    stopLevel == signal.stop_loss
    profitLevel == signal.take_profit
  And the method returns an OrderResult
    with order_id, filled_price, and status populated from the response
```

**Scenario 6.3 — has_open_position reflects API state**
```
Given the Capital.com positions endpoint returns at least one open position
  whose epic matches the configured EURUSD epic
When has_open_position("EURUSD") is called
Then the return value is True
```

```
Given the positions endpoint returns zero positions for the EURUSD epic
When has_open_position("EURUSD") is called
Then the return value is False
```

---

## 7. Config and MODE Guard

**REQ-13** — `src/config.py` loads all configuration from environment variables.
It exposes at minimum: `MODE` (`"demo"` | `"live"`), `SYMBOL`, `EPIC`,
`SIZE` (float), `WARMUP` (int, default 64), `TIMEFRAME` (default `"MINUTE_15"`).

**REQ-14 — Live MODE guard (hard gate).**
If `MODE == "live"` and the environment variable `I_UNDERSTAND_THIS_IS_REAL_MONEY`
is NOT set to exactly `"YES"`, the config loader raises `SystemExit` (or an
equivalent unrecoverable error) before any other component is constructed.
The process must not reach the trading loop.

**Scenario 7.1 — demo mode starts without confirmation env var**
```
Given MODE=demo and I_UNDERSTAND_THIS_IS_REAL_MONEY is unset
When Config is loaded
Then no exception is raised
  And config.mode == "demo"
```

**Scenario 7.2 — live mode without confirmation is rejected**
```
Given MODE=live and I_UNDERSTAND_THIS_IS_REAL_MONEY is unset (or != "YES")
When Config is loaded
Then SystemExit (or equivalent) is raised
  And the process does NOT reach the trading loop
```

**Scenario 7.3 — live mode with confirmation proceeds**
```
Given MODE=live and I_UNDERSTAND_THIS_IS_REAL_MONEY=YES
When Config is loaded
Then no exception is raised
  And config.mode == "live"
```

---

## 8. Entry Point Loop

**REQ-15** — `src/__main__.py` wires all dependencies (Config, CapitalSession,
CapitalBrokerAdapter, FadeStrategy, SystemClock, RunTradingCycleUseCase) and
runs a perpetual loop.

**REQ-16 — Cycle cadence.**
After each cycle the loop sleeps until the next 15-minute boundary as
determined by `ClockPort.utcnow()`. It does not use a fixed `time.sleep(900)`.

**REQ-17 — Cycle error isolation.**
A single cycle that raises an unhandled exception MUST NOT crash the loop.
The exception is logged (including traceback) and the loop continues to the
next 15-minute boundary.

**Scenario 8.1 — sleep aligns to next 15m boundary**
```
Given a FakeClock returning datetime(2024, 1, 1, 12, 07, 35, tzinfo=UTC)
When the loop computes the next-cycle sleep duration
Then the sleep target is datetime(2024, 1, 1, 12, 15, 0, tzinfo=UTC)
  And the computed sleep duration is 457 seconds (== 7*60 + 25)
```

**Scenario 8.2 — exactly on boundary sleeps to the NEXT boundary**
```
Given a FakeClock returning datetime(2024, 1, 1, 12, 15, 0, tzinfo=UTC)
When the loop computes the next-cycle sleep duration
Then the sleep target is datetime(2024, 1, 1, 12, 30, 0, tzinfo=UTC)
  And the computed sleep duration is 900 seconds
```

**Scenario 8.3 — cycle exception is swallowed and loop continues**
```
Given the use case raises RuntimeError("API timeout") during cycle N
When the loop handles the exception
Then the exception is logged with its traceback
  And the loop does NOT terminate
  And cycle N+1 is attempted at the next 15m boundary
```

---

## Non-Goals (out of scope for this spec)

- Multi-strategy or multi-symbol operation.
- WebSocket / streaming candle delivery.
- Position sizing logic beyond a fixed config constant.
- Re-implementation of any logic from `fade_strategy.py`.
- Real-money trading (live path exists but is not the purpose of this change).
- Trade management after order placement (TP/SL modification, trailing stops).
