# Design: Multi-Symbol Trading

## Technical Approach

Generalize the single-symbol composition root to N symbols by making `config.py`
carry a list of per-symbol value objects and `__main__.py` build one
`RunTradingCycleUseCase` per symbol, iterated sequentially each boundary with
per-symbol failure isolation. The change is confined to the two files that hold
the single-symbol assumption. Domain, ports, broker, journal, session, and the
reconciler are untouched — they are already symbol-agnostic (`broker.epics` is
`dict[str,str]`; `trading_cycle` self-gates via `has_open_position(self._symbol)`).

## Architecture Decisions

### Decision: Per-symbol value object + top-level Config aggregate

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Parallel dicts (`epics`, `sizes`) on flat Config | Cheap, but knowledge for one symbol is scattered across maps; easy to desync | Rejected |
| `SymbolConfig(symbol, epic, size)` list inside Config | One cohesive unit per symbol, immutable, trivial to iterate | **Chosen** |

**Rationale**: SRP + DRY — each symbol's identity, instrument, and size live in one
frozen value object. `Config.epics` is derived (`{s.symbol: s.epic}`) so the broker
contract is unchanged and there is a single source of truth.

### Decision: Explicit per-symbol epics, fail-fast (NO convention default)

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Convention default `CS.D.{SYMBOL}.MINI.IP` | Zero config, but 5/6 epics are UNVERIFIED — a wrong guess silently trades the wrong instrument | Rejected |
| Require explicit `EPIC_{SYMBOL}`, `ValueError` if missing | Slightly more env config; guarantees no accidental instrument | **Chosen** |

**Rationale**: This SUPERSEDES the proposal's tentative convention-default. With real
money and unverified epics, a silent wrong-instrument trade is the worst failure
mode. Startup MUST fail loudly naming the symbol. Config correctness is verified by
a human at deploy time, not discovered by the bot at runtime.

### Decision: Per-symbol size with global SIZE fallback (default 1000)

**Choice**: `SIZE_{SYMBOL}` overrides a global `SIZE` (default `1000`).
**Alternatives**: per-symbol-required (verbose, no OOTB run) rejected.
**Rationale**: Works out-of-the-box for all six, tunable for JPY, DRY via one default.

### Decision: List of use cases, sequential loop, per-symbol try/except

**Choice**: `build_use_cases()` returns `list[RunTradingCycleUseCase]`; `run_forever`
authenticates ONCE per boundary, then iterates symbols; each iteration is wrapped so
one symbol's failure logs and continues to the next.
**Alternatives**: threads/async (Option C) rejected — `CapitalSession` is not
thread-safe and 6×~2s is trivially inside the 900s window.
**Rationale**: Mirrors the reconciler's isolation pattern; SRP preserved (one use
case per symbol); zero downstream churn.

## Config Schema (exact env vars)

```
SYMBOLS=EURUSD,USDJPY,GBPUSD,AUDUSD,USDCAD,USDCHF   # comma-separated, required
EPIC_EURUSD=CS.D.EURUSD.MINI.IP                     # required per listed symbol
EPIC_USDJPY=...                                     # UNVERIFIED -> human sets at deploy
SIZE=1000                                           # global default (optional)
SIZE_USDJPY=...                                     # optional per-symbol override
# unchanged shared: MODE, CAPITAL_API_KEY, IDENTIFIER, PASSWORD, TIMEFRAME,
# WARMUP, CANDLE_SETTLE_SECONDS, POLL_MINUTES, FRESHNESS_*, DATABASE_URL
```

Removed scalars: `SYMBOL`, `EPIC`, and the single `trade_size` wiring path.

## Interfaces / Contracts

```python
@dataclass(frozen=True)
class SymbolConfig:
    symbol: str
    epic: str
    size: float

@dataclass(frozen=True)
class Config:
    mode: str; base_url: str; api_key: str; identifier: str; password: str
    symbols: tuple[SymbolConfig, ...]        # replaces symbol/epic/trade_size
    timeframe: str; warmup_bars: int; candle_settle_seconds: int
    poll_minutes: int
    freshness_max_retries: int; freshness_retry_seconds: float
    database_url: str

    @property
    def epics(self) -> dict[str, str]:        # derived, keeps broker contract intact
        return {s.symbol: s.epic for s in self.symbols}
```

`load_config` parses `SYMBOLS`, builds one `SymbolConfig` per entry resolving
`EPIC_{SYMBOL}` (fail-fast `ValueError` naming the symbol if missing/blank) and
`SIZE_{SYMBOL}` or `SIZE`. Shared-field validation stays as-is.

## Data Flow

```
load_config ─► Config.symbols ─┬─► SymbolConfig(EURUSD) ─► UseCase(EURUSD)
                               ├─► SymbolConfig(USDJPY) ─► UseCase(USDJPY)
                               └─► ...                                   │
run_forever: wait boundary ─► session.authenticate() (once) ─► for uc in use_cases:
                                                                 try: uc.execute()
                                                                 except: log & continue
```

Broker built ONCE with the full `epics` dict and shared across use cases (one
session). `open_position`/`has_open_position` already route by `symbol`→`epic`.

## `__main__` Loop Shape (pseudocode)

```python
def build_use_cases(config, http, clock, journal=None):
    session = CapitalSession(...)
    broker = CapitalBrokerAdapter(session, http, config.base_url,
                                  epics=config.epics, timeframe=config.timeframe)
    strategy = FadeStrategy(); _assert_warmup(config, strategy)
    journal = journal or _open_journal(config)
    use_cases = [RunTradingCycleUseCase(broker=broker, strategy=strategy,
                    symbol=sc.symbol, size=sc.size, logger=logger, clock=clock,
                    poll_minutes=config.poll_minutes,
                    freshness_max_retries=config.freshness_max_retries,
                    freshness_retry_seconds=config.freshness_retry_seconds,
                    journal=journal)
                 for sc in config.symbols]
    return use_cases, session

def run_forever(config, use_cases, session, clock):
    while True:
        clock.sleep(seconds_until_next_boundary(clock.utcnow(), config.poll_minutes)
                    + config.candle_settle_seconds)
        try: session.authenticate()
        except Exception: logger.exception("auth failed; skipping boundary"); continue
        for uc in use_cases:
            try: uc.execute()
            except Exception: logger.exception("cycle failed for %s; continuing", uc._symbol)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/config.py` | Modify | Add `SymbolConfig`; `Config` holds `symbols` tuple + derived `epics`; parse `SYMBOLS`/`EPIC_*`/`SIZE_*` with fail-fast |
| `src/__main__.py` | Modify | `build_use_case`→`build_use_cases` (list); `run_forever` auth-once + per-symbol try/except loop |
| `src/infrastructure/capital/broker.py` | None | Already multi-symbol |
| `src/application/trading_cycle.py` | None | One instance per symbol; already self-gates |
| `src/reconciler.py` | None | Symbol-agnostic; uses only shared fields |
| `tests/unit/test_config.py` | Create | Multi-symbol parse, size fallback, fail-fast on missing epic |
| `tests/unit/test_main_loop.py` | Create | List built; per-symbol isolation; auth-once ordering |

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `load_config` multi-symbol parse, `SIZE_{SYMBOL}` over `SIZE` over 1000, missing/blank epic raises `ValueError` naming symbol, derived `epics` | env-var monkeypatch |
| Unit | `build_use_cases` returns one use case per symbol; `run_forever` authenticates once then isolates per-symbol failure | fakes + spy use cases |

## Migration / Rollout

No data migration. Breaking env-schema change accepted (no deployment to migrate).
Epic verification for the 5 unverified pairs is a MANUAL demo-deploy gate, not a code
task; the bot must never probe or order to discover epics.

## Open Questions

- [ ] Optional per-boundary summary log (symbols evaluated / orders placed) for
      observability — deferred to tasks as a nice-to-have, not required.
