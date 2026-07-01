# Design: trading-engine

## 0. Architectural Stance (locked)

Hexagonal / ports-and-adapters, one strategy and one provider per process.

```
__main__ (composition root)
   │ wires
   ▼
controller/loop ──> RunTradingCycleUseCase ──> ports (StrategyPort, BrokerPort, ClockPort)
                          (application)              ▲              ▲
                                                     │ implements   │ implements
                          FadeStrategy (domain/adapters)   CapitalBrokerAdapter,
                                                            SystemClock (infrastructure)
```

Dependency rule (inward-only):
- `domain/entities`, `domain/ports` import nothing outward. Pure.
- `domain/adapters/fade_strategy.py` is the ONE deliberate exception to "domain imports nothing": it imports the frozen research helpers (`research.lib.*`, numpy). This is intentional and load-bearing — it is the anti-drift guarantee. numpy/pandas leakage is contained INSIDE this adapter; it returns only domain `Signal`. No numpy crosses the port boundary.
- `application` depends on ports only (DIP). It never imports infrastructure or the research lib.
- `infrastructure/capital/*` imports domain ports + entities + `requests`. It is the only place `requests` lives.

Uncle Bob gates applied throughout: SRP per module, small functions, exceptions over return codes, no nulls where a value is mandatory (Signal-or-None is the only intentional optional, and it is a domain modeling decision, not an error channel).

---

## 1. Module / Package Layout

Final tree under `capital_integration/src/`:

```
src/
├── domain/
│   ├── entities/
│   │   ├── candle.py          (exists) Candle VO + OHLC invariants
│   │   ├── direction.py       (exists) Direction enum + .opposite
│   │   ├── signal.py          (exists) Signal VO + ordering invariant
│   │   └── order.py           (NEW)    OrderResult VO — unblocks BrokerPort import
│   ├── ports/
│   │   ├── strategy_port.py   (exists) StrategyPort ABC
│   │   ├── broker_port.py     (exists) BrokerPort ABC
│   │   └── clock_port.py      (NEW)    ClockPort ABC — utcnow()
│   └── adapters/
│       └── fade_strategy.py   (NEW)    FadeStrategy(StrategyPort) — frozen-helper bridge
├── application/
│   └── trading_cycle.py       (NEW)    RunTradingCycleUseCase — orchestrates one cycle
├── infrastructure/
│   └── capital/
│       ├── session.py         (NEW)    CapitalSession — auth + eager re-auth
│       ├── broker.py          (NEW)    CapitalBrokerAdapter(BrokerPort)
│       └── clock.py           (NEW)    SystemClock(ClockPort)
├── config.py                  (NEW)    env load, MODE guard, trade params (single source of truth)
└── __main__.py                (NEW)    DI composition root + sleep loop
```

Single responsibility per module:

| Module | Responsibility (one thing) |
|---|---|
| `entities/order.py` | Immutable record of what the broker returned for an order placement. |
| `ports/clock_port.py` | Abstract "current UTC time" so scheduling is deterministic in tests. |
| `adapters/fade_strategy.py` | Translate a `Sequence[Candle]` into a fade `Signal` by calling the frozen helpers — nothing else. |
| `application/trading_cycle.py` | Sequence one trading cycle across ports. No broker/HTTP/strategy specifics. |
| `infrastructure/capital/session.py` | Obtain and hold valid Capital.com auth tokens; re-auth on demand. |
| `infrastructure/capital/broker.py` | Map BrokerPort methods to Capital.com REST calls; strip in-progress candle. |
| `infrastructure/capital/clock.py` | Real wall-clock implementation of ClockPort. |
| `config.py` | Load env once, enforce the live-money guard, expose validated trade params. |
| `__main__.py` | Build the object graph and run the 15-minute aligned loop with per-cycle error isolation. |

---

## 2. OrderResult shape

`domain/entities/order.py`:

```python
@dataclass(frozen=True, slots=True)
class OrderResult:
    order_id: str
    status: str
    filled_price: float
```

- `order_id: str` — Capital.com `dealReference` (returned by `POST /positions`) or the `dealId` resolved from the confirmation endpoint. We store the broker's stable identifier as-is.
- `status: str` — the deal status string from the confirm response (e.g. `"OPEN"`, `"ACCEPTED"`, `"REJECTED"`). Kept as a raw broker string in v1; not modeled as an enum because the forward-test wants to OBSERVE the real vocabulary before constraining it (OCP — promote to enum later without breaking callers).
- `filled_price: float` — the actual fill `level` from the position confirmation. This is the value the forward-test compares against `signal.entry_reference` to quantify entry variance (Risk #2). Mandatory float, never None — if Capital.com does not return a fill level the adapter raises rather than fabricating one.

How the broker adapter builds it: `POST /positions` returns a `dealReference`; the adapter then calls `GET /confirms/{dealReference}` to obtain `{dealStatus, level, dealId}` and constructs `OrderResult(order_id=dealId, status=dealStatus, filled_price=level)`. If the confirm reports a non-accepted status, the adapter raises a domain-level `OrderRejectedError` (see §6 error mapping) rather than returning a "bad" OrderResult — exceptions over error codes.

No `__post_init__` invariant beyond type expectations: an OrderResult only exists when the broker accepted something, so there is no illegal interior state to guard.

---

## 3. ClockPort + SystemClock

`domain/ports/clock_port.py`:

```python
class ClockPort(ABC):
    @abstractmethod
    def utcnow(self) -> datetime:
        """Timezone-aware current UTC time."""
    @abstractmethod
    def sleep(self, seconds: float) -> None:
        """Block for `seconds`."""
```

Rationale for putting `sleep` on the clock too: the loop's only two time interactions are "what time is it" and "wait until the next boundary". Injecting both behind ONE port makes the entire scheduler deterministic — a `FakeClock` returns scripted timestamps and records sleep calls without ever blocking the test suite. If `sleep` lived in `__main__` directly, the boundary math would be testable but the wait would not, and the loop could not be driven in a unit test.

`infrastructure/capital/clock.py`:

```python
class SystemClock(ClockPort):
    def utcnow(self) -> datetime:
        return datetime.now(timezone.utc)
    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
```

Next-boundary computation (pure function, lives next to the loop, fully unit-tested):

```python
def seconds_until_next_boundary(now: datetime, period_minutes: int) -> float:
    period = period_minutes * 60
    epoch_secs = now.timestamp()
    return period - (epoch_secs % period)
```

The loop calls `clock.utcnow()` → `seconds_until_next_boundary(now, 15)` → `clock.sleep(...)`, then adds a small fixed settle delay (e.g. +5s, a config constant `CANDLE_SETTLE_SECONDS`) so the broker has flushed the just-closed candle before we fetch. Computing from `utcnow()` each iteration is self-correcting against drift — we never accumulate sleep error because every boundary is recomputed from absolute time.

---

## 4. FadeStrategy.evaluate algorithm (the bridge)

This is the correctness core. It must reproduce, for the LAST CLOSED bar, exactly the decision `simulate_fades` would make — by calling the SAME frozen functions, never re-implementing them.

### 4.1 Index semantics (critical, easy to get wrong)

In `simulate_fades`, a run endpoint at `r.bar_idx` produces an entry at `entry_i = r.bar_idx + 1` (the NEXT bar's open). So the bar the trade actually enters on is `bar_idx + 1`.

Live, the broker adapter hands us the last `required_candles` CLOSED candles, oldest first, with the in-progress candle already stripped. Index the numpy arrays `0..n-1`. The last closed bar is index `n-1`. For a fresh, actionable entry on THIS cycle, the run endpoint the backtest would fade must be the bar BEFORE the last closed bar:

- run endpoint `= n-2`
- backtest entry bar `= n-1` (the bar that just closed)

So FadeStrategy fires iff bar `n-2` is an aggressive episode endpoint per the frozen gate. `entry_reference` is then locked to `c[n-1]` (close of the last closed bar) — the proposal's "signal-bar close". Live market fill happens on the next tick; the ~1–3 pip gap vs backtest's `o[n-1]` open is the accepted, logged variance (Risk #2).

### 4.2 Algorithm

```
evaluate(candles):
  if len(candles) < required_candles: return None        # not enough warm-up
  build numpy o,h,l,c arrays (float) from candles, oldest-first
  build a pandas DataFrame with columns open/high/low/close   # identify_runs needs df + close
  atr = compute_atr(h, l, c, ATR_PERIOD)                 # frozen ATR, recursive
  episodes = _aggressive_episodes(df, o, h, l, c, atr)   # SEE 4.3 — reuse frozen gate
  endpoint = n - 2
  if no episode has bar_idx == endpoint: return None
  r = that episode
  atr_e = atr[endpoint]
  if atr_e <= 0 or isnan(atr_e): return None             # mirrors backtest guard
  fade = -r.direction                                    # +1 long fade, -1 short fade
  entry_reference = float(c[n-1])                         # signal-bar close (locked)
  sl_dist = SL_ATR_MULT * atr_e                          # = 2 * ATR
  tp_dist = RR * sl_dist                                  # = sl_dist (RR=1.0)
  if fade == 1:   # long fade -> BUY
      direction = Direction.BUY
      stop_loss   = entry_reference - sl_dist
      take_profit = entry_reference + tp_dist
  else:           # short fade -> SELL
      direction = Direction.SELL
      stop_loss   = entry_reference + sl_dist
      take_profit = entry_reference - tp_dist
  return Signal(direction, entry_reference, stop_loss, take_profit)
```

### 4.3 Reusing the frozen aggressiveness gate — single source of truth

The gate that turns runs into "aggressive episodes" lives in `fade_strategy._aggressive_episodes`. We MUST NOT copy its body. Two acceptable options, in order of preference:

1. **Preferred:** call `fade_strategy._aggressive_episodes(df, o, h, l, c, atr)` directly. It is causal and pure; passing the live window reproduces the episode list the backtest computes over the same window. The leading underscore signals "internal", but importing it is the lesser evil versus duplicating the `MIN_DISP_ATR` / `MIN_STRAIGHTNESS` / dedup logic. We accept the private import as a deliberate anti-drift decision.
2. **Fallback (only if the frozen module is later refactored to not expose it):** call the public `identify_runs` + `extract_trajectory_features` and re-apply the gate — but then the thresholds MUST be imported from the frozen module (`fade_strategy.MIN_DISP_ATR`, etc.), never redeclared here.

The adapter imports every constant it needs FROM the frozen module:

```python
from research.lib.fade_strategy import (
    _aggressive_episodes, ATR_PERIOD, SL_ATR_MULT, RR,
)
from research.lib.runs import compute_atr
```

ZERO numeric strategy constants are written in `fade_strategy.py` (the adapter). Every threshold, period, multiplier, and RR is imported. This is the explicit guard against the duplication that would silently drift live from backtest.

### 4.4 required_candles

```python
@property
def required_candles(self) -> int:
    return WARMUP_BARS    # 64, imported from config (see §8)
```

Burn-in need is `max(L_FROZEN, ATR_PERIOD) = 32`; 64 gives the recursive ATR ample convergence and matches the IC Markets `WARMUP_BARS`. We surface it as one constant, not two.

### 4.5 Signal invariant safety

The `Signal.__post_init__` enforces `stop_loss < entry < take_profit` (BUY) / `take_profit < entry < stop_loss` (SELL). Because `atr_e > 0` is guaranteed before construction, `sl_dist > 0` and `tp_dist > 0`, so the arithmetic above ALWAYS produces strictly-ordered prices. The `atr_e <= 0 or isnan` early-return is therefore not just a backtest mirror — it is the precondition that makes the Signal constructor un-raisable. The design mandates that guard; without it a zero/NaN ATR would build `stop_loss == entry` and the constructor would throw inside a live cycle.

`entry_reference = c[n-1]` is a real traded close, strictly inside that bar's `[low, high]`, so it is a sane finite anchor for the ordering check.

---

## 5. RunTradingCycleUseCase

`application/trading_cycle.py`:

```python
class RunTradingCycleUseCase:
    def __init__(self, broker: BrokerPort, strategy: StrategyPort,
                 symbol: str, size: float, logger):
        ...

    def execute(self) -> OrderResult | None:
        if self.broker.has_open_position(self.symbol):
            self.logger.info("position already open; skipping placement")
            return None
        candles = self.broker.recent_candles(self.symbol, self.strategy.required_candles)
        signal = self.strategy.evaluate(candles)
        if signal is None:
            return None
        result = self.broker.open_position(self.symbol, signal, self.size)
        self.logger.info(
            "order placed", extra={"entry_reference": signal.entry_reference,
                                   "filled_price": result.filled_price})
        return result
```

- Depends ONLY on ports (`BrokerPort`, `StrategyPort`) + plain config values (`symbol`, `size`) + a logger. DIP satisfied; no infrastructure, no research lib, no HTTP.
- Orchestration order is exactly: guard → fetch → evaluate → place. The guard runs FIRST so we never even fetch/evaluate when a position is open (cheapest correct path, and it removes any chance of stacking).
- Sizing is injected (`size: float`), matching `open_position(symbol, signal, size)`. No sizing logic in the use case — it is a pass-through of a config constant.
- Returns `OrderResult | None`: `None` means "nothing to do this cycle" (open position or no signal), which is a normal domain outcome, not an error. Real failures (auth, HTTP, rejection) surface as exceptions from the broker adapter and propagate to the loop's per-cycle isolation (§9).
- Logging `entry_reference` vs `filled_price` here is the instrumentation Risk #2 mandates.

---

## 6. CapitalSession

`infrastructure/capital/session.py`. Single responsibility: produce valid auth tokens.

Auth flow (Capital.com REST):
1. `POST /session` with headers `X-CAP-API-KEY: <api_key>` and JSON `{identifier, password}`.
2. On 200, capture response headers `CST` and `X-SECURITY-TOKEN`, plus `utcnow()` as `authenticated_at`.
3. Expose `tokens() -> SessionTokens(cst, security_token)`.

Eager re-auth contract (locked decision):

```python
class CapitalSession:
    def __init__(self, http, base_url, api_key, identifier, password, clock):
        ...
    def authenticate(self) -> SessionTokens:
        # always performs a fresh POST /session, stores tokens + authenticated_at
    def tokens(self) -> SessionTokens:
        # returns last-authenticated tokens; raises if never authenticated
```

The use case / broker do not manage expiry. The LOOP calls `session.authenticate()` at the start of every cycle (eager re-auth). Capital.com sessions expire after ~10 minutes of inactivity; on a 15-minute cadence a lazily-reused token would already be dead, so re-authenticating every cycle is the simplest correct option — idempotent, zero retry branching, no background keep-alive thread. The ~100ms cost is negligible on a 15-min tick.

Why a 10-min TTL motivates eager (not lazy) re-auth: with a 15-min poll, the token is GUARANTEED stale by next cycle. Lazy-on-401 would 401 on essentially every first call, forcing retry logic on each broker method. Eager re-auth front-loads one deterministic call and keeps every broker method single-path.

Error mapping (exceptions, not codes):
- Non-2xx on `POST /session` → raise `AuthenticationError` (infrastructure exception) carrying status + body snippet. Never return a sentinel.
- Network/transport failure → let `requests` exceptions propagate, or wrap into an infra `BrokerUnavailableError` for a uniform catch in the loop.

`SessionTokens` is a small frozen dataclass `(cst: str, security_token: str)` so the broker receives a typed value, not a dict.

---

## 7. CapitalBrokerAdapter

`infrastructure/capital/broker.py`, implements `BrokerPort`. Holds a `CapitalSession`, `base_url`, an `epic` map, and the configured timeframe/resolution. Every method first pulls `session.tokens()` and sets `CST` / `X-SECURITY-TOKEN` headers (the loop already re-authenticated this cycle).

### 7.1 recent_candles(symbol, count) -> Sequence[Candle]

- Resolve `epic = epic_for(symbol)` (e.g. `EURUSD -> CS.D.EURUSD.MINI.IP`, from config map).
- `GET /prices/{epic}?resolution=MINUTE_15&max={count + 1}` — request ONE extra candle because the most recent one is the in-progress (still-open) candle.
- Parse each price record into a `Candle`. Capital.com returns bid/ask OHLC objects; the adapter uses a single, documented price side (bid) consistently to mirror a single price series, then constructs `Candle(timestamp, open, high, low, close)`.
- **In-progress-candle stripping:** drop the LAST element of the returned series (the open candle) and return the remaining `count`, oldest-first. A unit test pins this so the strategy NEVER sees an unclosed bar. If Capital.com returns fewer than `count + 1`, the adapter returns what it has after stripping and the strategy's own length guard handles warm-up.
- The Candle constructor's OHLC invariants act as a validation gate on broker data; a malformed candle raises rather than silently entering the strategy.

### 7.2 open_position(symbol, signal, size) -> OrderResult

- `epic = epic_for(symbol)`.
- `direction = "BUY" if signal.direction is Direction.BUY else "SELL"`.
- `POST /positions` with body:
  ```json
  {
    "epic": epic,
    "direction": direction,
    "size": size,
    "stopLevel": signal.stop_loss,
    "profitLevel": signal.take_profit,
    "guaranteedStop": false
  }
  ```
  Atomic SL/TP attachment via `stopLevel` / `profitLevel` in the SAME create call — SL and TP are part of position creation, never a follow-up request, so there is no window where the position is naked.
- Response yields `dealReference`; call `GET /confirms/{dealReference}` to resolve `{dealId, dealStatus, level}`.
- If `dealStatus` is accepted/open → return `OrderResult(order_id=dealId, status=dealStatus, filled_price=level)`.
- If rejected → raise `OrderRejectedError(reason)`. The use case does not branch on a code; the loop isolates it.
- `size` is passed straight through (config constant). Capital.com `size` is base-currency units, not MT lots — that semantic is a config/verification concern (Risk #3), not adapter logic.

### 7.3 has_open_position(symbol) -> bool

- `GET /positions`; resolve `epic = epic_for(symbol)`; return `True` iff any open position's `epic` matches. Pure read; no side effects.

### 7.4 epic mapping

A small `dict[str, str]` from config (`{"EURUSD": "<epic>"}`). `epic_for` raises `UnknownSymbolError` on a miss rather than returning None — fail loud, never place an order against a guessed epic.

---

## 8. config.py

Responsibilities: load env once, enforce the MODE guard, expose validated trade params. Single source of truth for everything EXCEPT frozen strategy constants, which are imported from the research lib.

```python
load_dotenv()

MODE = os.environ.get("MODE", "demo").lower()
REAL_MONEY_ACK = os.environ.get("I_UNDERSTAND_THIS_IS_REAL_MONEY", "")

def _resolve_base_url(mode) -> str:
    if mode == "live":
        if REAL_MONEY_ACK != "YES":
            raise SystemExit("Refusing live trading without explicit acknowledgement")
        return LIVE_BASE_URL
    return DEMO_BASE_URL

@dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str
    identifier: str
    password: str
    symbol: str = "EURUSD"
    epics: Mapping[str, str] = ...        # {"EURUSD": "<epic>"}
    timeframe: str = "MINUTE_15"
    trade_size: float = 0.01
    warmup_bars: int = 64
    candle_settle_seconds: int = 5
    poll_minutes: int = 15
```

MODE guard logic: live path is UNREACHABLE unless `MODE=live` AND `I_UNDERSTAND_THIS_IS_REAL_MONEY=YES`; otherwise `_resolve_base_url` hard-exits (proven IC Markets pattern). Default mode is demo.

Frozen strategy params — single source of truth rule: `config.py` does NOT redeclare `L_FROZEN`, `ATR_PERIOD`, `MIN_DISP_ATR`, `MIN_STRAIGHTNESS`, `SL_ATR_MULT`, `RR`, `DIR_THRESHOLD_FROZEN`, or `TIME_STOP_BARS`. Those live ONLY in `research.lib.fade_strategy` and are imported by the adapter. `WARMUP_BARS=64` is an EXECUTION concern (how much history to fetch), not a strategy threshold, so it legitimately lives in config — but it must be `>= max(L_FROZEN, ATR_PERIOD)`; a startup assertion `assert config.warmup_bars >= max(L_FROZEN, ATR_PERIOD)` ties the two together so the execution constant can never silently drop below the strategy's burn-in.

Missing required env (`api_key`, `identifier`, `password`, epic) → raise at construction. Fail at startup, never mid-cycle.

---

## 9. __main__ wiring

`src/__main__.py` is the composition root — the ONLY place concrete classes are instantiated and the dependency graph is assembled.

```python
def build_use_case(config, http, clock) -> RunTradingCycleUseCase:
    session = CapitalSession(http, config.base_url, config.api_key,
                             config.identifier, config.password, clock)
    broker  = CapitalBrokerAdapter(session, config.base_url, config.epics, config.timeframe)
    strategy = FadeStrategy()
    return RunTradingCycleUseCase(broker, strategy, config.symbol, config.trade_size, logger), session

def run_forever(config, use_case, session, clock):
    while True:
        wait = seconds_until_next_boundary(clock.utcnow(), config.poll_minutes)
        clock.sleep(wait + config.candle_settle_seconds)
        try:
            session.authenticate()        # eager re-auth per cycle
            use_case.execute()
        except Exception:                 # per-cycle isolation
            logger.exception("cycle failed; continuing to next boundary")
```

- DI composition root: builds session → broker → strategy → use case. `requests.Session` (the HTTP transport) is created here and injected, so it can be replaced by a double in tests.
- Sleep loop aligned to the 15-min boundary via `seconds_until_next_boundary` + a settle delay so the just-closed candle is available before fetch.
- Per-cycle error isolation: ANY exception in a cycle (auth, HTTP, rejection, malformed candle) is logged and swallowed; the process survives to the next boundary. A single bad cycle never kills a multi-day forward test. This is the deliberate boundary where exceptions stop propagating — everything below raises, the loop is the catch-all.
- Eager re-auth is here, not in the broker, keeping broker methods single-path.

---

## 10. Testing strategy (TDD, tests-first)

Strict TDD Mode is active. Every production file gets a failing test first.

### 10.1 Domain unit tests (fakes, no I/O)

- `OrderResult`: constructs and is frozen.
- `Signal` ordering: already enforced; FadeStrategy tests rely on it.
- `FadeStrategy.evaluate` with hand-built `Candle` sequences:
  - too-few candles → None.
  - a window whose bar `n-2` is NOT an aggressive endpoint → None.
  - a window whose bar `n-2` IS an aggressive endpoint → a `Signal` with `entry_reference == candles[-1].close`, correct fade direction, `stop_loss`/`take_profit` at `±2*ATR`/`±RR*2*ATR`, ordering invariant satisfied.
  - zero/NaN ATR path → None (proves the Signal constructor can never raise).
- `seconds_until_next_boundary`: parametrized over times within a 15-min window → exact remaining seconds; on a boundary → full period.

### 10.2 Application unit tests (fake ports + fake clock)

- `FakeBroker` and a stub `StrategyPort`:
  - open position exists → `execute()` returns None, never fetches/evaluates/places.
  - no signal → fetches + evaluates, returns None, no placement.
  - signal present → calls `open_position(symbol, signal, size)` exactly once, returns its `OrderResult`.
- `FakeClock` drives the loop's boundary math without real sleeping (records sleep durations).

### 10.3 Anti-drift integration test (THE critical test, Risk #1)

- Load a real EURUSD 15m candle history (a fixture CSV / the research dataset).
- Run `simulate_fades(df, cost_pct)` to get the full backtest trade list.
- For each index `i` where the backtest has a trade with `entry_idx == i`, build the live window = candles `[i-1-WARMUP+1 .. i-1]` (so the run endpoint `i-1` is the live `n-2`), feed it to `FadeStrategy.evaluate`, and assert:
  - a Signal IS produced,
  - its faded direction matches the backtest trade's `direction`,
  - its `stop_loss`/`take_profit` distances equal the backtest's `sl_dist`/`tp_dist` (within float tolerance) computed from the SAME `atr[run_end]`.
- Also assert the converse on a sample of non-entry windows: `evaluate` returns None where the backtest has no entry at that bar.
- If adapter and `simulate_fades` disagree on a shared window, the test FAILS — this is the build-breaking drift guard the proposal mandates. (Entry-PRICE differs by design — backtest `o[n-1]` vs live `c[n-1]` — so the test compares DECISION + direction + SL/TP distances, not the absolute entry price.)

### 10.4 Infrastructure tests (fake HTTP transport)

- Inject a fake `http` (a `requests.Session` double) returning canned Capital.com JSON.
- `CapitalSession.authenticate`: posts to `/session`, captures `CST`/`X-SECURITY-TOKEN` from headers; non-2xx → `AuthenticationError`.
- `CapitalBrokerAdapter.recent_candles`: given `count+1` price records, returns exactly `count` Candles oldest-first with the LAST (open) candle stripped — pinned test. Malformed OHLC → raises via Candle invariants.
- `open_position`: posts `/positions` with `stopLevel`/`profitLevel` set atomically; resolves `/confirms`; accepted → correct `OrderResult`; rejected status → `OrderRejectedError`.
- `has_open_position`: epic match logic both true and false.

### 10.5 Duplication watch (mandated)

Reviewers MUST reject any PR that redeclares a frozen strategy constant in `fade_strategy.py` (the adapter) or `config.py`. The grep gate: no literal `5.6`, `0.37`, `0.60`, `2.0`(as SL mult), `32`, `14`(as ATR period) in the adapter or config — all must be imported names from `research.lib.fade_strategy`. `WARMUP_BARS=64` is the only execution constant and is asserted `>= max(L_FROZEN, ATR_PERIOD)` at startup.

---

## 11. ADR-style decisions

| # | Decision | Rationale | Rejected alternative |
|---|---|---|---|
| D1 | FadeStrategy imports `_aggressive_episodes` + constants from the frozen module | Zero logic drift; the live path asks the SAME code the backtest asks | Re-implement the gate in the adapter — silent drift, the single biggest risk |
| D2 | Run endpoint = `n-2`, entry_reference = `c[n-1]` | Mirrors backtest `entry_i = bar_idx+1`; the last closed bar is the entry bar | Endpoint = `n-1` (would fire a cycle late and never match the backtest entry bar) |
| D3 | `ClockPort.sleep` lives on the port, not in `__main__` | Whole scheduler becomes deterministic; loop is unit-testable | Real `time.sleep` in the loop — untestable wait, slow/flaky tests |
| D4 | Eager re-auth every cycle in the loop | 10-min TTL guarantees staleness at 15-min cadence; single-path broker methods | Lazy-on-401 (retry branching everywhere) / keep-alive thread (extra concurrency) |
| D5 | Atomic SL/TP via `stopLevel`/`profitLevel` on `POST /positions` | No naked-position window; one network round-trip for the protected order | Place then attach SL/TP (a window of unprotected exposure) |
| D6 | `OrderResult.status` is a raw broker string in v1 | Forward-test observes the real status vocabulary before constraining it | Premature enum that may not match Capital.com's actual values |
| D7 | Per-cycle try/except in the loop is the only catch-all | A bad cycle never kills a multi-day run; everything below raises | Catching inside the use case (muddies orchestration with error policy) |
| D8 | `WARMUP_BARS` in config, strategy thresholds in the frozen lib | Execution-vs-strategy separation; one source of truth each, tied by a startup assert | Duplicating thresholds in config (drift) or hardcoding warmup in the adapter |
| D9 | numpy/pandas confined inside the FadeStrategy adapter | Domain stays pure at the PORT boundary; only Signal crosses out | Passing numpy arrays through ports (leaks infra detail into application) |
