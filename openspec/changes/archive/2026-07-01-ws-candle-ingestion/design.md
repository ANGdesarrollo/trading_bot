# Design: WebSocket Candle Ingestion + Postgres Candle Store

## Technical Approach

Approach A (three processes). A new synchronous `ingestion.py` (mirrors `reconciler.py`) owns a blocking WS loop that writes bid+ask rows into a new `candles` table. `PostgresCandleStore` (mirrors `PostgresTradeJournal`) is the sole candle source; `RunTradingCycleUseCase` becomes a pure PG reader. `BrokerPort.recent_candles` is removed; backfill/gap-fill REST lives on a focused `CandleHistoryPort`. Implements spec capabilities candle-store, ws-candle-ingestion, trading-cycle, capital-session.

## Architecture Decisions

| # | Decision | Choice | Rejected | Rationale |
|---|----------|--------|----------|-----------|
| 1 | WS library | `websocket-client` 1.9.0 (sync) | `websockets` (async) | Whole codebase is sync (psycopg sync, `requests`, no asyncio). Ingestion runs in its OWN process — no need to bridge async into a sync psycopg connection. Zero GIL/loop friction; matches reconciler style. Add `websocket-client>=1.9,<2` to `pyproject.toml`. |
| 2 | Ingestion structure | Blocking `run_ingestion_forever` loop | asyncio task / thread | Mirrors `run_reconciler_forever`; independently `python -m ingestion`. |
| 3 | `CandleRow` placement | `src/domain/entities/candle_row.py`, frozen dataclass; epic/resolution plain `str` | put in infra | Port references it → must be domain. Identifiers, not infra types. |
| 4 | REST history | New `CandleHistoryPort` + `CapitalCandleHistory` adapter | keep fat method on `BrokerPort` | ISP: `BrokerPort` keeps only order ops. Reuses `/prices` shape + session auth. |
| 5 | Upsert conflict | `ON CONFLICT (epic,resolution,candle_start) DO UPDATE` | DO NOTHING | AC-CSP-1: second-call OHLC must win. |
| 6 | `streamingHost` | capture in `authenticate()`, expose `streaming_host` property | change `tokens()` sig | Minimal blast radius; spec CS-01/02. |
| 7 | `required_candles` | read from `strategy.required_candles` at wiring; ingestion `Config.required_candles` mirrors `warmup_bars` | duplicate literal | Single source of truth avoids divergence. |
| 8 | Reconnect backoff | proactive reconnect every `ws_ping_interval_seconds` (540s) via session timer; on drop exp backoff base 1s, cap 60s, full jitter, unbounded retries; always re-subscribe + re-run gap-fill | fixed sleep | < 600s cutoff; bounded reconnect storm. |

## Data Flow / Component Diagram

```
Capital WS ──ohlc.event(bid|ask)──> CapitalWsIngester
                                       │ PairBuffer[(epic,res,t)]
                                       │ both sides? → CandleRow
                                       ▼
Capital REST /prices ──backfill/gap──> CandleStorePort.upsert_candle
                                       ▼
                                   candles table (PG)
                                       ▲
RunTradingCycleUseCase ──recent_candles(symbol,N)── derives mid=(bid+ask)/2 → Candle
```

## Interfaces / Contracts

```python
# domain/entities/candle_row.py
@dataclass(frozen=True, slots=True)
class CandleRow:
    epic: str; resolution: str; candle_start: datetime  # UTC-aware
    open_bid: float; high_bid: float; low_bid: float; close_bid: float
    open_ask: float; high_ask: float; low_ask: float; close_ask: float

# domain/ports/candle_store_port.py  (ABC, no infra imports)
def recent_candles(symbol: str, count: int) -> Sequence[Candle]   # oldest-first, mid-derived
def last_candle_start(symbol: str, resolution: str) -> datetime | None
def upsert_candle(row: CandleRow) -> None

# domain/ports/candle_history_port.py  (ABC)
def fetch_history(epic: str, resolution: str, count: int,
                  since: datetime | None) -> Sequence[CandleRow]  # bid+ask both sides
```

### PostgresCandleStore SQL

```sql
-- upsert (idempotent, second call wins)
INSERT INTO candles (epic,resolution,candle_start,open_bid,high_bid,low_bid,close_bid,
                     open_ask,high_ask,low_ask,close_ask)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (epic,resolution,candle_start) DO UPDATE SET
  open_bid=EXCLUDED.open_bid, high_bid=EXCLUDED.high_bid, low_bid=EXCLUDED.low_bid,
  close_bid=EXCLUDED.close_bid, open_ask=EXCLUDED.open_ask, high_ask=EXCLUDED.high_ask,
  low_ask=EXCLUDED.low_ask, close_ask=EXCLUDED.close_ask;

-- recent_candles: newest N, reversed to oldest-first in Python; mid=(bid+ask)/2
SELECT candle_start, open_bid,high_bid,low_bid,close_bid, open_ask,high_ask,low_ask,close_ask
FROM candles WHERE epic=%s AND resolution=%s ORDER BY candle_start DESC LIMIT %s;

SELECT candle_start FROM candles WHERE epic=%s AND resolution=%s
ORDER BY candle_start DESC LIMIT 1;   -- last_candle_start → None if empty
```
Cursor-per-op, `conn.commit()` after upsert, `symbol→epic` mapped from `Config.epics`, resolution from `Config.timeframe`. Mirrors `PostgresTradeJournal`.

### Migration 002_create_candles.sql
```sql
CREATE TABLE IF NOT EXISTS candles (
  epic TEXT NOT NULL, resolution TEXT NOT NULL, candle_start TIMESTAMPTZ NOT NULL,
  open_bid NUMERIC NOT NULL, high_bid NUMERIC NOT NULL, low_bid NUMERIC NOT NULL, close_bid NUMERIC NOT NULL,
  open_ask NUMERIC NOT NULL, high_ask NUMERIC NOT NULL, low_ask NUMERIC NOT NULL, close_ask NUMERIC NOT NULL,
  UNIQUE (epic, resolution, candle_start));
CREATE INDEX IF NOT EXISTS idx_candles_recent ON candles (epic, resolution, candle_start DESC);
```

### PairBuffer (bid+ask pairing)
`dict[(epic,resolution,t_ms), _Partial]` where `_Partial` holds optional bid-quad + ask-quad. On event: fill side; if both present → build `CandleRow` (`candle_start = datetime.fromtimestamp(t/1000, tz=utc)`), `upsert_candle`, `del` key (evict). Staleness bound: on each event, drop partials whose `t_ms < newest_t_ms − STALE_PERIODS * period_ms` (STALE_PERIODS=4) so a lost half-row cannot leak memory.

### CapitalSession diff shape
`authenticate()` adds after headers: `body = response.json(); self._streaming_host = body.get("streamingHost")`. New `@property streaming_host` → raises `RuntimeError("Not authenticated…")` when `self._streaming_host is None`. `SessionTokens` unchanged.

### RunTradingCycleUseCase new shape
```python
def __init__(self, broker, candle_store: CandleStorePort, strategy, symbol, size,
             logger, clock, poll_minutes, journal):  # freshness params REMOVED
def execute(self):
    if self._broker.has_open_position(self._symbol): return None
    expected = self._expected_decision_ts()
    candles = self._candle_store.recent_candles(self._symbol, self._strategy.required_candles)
    if len(candles) < self._strategy.required_candles: return None            # TC-05 race guard
    if candles[-1].timestamp != expected:                                     # TC-04 single check
        self._logger.warning("stale candle …"); return None
    signal = self._strategy.evaluate(candles)
    if signal is None: return None
    result = self._broker.open_position(self._symbol, signal, self._size)     # unchanged path
    ...journal...
```

## Sequences

- **Cold-start (empty)**: WS connect+subscribe → buffer live → `last_candle_start`=None → `fetch_history(count=required_candles)` upsert all → drain buffer → live-append.
- **Warm-start (gap)**: connect+subscribe+buffer → `last_candle_start`=T_last → `fetch_history(since=T_last+1 period, count derived from (now−T_last)/period)` → upsert seam (idempotent overlap) → drain buffer → live.
- **Live close**: `bid@t` → partial(bid) no write; `ask@t` → both → upsert once → evict.
- **Reconnect**: proactive at 540s OR drop → exp-backoff(1s..60s jitter) → reconnect → re-subscribe → re-run gap-fill (WS-first buffer) → resume live.

## File Changes

| File | Action | Purpose |
|------|--------|---------|
| `src/domain/entities/candle_row.py` | Create | bid+ask value object |
| `src/domain/ports/candle_store_port.py` | Create | read/write candle contract |
| `src/domain/ports/candle_history_port.py` | Create | REST history contract (ISP) |
| `src/infrastructure/postgres/candle_store.py` | Create | PG adapter, mid-at-read |
| `src/infrastructure/postgres/migrations/002_create_candles.sql` | Create | table + unique + index |
| `src/infrastructure/capital/candle_history.py` | Create | `/prices` bid+ask history adapter |
| `src/infrastructure/capital/ws_ingester.py` | Create | WS lifecycle, PairBuffer, backfill/gap/live, ping, reconnect |
| `src/ingestion.py` | Create | 3rd process entry point |
| `src/infrastructure/capital/session.py` | Modify | capture `streamingHost` + property |
| `src/application/trading_cycle.py` | Modify | `CandleStorePort` dep; drop freshness loop |
| `src/__main__.py` | Modify | wire `PostgresCandleStore`; drop broker-candle wiring |
| `src/config.py` | Modify | `ws_ping_interval_seconds=540`, `required_candles`, `backfill_max_candles`; drop freshness fields |
| `src/domain/ports/broker_port.py` | Modify | remove `recent_candles` |
| `src/infrastructure/capital/broker.py` | Modify | remove `recent_candles` + `_parse_candle` |
| `pyproject.toml` | Modify | add `websocket-client` |

### __main__ wiring
`build_use_cases`: build `conn`, `run_migrations`, `store = PostgresCandleStore(conn)`, pass `candle_store=store` to use case; `CapitalBrokerAdapter` no longer needs `timeframe` for candles (keep for order epic map only). Ingestion is a separate process — not wired here.

### config.py
Add `ws_ping_interval_seconds: int` (env `WS_PING_INTERVAL_SECONDS`, default 540, assert <600), `required_candles: int` (= `warmup_bars`), `backfill_max_candles: int` (default 500). Remove `freshness_max_retries`/`freshness_retry_seconds`. `streaming_host` NOT env — taken from `session.streaming_host` at ingestion runtime.

## Testing Strategy

| Layer | AC | Approach |
|-------|-----|----------|
| Unit | AC-WCI-1..4,8 | Fake `CandleStorePort` + fake WS transport feeding `ohlc.event` dicts; assert `upsert_candle` call count/args |
| Unit | AC-WCI-5,6 | Fake `CandleHistoryPort` + fake store; assert full vs gap range |
| Unit | AC-TC-1..5 | Fake `CandleStorePort` + fake clock/broker; assert None paths, no `broker.recent_candles` |
| Unit | AC-CS-1..4 | Fake HTTP with body `{"streamingHost":...}` + headers |
| Integration (real PG) | AC-CSP-1..7, AC-CSP-8, AC-WCI-7 | Real test DB — idempotency, mid, ordering, migration discovery |

Reconnect/backoff: unit test with fake clock + fake transport raising drop, assert backoff schedule + re-subscribe + gap-fill re-run.

## Test Impact
Remove `recent_candles` from every `BrokerPort` test double (only `open_position`+`has_open_position` remain). Delete freshness-guard tests. Rewrite trading-cycle tests against a `CandleStorePort` fake. `CapitalBrokerAdapter` candle test deleted; move to `CapitalCandleHistory` test.

## Migration / Rollout
Additive migration `002` (new table) — safe to leave in on rollback. Rollback: don't start `ingestion.py`; revert `trading_cycle`/`__main__`/ports to REST. `operator/` standalone repo — do NOT commit.

## Open Questions
- None blocking. Exact `/prices` param for range gap-fill: use `resolution` + `max` (cold) and `from`/`to` (gap) if supported, else `max` sized from `(now−T_last)/period`; adapter tolerates overlap via idempotent upsert.
