# Proposal: WebSocket Candle Ingestion + Postgres Candle Store

## Problem Statement

The `FadeStrategy` decides at the OPEN of the bar AFTER the decision candle, so the closed decision candle must be available within seconds of the boundary. The current REST poll (`CapitalBrokerAdapter.recent_candles`, `broker.py:44-55`) has **68-104s publication latency** on a 15-minute boundary. The freshness guard (`trading_cycle.py:53-66`) retries and often returns `None` — the cycle is skipped, entries are missed. Capital's WS `OHLCMarketData.subscribe` delivers the closed candle in **~450ms** (150-200x faster) with separate bid+ask. REST is structurally unfit for enter-at-next-open; a streaming source is required.

## Intent

Make the closed decision candle available sub-second by ingesting Capital WS OHLC events into Postgres, and make **Postgres the source of truth** for candles. Ingestion is separated from decision: the trading loop becomes a pure PG reader. The frozen `FadeStrategy` math is untouched — only the candle SOURCE changes.

## Goals

- Sub-second availability of the closed decision candle in the store.
- Postgres as the single source of truth for candles (strategy never reads the broker).
- A **contiguous** store up to the last CLOSED candle — zero gaps at the backfill→live seam.
- Bid + ask fidelity: store 8 raw columns; mid derived at read time.
- H1-ready: adding a timeframe is config + subscription only.

## Non-Goals

- Aggregating ticks into candles ourselves (WS emits closed OHLC directly).
- Multi-connection sharding beyond 40 epics/connection.
- Replacing or altering the reconciler.
- Changing strategy math, entities, or signal logic.

## Scope

### In Scope
- New `ingestion.py` process (mirrors `reconciler.py`): backfill-once → gap-fill-on-recovery → live-append via WS.
- New `CandleStorePort` + `PostgresCandleStore` (mirrors `PostgresTradeJournal`).
- New `CapitalWsIngester` (WS connect/subscribe, bid+ask pairing, ping, reconnect).
- Migration `002_create_candles.sql`, unique `(epic, resolution, candle_start)`.
- `CapitalSession` captures `streamingHost` from response body.
- `RunTradingCycleUseCase` reads from `CandleStorePort`; freshness retry loop removed.
- `Config` + composition-root wiring; new WS dependency.

### Out of Scope
- Tick aggregation, >40-epic sharding, reconciler changes, strategy math.

## Proposed Solution

Three-process topology (Approach A): trading loop + reconciler + new `ingestion.py`. Lifecycle: **backfill once** (empty table → REST history) → **gap-fill on recovery** (restart → detect gap from last stored candle → REST-fill only the gap) → **live-append** via WS. Splice contiguity is a HARD requirement: connect+subscribe WS first (buffer live events), then REST backfill, then gap-fill the seam; idempotent upsert on `(epic, resolution, candle_start)` absorbs overlap. `CandleStorePort` decouples the trading cycle from Postgres; the store keeps raw bid+ask and derives `mid=(bid+ask)/2` at read to match the FMP-mid backtest.

## Key Decisions

### DECIDED (do not re-open)
- **PG is source of truth** — ingestion separated from decision.
- **Backfill-once / gap-fill-on-recovery / live-append** lifecycle.
- **Splice contiguity guaranteed** — WS-first buffering, then backfill, then seam gap-fill, idempotent upsert.
- **Store bid AND ask (8 cols)** — market data is irrecoverable; enables future spread/slippage backtests. Strategy reads mid. Not YAGNI: uncaptured data is lost forever.
- **Approach A** — separate deployable `ingestion.py`; trading loop is a pure PG reader.
- **Multi-timeframe forward-compat** — table keyed on `(epic, resolution, candle_start)`; H1 = config + subscription.

### OPEN (spec/design must resolve)
- (a) Remove `BrokerPort.recent_candles` vs retain-but-unused.
- (b) `websockets` (async) vs `websocket-client` (sync).
- (c) Exact reconnect/backoff policy (suggested: exp backoff cap 60s; proactive reconnect < 10min WS cutoff).
- (d) How `streamingHost` is surfaced from `CapitalSession` (return value vs property).
- (e) Startup-race handling when the trading loop wakes before backfill completes.

## Capabilities

### New Capabilities
- `candle-store`: `CandleStorePort` + Postgres implementation; bid+ask persistence, mid-at-read, contiguity contract, `last_candle_timestamp`.
- `ws-candle-ingestion`: WS connect/subscribe, bid+ask pairing, backfill/gap-fill/live-append lifecycle, ping, reconnect, `ingestion.py` entry point.

### Modified Capabilities
- `trading-cycle`: candle source moves from `BrokerPort` to `CandleStorePort`; freshness retry loop removed.
- `capital-session`: `authenticate()` also captures `streamingHost`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/infrastructure/capital/session.py` | Modified | Capture `streamingHost` from body |
| `src/application/trading_cycle.py` | Modified | Read `CandleStorePort`; drop freshness guard |
| `src/__main__.py` | Modified | Wire `PostgresCandleStore` |
| `src/config.py` | Modified | WS ping/backfill/streaming-host fields |
| `src/domain/ports/candle_store_port.py` | New | Candle read/write contract |
| `src/infrastructure/postgres/candle_store.py` | New | PG adapter, mid-at-read |
| `src/infrastructure/capital/ws_ingester.py` | New | WS lifecycle + pairing |
| `src/ingestion.py` | New | 3rd process entry point |
| `.../migrations/002_create_candles.sql` | New | bid+ask table, unique index |
| tests | Modified | Freshness-guard tests, `BrokerPort` mocks, new store/ingester tests |
| `pyproject.toml` | Modified | WS library dependency |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Startup race (loop wakes pre-backfill) | Med | Cycle returns `None` on <128 candles; backfill ~1-2s |
| Bid/ask half-row loss on crash | Low | Ephemeral buffer; gap-fill recovers full candle from REST |
| WS 10-min disconnect | High | Proactive reconnect + re-subscribe every 540s |
| Migration ordering | Low | Runner sorts by filename; `002_` after `001_` |
| Seam gap despite ordering | Low | HARD contiguity check before trusting WS; idempotent upsert |

## Rollback Plan

Do not start `ingestion.py`; revert `trading_cycle.py`/`__main__.py` to read `BrokerPort.recent_candles`. Migration `002` is additive (new table) — leaving it in place is harmless. `operator/` is a standalone repo; revert via git without touching the parent.

## Dependencies

- New WS client library (`websockets` or `websocket-client` — decided in spec).
- Postgres reachable by the new process; shared Capital credentials.

## Success Criteria

- [x] Closed decision candle present in PG within ~1s of boundary.
- [x] Store contiguous to last closed candle across restart (gap-fill verified).
- [x] Trading loop reads only from PG; freshness retry loop removed.
- [x] Bid+ask persisted; mid at read matches FMP-mid backtest.
- [x] Adding H1 needs config + subscription only.
- [x] `FadeStrategy` math unchanged; existing strategy tests pass.

## Review Workload Forecast

- Estimated changed lines: **>400** (2 modified files + ~6 new files + migration + tests).
- **400-line budget risk: High**
- **Chained PRs recommended: Yes**
- **Decision needed before apply: Yes**
- Suggested slices: (1) migration + `CandleStorePort` + `PostgresCandleStore` + `streamingHost` capture; (2) `CapitalWsIngester` + `ingestion.py` + config + dependency; (3) `trading_cycle`/`__main__` cutover + freshness-guard removal + mock updates.
