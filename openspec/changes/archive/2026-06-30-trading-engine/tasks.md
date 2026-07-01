# Tasks: trading-engine

## Review Workload Forecast

| Metric | Estimate |
|---|---|
| Production source files (new) | 9 |
| Test files (new) | 7 |
| Estimated changed lines | ~950–1 100 |
| Exceeds 400-line budget | **Yes** |
| Chained PRs recommended | **Yes** |
| Decision needed before apply | **Yes** |

**Recommended split:**

- **PR-A** — Domain layer (entities, ports, domain adapter, application use case) + their tests. ~450 lines.
- **PR-B** — Infrastructure layer (session, broker, clock), config, entry point + their tests. ~600 lines.

Both PRs are independently shippable; PR-B depends on the domain ports defined in PR-A.

---

## Dependency notes

- Tasks within the same layer are sequential (test → implement).
- Layers themselves are sequential bottom-up: domain entities → domain ports → domain adapters → application → infrastructure → config → entry point.
- The anti-drift integration test (T-21) is independent of the infrastructure layer and can run as soon as the domain adapter is done; it is listed after the domain adapter block.
- The live smoke-test (T-31) requires user runtime inputs and is the final, gated task.

---

## PR-A — Domain + Application

### Layer 0 — Dependency fix (unblocks BrokerPort compilation)

- [x] **T-01** · Add `numpy` and `pandas` to `pyproject.toml` dependencies. (Design §4, REQ-03)

### Layer 1 — Domain Entity: OrderResult

- [x] **T-02** · Write failing tests for `OrderResult`: construction roundtrip (Scenario 1.1) and frozen-field assignment raises `AttributeError` (Scenario 1.2). (REQ-01)
- [x] **T-03** · Implement `domain/entities/order.py` — `@dataclass(frozen=True, slots=True) OrderResult(order_id, status, filled_price)`. (REQ-01, Design §2)
- [x] **T-04** · Fix the broken `OrderResult` import in `domain/ports/broker_port.py` (or wherever the forward reference exists) now that `order.py` exists. (REQ-01, Design §1)

### Layer 2 — Domain Port: ClockPort

- [x] **T-05** · Write failing tests for `ClockPort` contract via `SystemClock`: `utcnow()` is timezone-aware UTC within 2 s of wall time (Scenario 2.1); `FakeClock` returns its seeded time exactly (Scenario 2.2). (REQ-02)
- [x] **T-06** · Implement `domain/ports/clock_port.py` — `ClockPort(ABC)` with abstract `utcnow()` and `sleep()`. (REQ-02, Design §3)
- [x] **T-07** · Implement `infrastructure/capital/clock.py` — `SystemClock(ClockPort)` using `datetime.now(timezone.utc)` and `time.sleep`. (REQ-02, Design §3)
- [x] **T-08** · Implement `FakeClock` test double (in `tests/fakes/` or `tests/conftest.py`) — seeded `utcnow()`, records sleep calls. (REQ-02, Design §10.1)

### Layer 3 — Domain Adapter: FadeStrategy

- [x] **T-09** · Write failing tests for `FadeStrategy.evaluate`:
  - fewer than 64 candles → `None`, no helpers called (Scenario 3.1, REQ-04)
  - 64 candles where bar `n-2` is NOT aggressive → `None` (Scenario 3.2)
  - 64 candles where bar `n-2` IS aggressive → correct `Signal` with `entry_reference == candles[-1].close`, fade direction, `|sl - entry| == 2*ATR`, `|tp - entry| == RR*2*ATR`, Signal ordering invariant (Scenario 3.3)
  - zero/NaN ATR at the episode bar → `None` (Design §4.5)
  (REQ-03, REQ-04, Design §4)
- [x] **T-10** · Implement `domain/adapters/fade_strategy.py` — `FadeStrategy(StrategyPort)` calling `_aggressive_episodes`, `compute_atr`, and importing all constants from the frozen research lib; `required_candles` property returns `WARMUP_BARS` (64). (REQ-03, REQ-04, D1, D2, D8, D9)

### Layer 3 — Anti-drift Integration Test

- [x] **T-11** · Write the anti-drift integration test (`tests/integration/test_fade_strategy_anti_drift.py`):
  - Load a real EURUSD 15m fixture (CSV from the research dataset).
  - Run `simulate_fades` to get the full backtest trade list.
  - For each backtest entry, build the live window and assert `FadeStrategy.evaluate` produces a `Signal` with matching direction and `stop_loss`/`take_profit` distances (within 1e-6).
  - For a sample of non-entry windows assert `evaluate` returns `None`.
  - Any disagreement on direction, SL distance, or TP distance FAILS the build.
  (REQ-05, Scenario 3.4, Design §10.3)

### Layer 4 — Application: RunTradingCycleUseCase

- [x] **T-12** · Write failing tests for `RunTradingCycleUseCase.execute` with `FakeBroker` and stub `StrategyPort`:
  - `has_open_position` → `True`: no candle fetch, no evaluate, no placement (Scenario 4.1, REQ-07)
  - no signal → fetches `required_candles` candles, evaluates, no placement (Scenario 4.2, REQ-08)
  - signal present → `open_position(symbol, signal, size)` called exactly once, returns `OrderResult` (Scenario 4.3)
  (REQ-06, REQ-07, REQ-08)
- [x] **T-13** · Implement `application/trading_cycle.py` — `RunTradingCycleUseCase` depending only on `BrokerPort`, `StrategyPort`, `symbol`, `size`, and a logger. (REQ-06, REQ-07, REQ-08, Design §5)

---

## PR-B — Infrastructure + Config + Entry Point

### Layer 5 — Infrastructure: CapitalSession

- [x] **T-14** · Implement `FakeHttp` transport double (in `tests/fakes/`) — a `requests.Session` stand-in that returns canned `Response` objects with configurable status code, headers, and JSON body. (Design §10.4)
- [x] **T-15** · Write failing tests for `CapitalSession` using `FakeHttp`:
  - `authenticate()` on HTTP 200 stores `cst` and `security_token` from response headers (Scenario 5.1, REQ-09)
  - re-auth on next cycle replaces old tokens (Scenario 5.2, REQ-10)
  - non-2xx response raises `AuthenticationError`, no tokens stored (Scenario 5.3)
  (REQ-09, REQ-10)
- [x] **T-16** · Implement `infrastructure/capital/session.py` — `CapitalSession` with `authenticate()` (eager `POST /session`) and `tokens()`. Raises `AuthenticationError` on non-2xx. (REQ-09, REQ-10, Design §6)

### Layer 5 — Infrastructure: CapitalBrokerAdapter

- [x] **T-17** · Write failing tests for `CapitalBrokerAdapter` using `FakeHttp`:
  - `recent_candles(symbol, N)` given `N+1` records returns exactly `N` candles, oldest-first, last (in-progress) candle stripped (Scenario 6.1, REQ-12)
  - malformed OHLC record in response raises via `Candle` invariants
  - `open_position` posts to `/positions` with correct `epic`, `direction`, `size`, `stopLevel`, `profitLevel`; resolves `/confirms`; accepted status returns `OrderResult` (Scenario 6.2)
  - rejected `dealStatus` raises `OrderRejectedError`
  - `has_open_position` returns `True` when matching epic present, `False` when absent (Scenario 6.3)
  (REQ-11, REQ-12, Design §7)
- [x] **T-18** · Implement `infrastructure/capital/broker.py` — `CapitalBrokerAdapter(BrokerPort)` implementing `recent_candles`, `open_position` (atomic SL/TP via `stopLevel`/`profitLevel`, two-step confirm), and `has_open_position`. (REQ-11, REQ-12, D5, D6, Design §7)

### Layer 6 — Config

- [x] **T-19** · Write failing tests for `config.py` MODE guard:
  - `MODE=demo`, `I_UNDERSTAND_THIS_IS_REAL_MONEY` unset → loads without exception, `config.mode == "demo"` (Scenario 7.1)
  - `MODE=live`, confirmation unset → `SystemExit` raised before trading loop (Scenario 7.2, REQ-14)
  - `MODE=live`, `I_UNDERSTAND_THIS_IS_REAL_MONEY=YES` → loads, `config.mode == "live"` (Scenario 7.3)
  (REQ-13, REQ-14)
- [x] **T-20** · Implement `src/config.py` — loads all env vars (`MODE`, `SYMBOL`, `EPIC`, `SIZE`, `WARMUP`, `TIMEFRAME`, and credentials), enforces the live-money guard via `_resolve_base_url`, exposes `Config` frozen dataclass, includes startup assertion `warmup_bars >= max(L_FROZEN, ATR_PERIOD)`. (REQ-13, REQ-14, D8, Design §8)

### Layer 7 — Entry Point

- [x] **T-21** · Write failing tests for the loop utilities in `__main__`:
  - `seconds_until_next_boundary` at 12:07:35 UTC → 445 s (Scenario 8.1 — spec typo corrected: 7*60+25=445, not 457)
  - `seconds_until_next_boundary` exactly at 12:15:00 UTC → 900 s (Scenario 8.2)
  - loop with a use case that raises `RuntimeError`: logs exception, does NOT terminate, advances to next cycle (Scenario 8.3, REQ-17)
  (REQ-15, REQ-16, REQ-17)
- [x] **T-22** · Implement `src/__main__.py` — composition root (`build_use_case`), `seconds_until_next_boundary` pure function, `run_forever` loop with 15-minute boundary alignment (`clock.utcnow()` + `seconds_until_next_boundary` + settle delay), per-cycle error isolation (`try/except Exception`). (REQ-15, REQ-16, REQ-17, D3, D4, D7, Design §9)

---

## Final Task — Live Smoke-Test (requires runtime inputs)

- [ ] **T-23** · **[REQUIRES RUNTIME INPUTS — GATED]** Run a live demo smoke-test against the Capital.com demo environment:
  - Set `MODE=demo`, provide `IDENTIFIER`, `PASSWORD`, `API_KEY`, `EPIC` (e.g. `CS.D.EURUSD.MINI.IP`), and confirm lot semantics (`SIZE` in base-currency units, not MT lots).
  - Verify the bot authenticates, fetches candles, evaluates the strategy, and either skips (no signal / open position) or logs a placed order without error.
  - **Do not run with `MODE=live`** unless `I_UNDERSTAND_THIS_IS_REAL_MONEY=YES` is explicitly set.
  (REQ-09 through REQ-17, all scenarios)
