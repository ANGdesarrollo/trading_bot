# Design: trade-journal-postgres

## Technical Approach

Two independent hexagonal processes share one Postgres DB. The **operator** writes ENTRY rows inline after `open_position()` (best-effort, non-raising). A **separate reconciler** process polls at 1-min cadence, reads Capital.com `/history/activity` + `/history/transactions` by `dealId`, and UPDATEs RESULT columns on rows where `reconciled_at IS NULL`. Disjoint column ownership keyed by `deal_id` makes the two writers conflict-free. Persistence is a raw-SQL numbered-migration runner (no ORM), driven by `psycopg` v3 sync. Follows the existing pattern: pure domain ports, concrete infra in `src/infrastructure/`, wiring only in composition roots.

## Architecture Decisions

| Decision | Choice | Alternatives rejected | Rationale |
|----------|--------|-----------------------|-----------|
| Port shape (ISP) | Two ports: `TradeJournalPort` (writes) + `TradeHistoryPort` (closed-trade reads) | Extend `BrokerPort` with history reads | Operator's `BrokerPort` must stay lean; the reconciler needs history the operator never calls. Fat-interface violation avoided. |
| Session sharing | Reconciler opens its OWN `CapitalSession` | Share operator's session | Separate OS processes; no shared memory. Each re-auths on its own cadence (eager, per existing session doc). |
| History query granularity | Per-`dealId`: `GET /history/activity?dealId={id}&detailed=true` with `from=opened_at`, `to=now` | Batch date-range scan of all activity | Single-symbol 15m bot has ≤1 open trade at a time; per-dealId avoids client-side matching and respects the 86400s cap via stored `opened_at`. |
| Write-conflict avoidance | Operator INSERTs entry columns; reconciler UPDATEs result columns WHERE `reconciled_at IS NULL` | Row locks / advisory locks | Disjoint column sets + guarded UPDATE = no contention. INSERT vs UPDATE never race the same columns; idempotent re-runs are safe. |
| `realized_r` formula | `risk_price = sl_distance` (price units, broker-anchored); `move = (close_price − filled_price)` for BUY, negated for SELL; `realized_r = move / sl_distance`. Fees excluded from R (tracked separately). | Money-based R (`pnl / (sl_distance*size)`) | `sl_distance` is the exact broker stop offset from fill; price-move / stop-distance is the pure, testable R with no size/currency coupling. |
| Migration runner placement | Shared `src/infrastructure/postgres/migration_runner.py`; **operator runs it on startup**, reconciler calls the SAME idempotent runner on its startup | Only operator migrates | Both are independent entrypoints; either may start first. Idempotent runner (schema_migrations guard) makes double-invocation safe and removes ordering coupling. |
| Driver | `psycopg[binary]` v3 sync | psycopg2-binary | Modern, maintained, sync API sufficient; single new runtime dep. |
| ATR at entry | Derived: `atr_at_entry = sl_distance / SL_ATR_MULT` (imported from `research.lib.fade_strategy`, single source) | Add `atr` to `Signal` | Keeps pure domain untouched; `sl_distance` already encodes ATR. |

## Data Flow

    OPERATOR (15m loop)                     RECONCILER (1m loop)
    open_position() -> OrderResult          open_entries()  [reconciled_at IS NULL]
         |                                        | for each pending deal_id
    journal.record_entry(entry)             history.closed_trade(deal_id, opened_at)
         | best-effort (never raises)             | activity + transactions
         v                                        v
    INSERT trade_entries (entry cols)       journal.record_result(result)
                     \                          /  UPDATE result cols WHERE reconciled_at IS NULL
                      \___ Postgres: trade_entries ___/

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/domain/ports/trade_journal_port.py` | Create | `record_entry`, `record_result`, `open_entries` |
| `src/domain/ports/trade_history_port.py` | Create | `closed_trade(deal_id, opened_at) -> ClosedTrade | None` |
| `src/domain/entities/journal.py` | Create | `JournalEntry`, `JournalResult`, `ClosedTrade` frozen VOs |
| `src/infrastructure/postgres/connection.py` | Create | `connect(database_url)` psycopg factory |
| `src/infrastructure/postgres/journal_adapter.py` | Create | `PostgresTradeJournal(TradeJournalPort)` |
| `src/infrastructure/postgres/migration_runner.py` | Create | Idempotent numbered-SQL runner + `schema_migrations` |
| `src/infrastructure/postgres/migrations/001_create_trade_entries.sql` | Create | DDL below |
| `src/infrastructure/capital/history_adapter.py` | Create | `CapitalTradeHistory(TradeHistoryPort)` |
| `src/application/reconcile_closed_trades.py` | Create | `ReconcileClosedTradesUseCase` |
| `src/application/trading_cycle.py` | Modify | Best-effort `record_entry` after `open_position` |
| `src/__main__.py` | Modify | Run migrations on startup; wire journal into use-case |
| `src/reconciler.py` | Create | Reconciler composition root + 1-min `run_forever` |
| `src/config.py` | Modify | Add `DATABASE_URL` |
| `pyproject.toml` | Modify | Add `psycopg[binary]` |
| `docker-compose.yml` | Create | postgres:16-alpine service |
| `Makefile` | Create | up/down/logs/operator/reconciler |
| `tests/fakes/fake_journal.py` | Create | `FakeJournalPort` records calls |
| `tests/fakes/fake_history.py` | Create | `FakeTradeHistoryPort` canned closures |
| `tests/unit/test_reconcile_use_case.py` | Create | R math, guard, no-result retry |
| `tests/integration/test_postgres_journal.py` | Create | DATABASE_URL-gated round-trip |

## Interfaces / DDL

```python
class TradeJournalPort(ABC):
    def record_entry(self, entry: JournalEntry) -> None: ...      # never raises in cycle
    def record_result(self, deal_id: str, result: JournalResult) -> None: ...
    def open_entries(self) -> Sequence[JournalEntry]: ...          # reconciled_at IS NULL

class TradeHistoryPort(ABC):
    def closed_trade(self, deal_id: str, opened_at: datetime) -> ClosedTrade | None: ...
```

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trade_entries (
    id                 BIGSERIAL PRIMARY KEY,
    deal_id            TEXT NOT NULL UNIQUE,
    symbol             TEXT NOT NULL,
    direction          TEXT NOT NULL,
    opened_at          TIMESTAMPTZ NOT NULL,
    decision_candle_ts TIMESTAMPTZ NOT NULL,
    filled_price       DOUBLE PRECISION NOT NULL,
    sl_distance        DOUBLE PRECISION NOT NULL,
    tp_distance        DOUBLE PRECISION NOT NULL,
    atr_at_entry       DOUBLE PRECISION,
    position_size      DOUBLE PRECISION NOT NULL,
    -- result columns (reconciler-owned, NULL until reconciled)
    closed_at          TIMESTAMPTZ,
    close_price        DOUBLE PRECISION,
    close_source       TEXT,
    realized_pnl       DOUBLE PRECISION,
    fees               DOUBLE PRECISION,
    realized_r         DOUBLE PRECISION,
    reconciled_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_trade_entries_open ON trade_entries (reconciled_at) WHERE reconciled_at IS NULL;
```

Reconciler UPDATE guard: `UPDATE trade_entries SET ... , reconciled_at = now() WHERE deal_id = %s AND reconciled_at IS NULL`.

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | `record_entry` after open; NOT on no-signal; entry failure does not crash cycle | `FakeJournalPort` (raising variant) injected into `RunTradingCycleUseCase` |
| Unit | R sign math (BUY/SELL win/loss), no-result → skip, guarded UPDATE call | `FakeTradeHistoryPort` + `FakeJournalPort` in `ReconcileClosedTradesUseCase` |
| Integration | INSERT entry → UPDATE result → read back; guard blocks double-reconcile | `tests/integration/test_postgres_journal.py`, skip when `DATABASE_URL` absent |

Strict TDD: write failing test first for each unit above (`.venv/bin/python3 -m pytest`).

## Migration / Rollout

Additive. On startup each entrypoint runs the idempotent runner: create `schema_migrations`, apply any numbered file not yet recorded, in one transaction per file. No backfill of historical trades (non-goal). `make up` provisions Postgres before either process starts.

### docker-compose / Makefile

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment: { POSTGRES_DB: trade_journal, POSTGRES_USER: operator, POSTGRES_PASSWORD: operator_dev }
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
volumes: { pgdata: {} }
```

`Makefile`: `up` (compose up -d), `down`, `logs`, `operator` (python -m src runs migrations+loop), `reconciler` (python -m src.reconciler).

## Delivery / PR Boundary

Estimate ~450-550 changed lines across ~19 files — EXCEEDS the 400-line budget. Recommend **two chained PRs** at the natural entry/result seam:

- **PR1 (entry-write path)**: ports (journal), `journal.py` VOs, postgres connection+adapter+runner+001 DDL, `SL_ATR_MULT` derivation, operator wiring, config `DATABASE_URL`, `psycopg` dep, docker-compose, Makefile, fake_journal, entry + integration tests. Self-contained, deployable (operator journals entries).
- **PR2 (reconciler path)**: `TradeHistoryPort`, `history_adapter.py`, `ReconcileClosedTradesUseCase`, `reconciler.py` entrypoint + 1-min loop, `record_result`/`open_entries` impl, fake_history, reconciler tests, Makefile `reconciler` target.

`sdd-tasks` confirms final line count; single PR only if it lands ≤400.

## Open Questions

- [ ] Fees: use `/history/transactions` TRADE_COMMISSION join (design assumes yes, populating `fees`); confirm P&L source is transaction row vs activity.
