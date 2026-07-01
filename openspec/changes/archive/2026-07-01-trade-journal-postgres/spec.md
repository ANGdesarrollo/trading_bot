# Spec: trade-journal-postgres

## Purpose

Durable per-trade journaling via Postgres. The operator writes entry rows on
successful order open; a separate reconciler process fills result columns by
querying Capital.com closed-activity history. All new — no prior journal spec.

---

## 1. TradeJournalPort

**REQ-01** — `TradeJournalPort` is an ABC in `domain.ports.trade_journal_port`.
It declares three methods: `record_entry(entry: JournalEntry) -> None`,
`record_result(result: JournalResult) -> None`, and
`open_entries() -> list[JournalEntry]`.
No SQL, no I/O, no infrastructure detail crosses this boundary.

**Scenario 1.1 — record_entry persists a new row**
```
Given a TradeJournalPort implementation and a valid JournalEntry with deal_id="D1"
When record_entry(entry) is called
Then a row keyed by deal_id="D1" exists in the journal
  And result columns (closed_at, close_price, etc.) are NULL
```

**Scenario 1.2 — record_entry is idempotent on duplicate deal_id**
```
Given deal_id="D1" already exists in the journal
When record_entry is called again with the same deal_id
Then no second row is inserted (INSERT ... ON CONFLICT DO NOTHING or equivalent)
  And the existing entry row is unchanged
```

**Scenario 1.3 — record_result writes only result columns**
```
Given a row with deal_id="D1" and NULL result columns
When record_result(JournalResult(deal_id="D1", ...)) is called
Then closed_at, close_price, close_source, realized_pnl, fees, realized_r,
     reconciled_at are populated for deal_id="D1"
  And entry columns (symbol, direction, filled_price, etc.) are unchanged
```

**Scenario 1.4 — open_entries returns only unreconciled rows**
```
Given two rows: deal_id="D1" with reconciled_at=NULL, deal_id="D2" with reconciled_at set
When open_entries() is called
Then the result contains JournalEntry for "D1" only
```

---

## 2. JournalEntry and JournalResult Value Objects

**REQ-02** — `JournalEntry` is an immutable value object with fields:
`deal_id: str`, `symbol: str`, `direction: str`, `opened_at: datetime`,
`decision_candle_ts: datetime`, `filled_price: float`, `sl_distance: float`,
`tp_distance: float`, `atr_at_entry: float`, `position_size: float`,
`bid_at_decision: float | None`, `ask_at_decision: float | None`.

**REQ-03** — `atr_at_entry` MUST be derived at construction time as
`sl_distance / SL_ATR_MULT` where `SL_ATR_MULT` is the frozen strategy constant.
No caller may supply `atr_at_entry` directly.

**Scenario 2.1 — atr_at_entry derived correctly**
```
Given sl_distance=0.0020 and SL_ATR_MULT=2.0
When JournalEntry is constructed
Then atr_at_entry == 0.0010
```

**REQ-04** — `JournalResult` is an immutable value object with fields:
`deal_id: str`, `closed_at: datetime`, `close_price: float`,
`close_source: str` (one of `"SL"`, `"TP"`, `"USER"`, `"CLOSE_OUT"`),
`realized_pnl: float`, `fees: float`, `realized_r: float`, `reconciled_at: datetime`.

---

## 3. Entry Recording (Operator — Best-Effort)

**REQ-05** — `RunTradingCycleUseCase.execute()` MUST call
`journal.record_entry(...)` immediately after a successful `open_position()`.
The write is best-effort: any exception from the journal MUST be caught, logged
with full traceback, and suppressed. The trading engine MUST NOT observe the
failure.

**REQ-06** — `record_entry` MUST NOT be called when there is no signal or
when `open_position()` raises.

**Scenario 3.1 — entry recorded after successful open**
```
Given broker.open_position returns OrderResult with deal_id="D1"
When execute() completes
Then journal.record_entry was called once with deal_id="D1"
  And the entry fields match the signal and order result
```

**Scenario 3.2 — no entry when no signal**
```
Given strategy.evaluate returns None
When execute() is called
Then journal.record_entry is NOT called
```

**Scenario 3.3 — journal failure does not crash the cycle**
```
Given journal.record_entry raises an exception
When execute() is called and open_position succeeded
Then the exception is caught and logged
  And execute() returns normally without re-raising
  And the trading loop continues to the next cycle
```

---

## 4. realized_r Arithmetic

**REQ-07** — `realized_r` MUST be computed as:

```
risk_currency = sl_distance * position_size
realized_r = (realized_pnl - fees) / risk_currency
```

Sign convention: positive `realized_r` means a profitable close. `sl_distance`
is always positive (absolute distance). `realized_pnl` is positive for profit,
negative for loss, using the broker's reported P&L sign.

**Scenario 4.1 — winning trade realized_r**
```
Given realized_pnl=20.0, fees=1.0, sl_distance=0.0020, position_size=10000
When realized_r is computed
Then risk_currency = 0.0020 * 10000 = 20.0
  And realized_r = (20.0 - 1.0) / 20.0 = 0.95
```

**Scenario 4.2 — losing trade realized_r**
```
Given realized_pnl=-20.0, fees=1.0, sl_distance=0.0020, position_size=10000
When realized_r is computed
Then realized_r = (-20.0 - 1.0) / 20.0 = -1.05
```

---

## 5. Reconciler Use Case

**REQ-08** — `ReconcileClosedTradesUseCase` lives in `application.reconcile_trades`.
It depends only on `TradeJournalPort` and a closed-position lookup port (shape
deferred to design). It has no direct dependency on any infrastructure class.

**REQ-09** — On each invocation, the use case MUST:
1. Call `journal.open_entries()` to retrieve unreconciled entries.
2. For each entry, query closed-position details by `deal_id`.
3. If the position is confirmed closed, compute `realized_r` and call
   `journal.record_result(...)`.
4. If the position is not yet found in closed history, leave the entry
   unreconciled (no action; the next pass retries).

**REQ-10** — The reconciler MUST be idempotent: if `record_result` is called
for a `deal_id` that already has `reconciled_at` set, the implementation MUST
skip the write (not double-write result columns).

**REQ-11** — A lookup failure or malformed response for one `deal_id` MUST NOT
abort the reconciliation of remaining entries. The error MUST be logged and the
loop MUST continue with the next entry.

**Scenario 5.1 — open entry gets reconciled on close**
```
Given journal.open_entries returns [entry(deal_id="D1")]
  And the lookup port returns a closed position for "D1"
When use case is invoked
Then journal.record_result is called with deal_id="D1" and realized_r computed
  And reconciled_at is set
```

**Scenario 5.2 — still-open position is left untouched**
```
Given journal.open_entries returns [entry(deal_id="D1")]
  And the lookup port returns no closed activity for "D1"
When use case is invoked
Then journal.record_result is NOT called for "D1"
  And reconciled_at remains NULL
```

**Scenario 5.3 — malformed lookup for one deal does not abort the pass**
```
Given journal.open_entries returns [entry("D1"), entry("D2")]
  And the lookup for "D1" raises an exception
When use case is invoked
Then the exception for "D1" is logged
  And reconciliation continues and attempts "D2"
```

**Scenario 5.4 — re-running on already-reconciled entry is a no-op**
```
Given entry "D1" already has reconciled_at set (not returned by open_entries)
When use case is invoked
Then record_result is NOT called for "D1"
```

---

## 6. Reconciler Entrypoint and Isolation

**REQ-12** — The reconciler MUST run as a **separate OS process** from the
operator, with its own `run_forever` loop at **60-second cadence**.

**REQ-13** — The reconciler process crashing or raising at any point MUST NOT
affect the operator process, and vice versa. They share only the Postgres DB.

**REQ-14** — A cycle error in the reconciler loop MUST be caught, logged with
traceback, and the loop MUST continue to the next 60-second boundary.

**Scenario 6.1 — reconciler cycle exception does not terminate the loop**
```
Given the reconciler use case raises RuntimeError during a cycle
When the reconciler loop handles the exception
Then the exception is logged
  And the loop sleeps to the next 60-second boundary and retries
  And the operator process is unaffected
```

---

## 7. Migration Runner

**REQ-15** — On startup, the operator (and reconciler) MUST run the migration
runner before any other database operation.

**REQ-16** — The migration runner MUST maintain a `schema_migrations` table
tracking which numbered SQL files have been applied. It MUST apply pending
files in ascending numeric order and skip already-applied files.

**REQ-17** — Running the migration runner twice against the same database state
MUST be a no-op (idempotent). No alembic, no ORM.

**Scenario 7.1 — first run applies all pending migrations**
```
Given a fresh database with no schema_migrations table
  And numbered SQL files 001_create_journal.sql exist
When the migration runner is invoked
Then schema_migrations is created
  And 001_create_journal.sql is applied
  And a row for "001_create_journal.sql" is recorded in schema_migrations
```

**Scenario 7.2 — second run is a no-op**
```
Given schema_migrations already contains "001_create_journal.sql"
When the migration runner is invoked again
Then no SQL from 001_create_journal.sql is re-executed
  And schema_migrations is not modified
```

**Scenario 7.3 — new migration file is applied on next startup**
```
Given "001_create_journal.sql" is already recorded in schema_migrations
  And "002_add_fees_column.sql" is a new file not yet recorded
When the migration runner is invoked
Then only 002_add_fees_column.sql is applied
  And "002_add_fees_column.sql" is recorded in schema_migrations
```

---

## 8. Configuration

**REQ-18** — `src/config.py` MUST expose `DATABASE_URL: str` loaded from the
`DATABASE_URL` environment variable. If the variable is absent and the journal
is wired, the process MUST raise a clear error before reaching the trading loop.

**Scenario 8.1 — DATABASE_URL missing causes early failure**
```
Given DATABASE_URL is not set in the environment
When the operator or reconciler starts up
Then a ConfigError (or equivalent) is raised before the trading loop begins
  And the error message references DATABASE_URL
```

---

## 9. Infrastructure Bring-up

**REQ-19** — `make up` MUST start the Postgres service via docker-compose and
nothing else (operator and reconciler run separately).

**REQ-20** — `make operator` and `make reconciler` MUST be independent targets.
Running one MUST NOT start the other.

---

## Non-Goals (out of scope for this spec)

- Dashboard, UI, or query front-end.
- Multi-broker support.
- Backfill of trades placed before the journal existed.
- Signal entity changes (atr_at_entry is derived, not stored on Signal).
- Live P&L or mark-to-market.
- Merging operator and reconciler into one process.
