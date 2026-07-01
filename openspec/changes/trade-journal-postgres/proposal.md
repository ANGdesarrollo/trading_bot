# Proposal: trade-journal-postgres

## 1. Intent / Why Now

The operator now places real orders on Capital.com demo, but it has **no memory
of what it did**. Once a position opens and later closes broker-side (SL/TP hit,
manual close, forced close-out), that outcome evaporates: the bot only knows
"a position exists" or "it doesn't". We cannot answer the questions that decide
whether the frozen fade survives execution reality:

- **Debug**: did the fill match the decision candle? Did SL/TP land where we
  attached them?
- **Fee analysis**: what did Capital.com actually charge per round-trip
  (TRADE_COMMISSION, swap)? Fees erode the measured edge and are invisible today.
- **Profit tracking**: cumulative realized P&L and R across trades.
- **Post-hoc strategy validation against REAL fills**: the backtest predicts
  E[R]; only a journal of real entries and exits lets us compare live realized R
  to the in-sample expectation and detect execution drift.

**Why now.** Every demo trade placed without a journal is data thrown away. The
forward-test's entire purpose is to measure execution reality, and we currently
measure nothing after the order leaves. This is the persistence layer the
forward-test needs to be worth running.

**Success.** For every position the operator opens, a durable row is written at
entry (synchronously, as the operator recording its own action). A **separate,
independent reconciler process** later fills the result columns (close price,
close source, realized P&L, fees, realized R) by reading Capital.com's
`/history/activity` and `/history/transactions` for that `dealId`. The two
processes never contend: the operator writes entry columns, the reconciler
writes result columns, on the same row keyed by `deal_id`.

## 2. Scope (In)

**Domain (pure, no I/O):**
1. `src/domain/ports/trade_journal_port.py` — `TradeJournalPort` ABC with
   `record_entry(entry)` and `record_result(result)` (and a read method for the
   reconciler to fetch unreconciled entries, e.g. `open_entries()`). Two value
   objects: `JournalEntry` (entry columns) and `JournalResult` (result columns).
   The port is the domain boundary; no SQL leaks inward.

**Application (orchestration, depends only on ports):**
2. `src/application/trading_cycle.py` — after `open_position()` returns an
   `OrderResult`, call `journal.record_entry(...)` with the entry data. The write
   is **best-effort and must never raise into the engine**: a journal failure
   must not crash a live trade. ATR at entry is **derived**, not read from
   `Signal` (see §4).
3. **New reconciler use case** (application layer), e.g.
   `src/application/reconcile_trades.py` — `ReconcileClosedTradesUseCase`: read
   unreconciled entries from the journal, for each query Capital.com activity +
   transactions by `dealId`, and write `record_result(...)`. Pure orchestration,
   depends only on ports.

**Infrastructure:**
4. `src/infrastructure/postgres/` — new package:
   - `connection.py` — psycopg connection from `DATABASE_URL`.
   - `journal_adapter.py` — `PostgresTradeJournal(TradeJournalPort)`.
   - `migrations/` — numbered raw SQL files (`001_*.sql`).
   - `migration_runner.py` — thin idempotent runner, tracked by a
     `schema_migrations` table (see §4).
5. **Reconciler needs closed-position lookups.** Either extend `BrokerPort`
   (e.g. `closed_position_details(deal_id, opened_at)`) implemented in
   `CapitalBrokerAdapter`, or add a dedicated history port. Decision deferred to
   design (§6), but it lives behind a port either way.

**Composition + entrypoints:**
6. `src/__main__.py` — operator composition root: run migrations on startup, wire
   `PostgresTradeJournal` into the trading cycle.
7. **New reconciler entrypoint** — a second entrypoint (e.g.
   `src/reconciler.py`) with its own `run_forever` loop at **1-minute cadence**,
   wiring the reconciler use case against the same DB and the same Capital.com
   session mechanism. Distinct process from the operator.
8. `src/config.py` — add `DATABASE_URL` (env-loaded).

**Infra files (new, none exist today):**
9. `docker-compose.yml` — `postgres:16-alpine` service, named volume.
10. `Makefile` — `make up`/`make down`/`make logs` for Postgres, plus separate
    `make operator` and `make reconciler` targets.
11. `pyproject.toml` — add `psycopg[binary]` (the single new runtime dependency).

**Tests (strict TDD, tests-first):**
12. `tests/fakes/fake_journal.py` — `FakeTradeJournal(TradeJournalPort)`
    recording calls, for use-case unit tests.
13. Use-case tests: entry recorded after a successful open; not recorded when no
    signal; journal failure does not crash the cycle. Reconciler tests: an
    unreconciled entry gets its result written; a still-open position is left
    untouched.
14. One `DATABASE_URL`-gated integration test
    (`tests/integration/test_postgres_journal.py`) round-tripping entry → result
    against the docker-compose Postgres, skipped when the env var is absent.

## 3. Scope (Out / Non-Goals)

- **Dashboard / UI / reporting front-end.** The journal is a database; querying
  it is out of scope for this change.
- **Multi-broker.** Capital.com only; the schema is broker-agnostic enough but no
  second adapter is built.
- **Migrating existing/past trades.** No backfill of trades placed before the
  journal existed.
- **Changing the frozen fade strategy or its math.** The domain `Signal` entity
  is NOT modified (ATR is derived — §4).
- **Reconciliation of anything but closed positions.** No live P&L, no
  mark-to-market, no open-position tracking beyond the existing `has_open_position`.
- **Bot containerization.** Only Postgres runs in docker-compose; operator and
  reconciler run from the host connecting to the mapped port.
- **Merging operator and reconciler into one process.** They are deliberately two
  entrypoints (SRP — §4).

## 4. Locked Decisions (from user, treat as fixed)

| Decision | Choice | Rationale |
|---|---|---|
| **Reconciler process** | A **separate entrypoint and loop** at **1-minute cadence**, distinct from the operator. Shares the same Postgres DB and the same Capital.com session mechanism. | SRP: the operator opens trades and records its own entries; the reconciler only reads closed positions and fills results. Crash-safe (DB is source of truth) and never blocks the trading loop. |
| **ATR at entry** | **Derived**, not stored on `Signal`: `atr_at_entry = sl_distance / SL_ATR_MULT` (frozen constant). | Keeps the pure domain untouched; `sl_distance` already encodes ATR, so storing ATR separately would duplicate knowledge. |
| **Migrations** | Raw numbered SQL files applied by a thin Python runner **on startup**, idempotent, tracked by a `schema_migrations` table. No alembic/SQLAlchemy. | Minimal deps (project only has requests/numpy/pandas today). psycopg is the single new runtime dep. Fits the project's minimal-deps philosophy. |
| **Driver** | `psycopg[binary]` (psycopg 3), sync. | One new runtime dependency; sync matches the bot. |
| **Bring-up** | `make up` starts docker-compose Postgres; separate `make operator` and `make reconciler` targets. | User-specified. Keeps the three concerns (DB, operator, reconciler) independently runnable. |
| **Entry write ownership** | The **operator** writes the entry row inside the trading cycle, on a successful `open_position`. | Recording your own action is not "interference" — it is the operator journaling what it just did. The reconciler never writes entry columns. |
| **Result write ownership** | The **reconciler** writes result columns exclusively. | Column-level ownership keyed by `deal_id` means the two processes touch disjoint columns of the same row — no write conflict. |

## 5. Journaled Data (per trade, one row keyed by `deal_id`)

**ENTRY (written by the operator on successful open):**
`deal_id`, `symbol`, `direction`, `opened_at`, `decision_candle_ts`,
`filled_price`, `sl_distance`, `tp_distance`, **derived** `atr_at_entry`,
`position_size`, and bid/ask context at decision if available.

**RESULT (written by the reconciler):**
`closed_at`, `close_price`, `close_source` (`SL` | `TP` | `USER` | `CLOSE_OUT`),
`realized_pnl`, `fees`, `realized_r`, `reconciled_at`.

Schema note: `deal_id` is `UNIQUE` (Capital.com dealIds are globally unique per
the confirms response). `symbol` is a first-class column so the schema is
multi-symbol-ready even though the operator runs one symbol today. Result columns
are `NULL` until reconciled. `opened_at` is stored so the reconciler can build
the `/history/activity` `from`/`to` range (the endpoint caps `lastPeriod` at
86400s = 1 day).

## 6. Open Design Questions (defer to design phase)

These are architecture questions the design phase must resolve; none block the
proposal.

1. **Session sharing.** Does the reconciler reuse `CapitalSession` (import and
   instantiate its own) or does it authenticate independently? Both share "the
   Capital.com session mechanism"; the design fixes whether that means shared code
   or a shared live session.
2. **Per-dealId vs batch reconciliation.** Query `/history/activity?dealId=X` once
   per unreconciled entry, or fetch a day's activity once and match locally? Trade
   off API calls vs. matching complexity at 1-minute cadence.
3. **Closed-position lookup port shape.** Extend `BrokerPort` with a
   `closed_position_details` method, or introduce a dedicated `HistoryPort` for
   reconciliation reads? Keep the operator's `BrokerPort` lean vs. one port.
4. **Fees join.** Is P&L from `/history/activity` sufficient, or must the
   reconciler join `/history/transactions` TRADE_COMMISSION (and swap) rows to
   populate `fees` accurately? Affects `realized_r` net-of-fees.
5. **Retry / not-yet-settled.** If `/history/activity?dealId=X` returns nothing yet
   (very recently closed), the reconciler leaves the row unreconciled and retries
   next minute (no backoff needed given 1-minute cadence). Confirm this is the
   policy vs. explicit backoff.
6. **`realized_r` derivation.** `realized_r = realized_pnl / (risk in currency)`,
   where risk derives from `sl_distance × position_size`. Design pins the exact
   arithmetic and units.

## 7. Risks

- **Write-conflict (managed, not a real risk).** Operator and reconciler touch
  **disjoint columns** of the same `deal_id` row: the operator writes entry
  columns once at open, the reconciler `UPDATE`s only result columns later. No
  row is ever written by both for the same column. Row is created by the operator
  before the reconciler ever sees it.
- **Entry-write failure while trade is live.** The journal write is best-effort;
  if it fails, the trade is live but unjournaled. The port must not raise into the
  engine. Mitigation: log loudly; a missing entry means the reconciler has nothing
  to reconcile for that trade (acceptable, rare).
- **Reconciliation latency / activity settlement.** Capital.com may not surface a
  closure in `/history/activity` immediately. The 1-minute reconciler simply
  retries until it appears; `opened_at` bounds the query window.
- **Activity date-range cap (86400s).** Trades held > 1 day need `from`/`to` built
  from `opened_at`; the schema stores it, so this is handled.
- **`psycopg[binary]` compiled dep.** Adds a binary wheel (~few MB). Acceptable;
  it is the only new runtime dependency.
- **Two-process operational surface.** `make up` + `make operator` +
  `make reconciler` is three things to run. Documented in the Makefile targets.

## 8. First-Slice Boundary & Delivery

**One PR, but at the upper edge of the 400-line budget.** This change spans
domain (port + value objects), application (entry write + reconciler use case),
infrastructure (adapter + migration runner + SQL), a second entrypoint, and infra
files (docker-compose, Makefile, pyproject), each with tests-first coverage.

**Estimated changed-line footprint: ~350–500 lines** across ~14 files. This is
**at risk of exceeding the 400-line budget** — the tasks phase should confirm the
count and, if it does, recommend a **chained split**:

- **PR 1 (foundation + entry):** `TradeJournalPort` + value objects, Postgres
  adapter, migration runner + `001` SQL, `DATABASE_URL` config, docker-compose,
  Makefile (`up`/`operator`), operator entry-write in the trading cycle, fakes,
  use-case + integration tests. Proves the operator journals entries end-to-end.
- **PR 2 (reconciler):** closed-position lookup port + Capital.com implementation,
  `ReconcileClosedTradesUseCase`, the reconciler entrypoint + 1-minute loop,
  `make reconciler`, reconciler tests. Fills the result columns.

The natural seam is entry-write vs. result-write, which mirrors the two
processes and the disjoint-column ownership. If the tasks phase measures the
combined diff at or under budget, ship as a single PR; otherwise chain PR 1 → PR 2.
