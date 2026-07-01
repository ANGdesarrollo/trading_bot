# Exploration: WebSocket Candle Ingestion + Postgres Candle Store

## Context

The bot's FadeStrategy decides at the OPEN of the bar AFTER the decision candle. The current REST-based `recent_candles` poll has 68-104s publication latency on a 15-minute boundary, causing stale-candle warnings and missed entries. Capital.com WebSocket `OHLCMarketData.subscribe` delivers closed-candle events in ~450ms (150-200x faster). This exploration maps the full integration surface to enable a spec/design/tasks pipeline.

---

## Current State

### Candle Flow (file:line references)

**`src/infrastructure/capital/broker.py:44-55`** — `CapitalBrokerAdapter.recent_candles`
- Fetches `GET /prices/{epic}?resolution={timeframe}&max={count+1}` via REST
- `records[:-1]` drops the last record (in-formation candle) — line 54 is the closed-candle filter
- `_parse_candle` (line 130-140) maps REST price structure to `Candle`, using **bid** OHLC exclusively (`record["openPrice"]["bid"]`, etc.)
- Timestamps parsed from `snapshotTimeUTC` ISO string, stored as UTC-aware `datetime`

**`src/application/trading_cycle.py:41-82`** — `RunTradingCycleUseCase.execute`
- Lines 46-51: computes `expected_decision_ts` = the closed candle at the boundary **before** now
- Lines 53-66: freshness guard — retries up to `freshness_max_retries` times, sleeps `freshness_retry_seconds` between; if after all retries `candles[-1].timestamp != expected_decision_ts`, logs a warning and returns `None` (skipped cycle)
- Line 68: calls `strategy.evaluate(candles)` — passes ALL candles including the decision candle as last element

**Once candles come from Postgres**: the freshness guard (lines 53-66) becomes **dead logic**. The PG store will always hold the closed decision candle by the time the trading loop wakes up (WS delivers it in ~450ms). The guard should be removed or replaced by a simpler "last candle in store == expected boundary" assertion that does NOT retry via REST.

### Domain Contracts

**`src/domain/entities/candle.py`** — `Candle` entity
- Fields: `timestamp: datetime`, `open: float`, `high: float`, `low: float`, `close: float`
- Frozen dataclass with `__post_init__` invariant checks (high >= low, open/close within [low, high])
- Currently single-price (bid-only). For bid+ask storage, this entity stays unchanged — the store holds raw bid+ask columns, the read-path derives a mid to fill this existing entity at query time.

**`src/domain/ports/broker_port.py`** — `BrokerPort`
- `recent_candles(symbol, count) -> Sequence[Candle]` — the only candle-supply contract
- This port currently conflates "fetch candles" and "execute orders". After this change, candle reading moves to a new `CandleStorePort`; `BrokerPort` retains only order operations.

**`src/domain/ports/strategy_port.py`** — `StrategyPort`
- `required_candles: int` — FadeStrategy returns 128
- `evaluate(candles: Sequence[Candle]) -> Signal | None`

**`src/domain/adapters/fade_strategy.py`** — `FadeStrategy`
- Consumes `candle.open`, `candle.high`, `candle.low`, `candle.close` (lines 41-43, 67-72)
- Does NOT access `candle.timestamp` — no timestamp coupling in strategy logic
- Mid derivation `(bid+ask)/2` at read time is fully transparent to the strategy

### Postgres Infrastructure

**`src/infrastructure/postgres/connection.py`**
- `connect(database_url)` returns a raw `psycopg.Connection` — synchronous psycopg v3

**`src/infrastructure/postgres/migration_runner.py`**
- Discovers and applies `*.sql` files from `src/infrastructure/postgres/migrations/` by filename sort order
- Uses `schema_migrations` table as applied-set; idempotent on re-run
- Pattern for new candle migration: add `002_create_candles.sql` — picked up automatically

**`src/infrastructure/postgres/journal_adapter.py`** — `PostgresTradeJournal`
- Pattern to mirror for `PostgresCandleStore`: raw SQL constants at module level, adapter class holds `self._conn`, cursor-per-operation, explicit `conn.commit()` after writes
- Uses `ON CONFLICT (deal_id) DO NOTHING` — upsert pattern available for candle deduplication

**Existing migration `001_create_trade_entries.sql`**: defines `trade_entries` table and `schema_migrations` bootstrapping.

### Session / Auth

**`src/infrastructure/capital/session.py`** — `CapitalSession`
- `authenticate()` calls `POST /session`, extracts `CST` and `X-SECURITY-TOKEN` from **response headers**
- **CRITICAL GAP**: `streamingHost` is in the POST /session **response body** (not headers) but is currently discarded. Line 52 only reads headers. The WS connection URL is `{streamingHost}/connect` — this field must be captured and surfaced.
- `tokens()` returns `SessionTokens(cst, security_token)` — these are also the WS auth credentials (sent in a CONNECT frame after WS handshake)

**`src/infrastructure/capital/cached_session.py`** — `CachedSession`
- TTL-based token cache (default 540s) to avoid rate-limit on POST /session (HTTP 429 if called too frequently across operator + reconciler)
- WS ingestion process will share this session; the ping-keepalive (every <10min) implicitly keeps the REST session alive too, but they are separate concerns

### Composition Root

**`src/__main__.py`**
- `build_use_cases()` (lines 49-94): wires all infrastructure → `RunTradingCycleUseCase`
- `run_forever()` (lines 97-112): boundary-aligned loop — sleeps until next 15-min boundary + `candle_settle_seconds` (5s default), authenticates, then runs all use cases
- Two processes today: `__main__.py` (trading loop) and `reconciler.py` (trade reconciliation, runs every 5min)
- The candle ingestion is a **third long-running process** (or a background thread in `__main__`). See topology discussion below.

**`src/reconciler.py`**
- Independent process with its own `run_reconciler_forever` loop
- Shares the same DB and Capital credentials
- Demonstrates the multi-process pattern already established

### Config

**`src/config.py`** — `Config` dataclass + `load_config()`
- `timeframe: str` already exists (default `"MINUTE_15"`)
- `database_url: str` already exists
- `epics: dict[str, str]` derived from `symbols`
- New fields needed: `streaming_host` (or derived from session response), `ws_ping_interval_seconds` (default 540), `backfill_max_candles` (default 500 or similar), `candle_store_resolution` (alias for timeframe or separate)
- Pattern: add fields to `Config` dataclass, read from env in `load_config()` with sensible defaults

---

## New Candle Port

A new `CandleStorePort` (domain port) is needed to decouple the trading cycle from the Postgres implementation:

```
CandleStorePort (abstract)
  recent_candles(symbol, count) -> Sequence[Candle]
  last_candle_timestamp(symbol) -> datetime | None
  append_candle(symbol, candle_bid_ask) -> None
```

`RunTradingCycleUseCase` reads candles from `CandleStorePort`, not `BrokerPort`. `BrokerPort.recent_candles` is removed from the port (or kept only for the backfill path, never called from the trading cycle).

---

## Approaches: Process Topology

### Approach A — Separate Ingestion Process (3-process architecture)

A dedicated `ingestion.py` process runs continuously:
1. Connects WS, subscribes to `OHLCMarketData` for all configured epics + resolution
2. On startup: backfill via REST if table empty; gap-fill if table has rows but a gap exists
3. On `ohlc.event` (bid or ask): buffer partial rows until both bid+ask arrive for the same `(epic, resolution, t)`, then upsert to Postgres
4. Ping every 540s to keep WS alive; reconnect on disconnect with exponential backoff

`__main__.py` trading loop changes:
- Removes `recent_candles` from BrokerPort usage
- Calls `CandleStorePort.recent_candles(symbol, 128)` from Postgres
- Removes freshness retry loop; asserts last candle timestamp == expected boundary once

**Pros:**
- Clean separation of concerns — ingestion and decision never block each other
- Ingestion can crash/restart independently without affecting order placement
- Follows existing reconciler-as-separate-process pattern
- WS reconnect/backoff logic stays isolated in its own event loop

**Cons:**
- Adds a third process to manage (Docker Compose service, etc.)
- Both processes need DB access and Capital credentials
- Decision loop must handle "no data yet" gracefully (race on startup)
- Deployment complexity increase

**Effort: Medium**

### Approach B — Embedded Background Thread in `__main__`

The WS ingestion runs as a `threading.Thread` inside the existing trading process:
- Thread runs `asyncio.run(ingest_forever(...))` using `websockets` library
- Main thread keeps the boundary-aligned loop, reads from Postgres
- Thread handles WS lifecycle, writes to Postgres

**Pros:**
- Single process to deploy/monitor
- Shared in-memory state possible (e.g. a `threading.Event` signaling "first candle written")
- Less infrastructure overhead

**Cons:**
- Python GIL complicates async WS + sync decision loop interaction
- A crash in the ingestion thread (or its asyncio loop) can destabilize the trading thread
- Harder to test in isolation
- `psycopg` (sync v3) + asyncio thread requires careful connection handling (connections are not thread-safe without connection pools)

**Effort: Medium (similar lines, but more coupling)**

### Approach C — Decision Loop Pulls from PG, No WS Process at All (REST + PG hybrid)

Keep REST polling but write each REST result to Postgres, eliminating WS entirely. Addresses the latency problem by reducing `candle_settle_seconds` and accepting that the current 68-104s latency is structural.

**Pros:**
- Minimal change — no WS code
- No new process

**Cons:**
- Does NOT solve the 68-104s publication latency (this was the original motivation)
- Postgres becomes a cache, not a source of truth — adds complexity with no latency benefit
- This approach was ALREADY ruled out by the probe results

**Effort: Low (but wrong)**

---

## Comparison Table

| Approach | Latency Fix | Separation | Deployment | Test Isolation | Effort |
|---|---|---|---|---|---|
| A — Separate Process | YES | HIGH | +1 process | EASY | Medium |
| B — Background Thread | YES | LOW | Same process | HARD | Medium |
| C — REST-only | NO | N/A | No change | N/A | Low |

---

## Key Integration Points

1. **`CapitalSession.authenticate()`** (`src/infrastructure/capital/session.py:40-53`) must be extended to capture `streamingHost` from the response body. The WS URL is `{streamingHost}/connect`. This is the only auth change needed.

2. **`Candle` entity** stays unchanged. The Postgres candle table stores `(open_bid, high_bid, low_bid, close_bid, open_ask, high_ask, low_ask, close_ask)`. The `PostgresCandleStore.recent_candles()` derives `mid = (bid+ask)/2` at read time and returns `Candle(open=mid_open, ...)`.

3. **WS bid+ask pairing**: each `ohlc.event` carries `priceType: "bid" | "ask"`. Two messages arrive per closed candle. The ingestion layer must buffer by `(epic, resolution, t)` until both arrive, then write a single combined row. The WS message format guarantees epoch_ms UTC for `t`.

4. **`RunTradingCycleUseCase`**: the freshness guard (`trading_cycle.py:53-66`) is removed. The use case's `broker.recent_candles` call is replaced by `candle_store.recent_candles`. The `BrokerPort` signature loses `recent_candles`; the use case gains a `CandleStorePort` dependency.

5. **Migration**: `002_create_candles.sql` creates the candle table with `UNIQUE (epic, resolution, candle_start)` for upsert idempotency. The migration runner discovers it by filename sort — no runner changes needed.

6. **Backfill REST path**: reuses existing `CapitalBrokerAdapter` HTTP infrastructure (same auth, same `/prices` endpoint). No new HTTP client needed.

7. **Config**: `streamingHost` can be stored at runtime (not in env) if `CapitalSession` returns it from `authenticate()`. Alternatively add `STREAMING_HOST` env override for testing.

8. **Ping**: Capital WS sessions expire after 10 minutes. A periodic ping every 540s (matching `session_refresh_ttl_seconds` default) keeps both the WS and the REST session alive.

---

## Open Questions / Risks

1. **Startup race condition**: the trading loop wakes at the 15-min boundary. If the ingestion process (Approach A) is still backfilling when the boundary hits, `CandleStorePort.recent_candles` may return fewer than 128 candles. The trading cycle must handle this gracefully (return None, not crash).

2. **In-formation candle definition**: WS pushes `ohlc.event` on candle CLOSE. The currently-forming candle only arrives when it closes. No in-formation filtering needed at the WS level (unlike REST where `records[:-1]` was required).

3. **`streamingHost` surfacing**: `session.py` currently discards the response body. The minimal change is to return it from `authenticate()` OR parse it internally and expose a `streaming_host` property. The spec phase must decide.

4. **Bid+ask buffer durability**: if the ingestion process crashes between receiving the bid event and the ask event, one half-row is lost. On reconnect, the gap-fill REST call recovers the complete candle from history. The buffer is ephemeral; this is acceptable.

5. **`websockets` vs `websocket-client`**: `pyproject.toml` has no WS library dependency. `websockets` is async-native; `websocket-client` is sync. The spec phase must add the dependency.

6. **Connection limit**: max 40 instruments per WS connection. Current config has 1 symbol. Multi-symbol is safe up to 40 epics per connection. Not a risk for current scope.

7. **Timezone handling**: WS `t` is epoch milliseconds UTC. `datetime.fromtimestamp(t / 1000, tz=timezone.utc)` is the correct conversion. Candle timestamps in PG should be stored as `TIMESTAMPTZ`.

8. **`BrokerPort.recent_candles` removal**: removing this method from the abstract port breaks `CapitalBrokerAdapter` and all mocks. This is the largest refactor surface. Alternatively, keep the method but stop calling it from `RunTradingCycleUseCase`. The spec must decide.

9. **H1 forward-compat**: the architecture (config-driven `resolution`, WS subscription per `(epic, resolution)`; PG table keyed on `(epic, resolution, candle_start)`) already supports H1 with zero code changes.

10. **WS reconnect policy**: Capital disconnects after exactly 10 minutes. A clean reconnect every 540s (before the hard cutoff) with re-subscription is safest. The spec must define backoff for unexpected disconnects (suggested: exponential backoff capped at 60s).

---

## Recommendation

**Approach A — Separate Ingestion Process** is recommended.

The existing codebase already establishes a multi-process pattern (operator + reconciler as separate `__main__`-runnable modules sharing the same Postgres DB and Capital credentials). Approach A follows this pattern exactly: a third `ingestion.py` module runs a continuous WS ingest loop. It is independently deployable, restartable, and testable. The trading loop becomes a pure Postgres reader with no broker dependency for candle data.

Key implementation sequence (to be specified by sdd-spec):
1. Extend `CapitalSession.authenticate()` to capture `streamingHost`.
2. Add `002_create_candles.sql` migration (bid+ask columns, unique index on `(epic, resolution, candle_start)`).
3. Define `CandleStorePort` (domain port) with `recent_candles`, `last_candle_timestamp`, `append_candle_row`.
4. Implement `PostgresCandleStore` (mirrors `PostgresTradeJournal` pattern).
5. Implement `CapitalWsIngester` (infrastructure, new file) — backfill, gap-fill, live WS, ping, reconnect.
6. Add `ingestion.py` entry point (mirrors `reconciler.py` structure).
7. Modify `RunTradingCycleUseCase` to take `CandleStorePort` instead of `BrokerPort` for candles; remove freshness guard.
8. Update `__main__.py` composition root (wire `PostgresCandleStore` into use case).
9. Update `Config` with new env vars.
