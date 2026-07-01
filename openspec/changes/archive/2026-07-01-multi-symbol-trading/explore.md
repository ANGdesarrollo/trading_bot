# Exploration: multi-symbol-trading

## Current State

The bot runs ONE symbol per process, hard-wired at startup. Key facts discovered:

**Config** (`operator/src/config.py`):
- `Config.symbol: str` — single symbol (default "EURUSD")
- `Config.epics: dict[str, str]` — already a dict (`{symbol: epic}`), built as `{symbol: epic}` in `load_config()`. The dict shape was introduced in a prior refactor; only one entry exists today.
- `Config.trade_size: float` — single scalar, shared across all symbols

**CapitalBrokerAdapter** (`operator/src/infrastructure/capital/broker.py`):
- Constructor takes `epics: dict[str, str]`, stored as `self._epics`. Already multi-symbol-capable at the infrastructure level.
- All three methods (`recent_candles`, `open_position`, `has_open_position`) take `symbol: str` as a parameter and resolve to epic via `self._epic_for(symbol)`.
- The broker adapter is ALREADY symbol-agnostic by design — it just needs more entries in `epics`.

**RunTradingCycleUseCase** (`operator/src/application/trading_cycle.py`):
- Constructor takes `symbol: str` and `size: float` — baked in at construction.
- `execute()` uses `self._symbol` and `self._size` throughout: `has_open_position(self._symbol)`, `recent_candles(self._symbol, ...)`, `open_position(self._symbol, signal, self._size)`.
- The use case is SINGLE-SYMBOL: it represents one symbol's trading cycle.

**`__main__.py`**:
- `build_use_case()` creates ONE use case for ONE symbol, passing `config.symbol` and `config.trade_size`.
- `run_forever()` calls `use_case.execute()` once per boundary — the single-symbol assumption is here.

**CapitalSession** (`operator/src/infrastructure/capital/session.py`):
- Account-level auth only. Fully symbol-agnostic. One session serves all symbols.

**ReconcileClosedTradesUseCase** (`operator/src/application/reconcile_closed_trades.py`):
- Iterates `journal.open_entries()` by `deal_id`, not by symbol. Already symbol-agnostic. Per-entry try/except isolation already exists.

**JournalEntry** (`operator/src/domain/entities/journal.py`):
- Has `symbol: str` field. DB insert already includes it. Symbol column is already present — no migration needed.

**BrokerPort** (`operator/src/domain/ports/broker_port.py`):
- All three abstract methods take `symbol: str`. The port is already multi-symbol-capable.

## Where the Single-Symbol Assumption Lives

1. `config.py` `load_config()`: reads single `SYMBOL` and `EPIC` env vars, builds single-entry `epics` dict
2. `config.py` `Config`: `symbol: str` (scalar) and `trade_size: float` (scalar, not per-symbol)
3. `__main__.py` `build_use_case()`: passes `symbol=config.symbol` and `size=config.trade_size` to one use case
4. `__main__.py` `run_forever()`: calls `use_case.execute()` once — assumes one use case
5. `RunTradingCycleUseCase.__init__`: bakes in `self._symbol` and `self._size`

Everything else (broker adapter, session, journal, reconciler, BrokerPort) is already multi-symbol-capable.

## Affected Areas

- `operator/src/config.py` — replace scalar `symbol`/`trade_size` with per-symbol config list; replace single `EPIC` env var
- `operator/src/__main__.py` — `build_use_case()` -> build N use cases; `run_forever()` -> iterate N use cases per boundary
- `operator/src/application/trading_cycle.py` — NO change needed (already parameterized per symbol at construction)
- `operator/src/infrastructure/capital/broker.py` — NO change needed (already multi-symbol)
- `operator/src/domain/ports/broker_port.py` — NO change needed
- `operator/src/domain/entities/journal.py` — NO change needed
- `operator/src/infrastructure/postgres/journal_adapter.py` — NO change needed
- `operator/src/application/reconcile_closed_trades.py` — NO change needed
- `tests/unit/test_config.py` — needs new test cases for multi-symbol config parsing
- `tests/unit/test_main_loop.py` — needs tests for multi-symbol build + loop iteration
- `.env` / deployment env vars — new per-symbol env var scheme

## Approaches

### Option A — Per-symbol use case instances built at startup, iterated sequentially
Build N `RunTradingCycleUseCase` instances at startup (one per symbol), each with its own symbol+size. `run_forever()` iterates the list of use cases at each boundary with a per-use-case try/except.

- Pros: use case class unchanged; minimal code delta; full per-symbol isolation via existing try/except; simple to reason about; fits the existing hexagonal structure; boundary timing is the same 15-min window for all 6 (candle fetches are fast sequential HTTP calls, ~1-2s each, 6x2s = 12s worst case, well within a 900s window)
- Cons: config shape must change (no longer one scalar SYMBOL/EPIC pair); env var scheme needs redesign
- Effort: Low

### Option B — Single use case that loops internally over a symbols list
Add a `symbols: list[SymbolConfig]` param to `RunTradingCycleUseCase`, loop internally per `execute()`.

- Pros: one use case object, one call in `run_forever()`
- Cons: violates SRP (use case now owns iteration and per-symbol logic); harder to test per-symbol behavior in isolation; the existing test suite tests one-symbol execute; requires modifying the use case class meaningfully
- Effort: Medium (more invasive refactor)

### Option C — Parallel execution (threading/asyncio)
Run per-symbol use cases concurrently.

- Pros: potentially faster within a boundary window
- Cons: Capital.com rate limits; shared session token (single CST/X-SECURITY-TOKEN pair — concurrent use may be fine for reads but risky for writes); significantly more complexity; the sequential 6x2s window is trivially within 900s so parallelism buys nothing
- Effort: High

### Recommendation: Option A.
It is the only option that keeps the use case SRP-compliant and requires changes only in the composition root (config + `__main__`). The use case class, broker adapter, journal, and reconciler require NO changes. Sequential execution is safe given the timing math (6 symbols x ~6s settle + freshness retries = well under 900s per boundary).

## Config Design (for propose phase)

Replace:
```
SYMBOL=EURUSD
EPIC=CS.D.EURUSD.MINI.IP
SIZE=1000
```

With one of:
- **Option A1 — JSON env var**: `SYMBOLS='[{"symbol":"EURUSD","epic":"CS.D.EURUSD.MINI.IP","size":1000},...]'`. Pros: single env var, arbitrary symbol count. Cons: harder to override one symbol in docker-compose.
- **Option A2 — Indexed env vars**: `SYMBOL_1=EURUSD`, `EPIC_1=...`, `SIZE_1=1000`, `SYMBOL_2=USDJPY`, etc. Pros: easy to override individual symbols. Cons: more verbose; arbitrary count needs a `SYMBOL_COUNT` var or a scan.
- **Option A3 — Keep backward-compat single-symbol vars, add `SYMBOLS_JSON` override**: If `SYMBOLS_JSON` is set, use it; else fall back to single `SYMBOL`/`EPIC`/`SIZE`. This is the safest migration path IF a deployment already exists.

## Per-Symbol Failure Isolation

In `run_forever()`, the current outer try/except catches any exception from `use_case.execute()` and logs it. When iterating N use cases, each needs its own try/except so a failed symbol doesn't abort the remaining ones. This mirrors the reconciler pattern exactly.

```python
for uc in use_cases:
    try:
        uc.execute()
    except Exception:
        logger.exception("cycle failed for symbol; continuing")
```

## Freshness Gate + Boundary Timing

Each `RunTradingCycleUseCase.execute()` computes its own `expected_decision_ts` from `clock.utcnow()` at call time. Since all 6 symbols share the same 15-minute boundary, and the calls are sequential (total ~12-20s including freshness retries), all 6 compute the same `boundary_epoch` and `expected_decision_ts`. No freshness issue, assuming total iteration time is much less than 900s.

Risk: if freshness retries spike (e.g., 3 retries x 2s x 6 symbols = 36s added), still trivially within window.

## Epic Mapping for New Symbols

Capital.com epic IDs are NOT always identical to symbol strings. EURUSD epic is `CS.D.EURUSD.MINI.IP` (confirmed by existing test fixtures). The pattern suggests: `CS.D.{SYMBOL}.MINI.IP`. But this needs verification against the demo API for each pair (USDJPY, GBPUSD, AUDUSD, USDCAD, USDCHF). This is a deployment concern, not a code concern. The `epics: dict[str, str]` design handles arbitrary mappings.

## Position Sizing per Symbol

`SIZE=1000` in base currency units. For EURUSD (USD-denominated), 1000 = 1000 USD notional. For USDJPY, 1000 could mean 1000 USD or 1000 JPY depending on Capital.com's contract spec. JPY pairs typically trade in different minimum lot sizes. This is a RISK that must be confirmed per-pair on the demo account before live use. The code design handles per-symbol size via `SymbolConfig.size`.

## Strategy Parameterization

`FadeStrategy` is pure math with frozen constants. No per-symbol tuning. Running the same params on 6 pairs is the user's explicit choice. The strategy was walk-forward validated on EURUSD only — performance on USDJPY/GBPUSD/AUDUSD/USDCAD/USDCHF is unvalidated. This is a research caveat, not a code bug.

## Position Management per Symbol

Current behavior: `has_open_position(symbol)` gates re-entry (`trading_cycle.py` line 42). With 6 symbols, each independently gates itself — if EURUSD has an open position, it skips, but USDJPY still runs. This is correct and already works because `has_open_position` takes a symbol param and filters by epic. No pyramiding per symbol; this stays unchanged.

## Existing Test Coverage Impact

- `test_trading_cycle.py`: passes `symbol="EURUSD"` hardcoded. No change needed to existing tests.
- `test_main_loop.py`: tests `build_use_case()` with single-symbol config. Needs new tests for multi-symbol build.
- `test_config.py`: tests single SYMBOL/EPIC/SIZE parsing. Needs new tests for multi-symbol config parsing.
- `FakeBroker`: already multi-symbol (takes `symbol: str` in all methods). No change needed.

## Risks

1. **Epic mapping verification**: The 5 new epics must be verified against Capital.com demo API before live deployment. Wrong epic = wrong instrument traded silently.
2. **Per-symbol position sizing**: SIZE=1000 may not be equivalent across pairs (especially JPY pairs). Must verify contract specs per pair.
3. **Strategy out-of-sample risk**: Frozen fade params validated only on EURUSD; applying to 5 new pairs is an unvalidated research bet.
4. **Config migration**: If a deployment already exists, changing the schema breaks it. Mitigated by A3, OR moot if no deployment exists.
5. **Session token thread safety**: Not relevant for sequential execution, but note that `CapitalSession` is NOT thread-safe (it mutates `self._tokens`). This is fine for sequential, blocks Option C.
6. **Rate limiting**: Capital.com may throttle 6 sequential candle fetches per boundary. Unknown rate limit; needs testing on demo.

## Open Questions for Propose Phase

1. What are the exact Capital.com epic IDs for USDJPY, GBPUSD, AUDUSD, USDCAD, USDCHF? (Verify on demo before hardcoding)
2. Should per-symbol SIZE be configurable independently, or use the same size for all 6?
3. Config schema: JSON env var vs. indexed env vars vs. backward-compat Option A3?
4. Should the bot skip a symbol boundary if it already has an open position on that symbol (current behavior, unchanged), or log a summary of skipped symbols?
5. Any per-symbol position limit beyond the "no stacking" gate? (E.g., max 1 open at a time across ALL symbols combined?)

## Ready for Proposal
Yes. The codebase is well-factored for this change. The broker adapter and all downstream are already multi-symbol. The scope is contained to: (1) Config refactor, (2) `__main__` composition root expansion, (3) env var scheme, (4) new tests. The use case class itself needs no modification.
