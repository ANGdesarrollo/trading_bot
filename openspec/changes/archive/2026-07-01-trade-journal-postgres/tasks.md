# Tasks: trade-journal-postgres

**Delivery**: Single PR to `main` — `size:exception` (user-approved; estimated ~450-550 lines / ~19 files exceeds 400-line budget)
**TDD mode**: STRICT — RED → GREEN → REFACTOR every code task. Test runner: `cd operator && .venv/bin/python3 -m pytest`

---

## Review Workload Forecast

| Dimension | Value |
|-----------|-------|
| Estimated changed lines | ~450-550 |
| Files touched | ~19 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes (design recommends it) |
| Decision | **size:exception** — user explicitly chose single PR to main |
| PR boundary | All tasks in one PR |

---

## Dependency Graph (sequential unless marked PARALLEL)

```
T-01 (deps/config)
  └─ T-02 (domain entities)            ← PARALLEL with T-03
  └─ T-03 (domain ports)               ← PARALLEL with T-02
       └─ T-04 (fakes)                 ← PARALLEL: both fakes independent
       └─ T-05 (migration SQL + runner)
            └─ T-06 (postgres adapter) ← needs ports + entities
                 └─ T-07 (operator wiring)
                 └─ T-08 (integration test)   ← PARALLEL with T-07
            └─ T-09 (capital history adapter) ← needs TradeHistoryPort
                 └─ T-10 (reconcile use case) ← needs both fakes + ports
                      └─ T-11 (reconciler entrypoint)
T-12 (docker-compose + Makefile)       ← PARALLEL with T-01 onward, no code deps
```

---

## Group A — Infrastructure / Config

### [x] T-01 · Add psycopg dep + DATABASE_URL config

**Spec**: REQ-18, Scenario 8.1
**Files**: `pyproject.toml`, `src/config.py`, `tests/unit/test_config.py`

**RED** — Add to `tests/unit/test_config.py`:
```python
def test_database_url_missing_raises_config_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="DATABASE_URL"):
        load_config()

def test_database_url_present_populates_config(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://op:op@localhost/trade_journal")
    cfg = load_config()  # will fail — Config has no database_url field yet
    assert cfg.database_url == "postgresql://op:op@localhost/trade_journal"
```
Run: `FAIL` — `Config` has no `database_url`, missing-var check absent.

**GREEN**:
- Add `psycopg[binary]` to `pyproject.toml` `dependencies`.
- Add `database_url: str` field to `Config` dataclass.
- In `load_config()`, read `DATABASE_URL = os.environ.get("DATABASE_URL", "")` and add `"DATABASE_URL"` to the `missing` list check.

**REFACTOR**: Confirm existing `missing`-variable pattern is reused without duplication; no new branch structure needed.

---

## Group B — Domain Layer (PARALLEL: T-02 and T-03 can be written simultaneously)

### [x] T-02 · JournalEntry, JournalResult, ClosedTrade value objects

**Spec**: REQ-02, REQ-03, REQ-04, Scenario 2.1
**Files**: `src/domain/entities/journal.py`, `tests/unit/test_journal_entities.py`

**RED** — Write `tests/unit/test_journal_entities.py`:
```python
def test_atr_at_entry_derived_from_sl_distance():
    # REQ-03: atr_at_entry = sl_distance / SL_ATR_MULT; no direct supply
    entry = JournalEntry(deal_id="D1", symbol="EURUSD", direction="BUY",
                         opened_at=..., decision_candle_ts=...,
                         filled_price=1.10, sl_distance=0.0020, tp_distance=0.0020,
                         position_size=10000.0,
                         bid_at_decision=None, ask_at_decision=None)
    assert entry.atr_at_entry == pytest.approx(0.0010)

def test_journal_entry_is_immutable():
    entry = JournalEntry(...)
    with pytest.raises((AttributeError, TypeError)):
        entry.deal_id = "X"

def test_journal_result_close_source_enum_values():
    for src in ("SL", "TP", "USER", "CLOSE_OUT"):
        r = JournalResult(deal_id="D1", closed_at=..., close_price=1.10,
                          close_source=src, realized_pnl=10.0, fees=0.5,
                          realized_r=0.95, reconciled_at=...)
        assert r.close_source == src

def test_closed_trade_holds_pnl_and_fees():
    ct = ClosedTrade(deal_id="D1", closed_at=..., close_price=1.10,
                     close_source="SL", realized_pnl=-20.0, fees=1.0)
    assert ct.realized_pnl == pytest.approx(-20.0)
```
Run: `FAIL` — module does not exist.

**GREEN** — Create `src/domain/entities/journal.py`:
- `JournalEntry`: `@dataclass(frozen=True, slots=True)`. Constructor takes all fields EXCEPT `atr_at_entry`. Use `__post_init__` + `object.__setattr__` to compute and set `atr_at_entry = sl_distance / SL_ATR_MULT`. Import `SL_ATR_MULT` from `domain.adapters.fade_strategy` (re-exports it) or directly via the sys.path shim already in `fade_strategy.py`.
- `JournalResult`: `@dataclass(frozen=True, slots=True)`, all fields as per REQ-04.
- `ClosedTrade`: `@dataclass(frozen=True, slots=True)` — `deal_id`, `closed_at`, `close_price`, `close_source`, `realized_pnl`, `fees`. Used by reconciler as the return type of `TradeHistoryPort.closed_trade()`.

**REFACTOR**: Confirm `SL_ATR_MULT` import path is the single source (no duplicate constant). Keep `__post_init__` minimal — just the derivation.

---

### [x] T-03 · TradeJournalPort and TradeHistoryPort ABCs

**Spec**: REQ-01, REQ-08
**Files**: `src/domain/ports/trade_journal_port.py`, `src/domain/ports/trade_history_port.py`

**RED** — Write `tests/unit/test_ports_are_abstract.py`:
```python
def test_trade_journal_port_cannot_be_instantiated():
    with pytest.raises(TypeError):
        TradeJournalPort()

def test_trade_history_port_cannot_be_instantiated():
    with pytest.raises(TypeError):
        TradeHistoryPort()

def test_trade_journal_port_declares_three_methods():
    assert hasattr(TradeJournalPort, "record_entry")
    assert hasattr(TradeJournalPort, "record_result")
    assert hasattr(TradeJournalPort, "open_entries")

def test_trade_history_port_declares_closed_trade():
    assert hasattr(TradeHistoryPort, "closed_trade")
```
Run: `FAIL` — modules do not exist.

**GREEN**:

`src/domain/ports/trade_journal_port.py`:
```python
from abc import ABC, abstractmethod
from collections.abc import Sequence
from domain.entities.journal import JournalEntry, JournalResult

class TradeJournalPort(ABC):
    @abstractmethod
    def record_entry(self, entry: JournalEntry) -> None: ...
    @abstractmethod
    def record_result(self, result: JournalResult) -> None: ...
    @abstractmethod
    def open_entries(self) -> Sequence[JournalEntry]: ...
```

`src/domain/ports/trade_history_port.py`:
```python
from abc import ABC, abstractmethod
from datetime import datetime
from domain.entities.journal import ClosedTrade

class TradeHistoryPort(ABC):
    @abstractmethod
    def closed_trade(self, deal_id: str, opened_at: datetime) -> ClosedTrade | None: ...
```

**REFACTOR**: Ensure `BrokerPort` is untouched (ISP contract).

---

## Group C — Test Doubles (PARALLEL: T-04a and T-04b independent)

### [x] T-04a · FakeJournalPort

**Spec**: supports REQ-05, REQ-06, Scenarios 3.1–3.3
**Files**: `tests/fakes/fake_journal.py`

No RED/GREEN cycle here — this is a test double, not production code. Write directly:

- `FakeJournalPort(TradeJournalPort)`: stores `record_entry` calls in `entry_calls: list[JournalEntry]`, `record_result` calls in `result_calls: list[JournalResult]`, `open_entries` returns configurable list.
- Variant: `RaisingJournalPort(TradeJournalPort)` — `record_entry` always raises `RuntimeError("journal down")`. Used by Scenario 3.3.

---

### [x] T-04b · FakeTradeHistoryPort

**Spec**: supports Scenarios 5.1–5.3
**Files**: `tests/fakes/fake_history.py`

Write directly:

- `FakeTradeHistoryPort(TradeHistoryPort)`: constructed with `responses: dict[str, ClosedTrade | None | Exception]`. `closed_trade(deal_id, opened_at)` looks up `deal_id` — if value is an `Exception` instance, raises it; otherwise returns it (including `None` for "still open").

---

## Group D — Migrations

### [x] T-05 · SQL migration file + idempotent migration runner

**Spec**: REQ-15, REQ-16, REQ-17, Scenarios 7.1–7.3
**Files**: `src/infrastructure/postgres/migrations/001_create_trade_entries.sql`, `src/infrastructure/postgres/migration_runner.py`, `src/infrastructure/postgres/__init__.py`

**RED** — Write `tests/unit/test_migration_runner.py` using an in-memory SQLite stand-in OR a fixture that injects a psycopg connection from `DATABASE_URL`. Since the runner uses raw SQL, test its logic with `FakeConnection` doubles that capture executed SQL:

```python
class _FakeConn:
    """Captures executed SQL statements."""
    def __init__(self): self.executed = []; self._tables = set()
    def execute(self, sql, params=()): self.executed.append(sql.strip())
    def fetchall(self): return []  # no applied migrations
    def commit(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass

def test_runner_creates_schema_migrations_table_on_first_run():
    conn = _FakeConn()
    run_migrations(conn, migrations_dir=...) # fails — function does not exist
    assert any("CREATE TABLE" in s and "schema_migrations" in s for s in conn.executed)

def test_runner_applies_pending_sql_in_order():
    ...

def test_runner_skips_already_applied_migration():
    ...
```
Run: `FAIL` — `run_migrations` does not exist.

**GREEN** — Create `src/infrastructure/postgres/migration_runner.py`:
- `run_migrations(conn, migrations_dir: Path) -> None`
- Ensure `schema_migrations` exists (CREATE TABLE IF NOT EXISTS).
- Read applied set from `schema_migrations`.
- Glob `*.sql` files in `migrations_dir`, sort numerically by filename prefix.
- For each file not in the applied set: execute its SQL, INSERT the filename into `schema_migrations`, commit.

Create `src/infrastructure/postgres/migrations/001_create_trade_entries.sql` with the DDL from the design (schema_migrations table + trade_entries table + partial index).

**REFACTOR**: `migrations_dir` defaults to `Path(__file__).parent / "migrations"` so callers don't need to pass it in normal use.

---

## Group E — Postgres Adapter

### [x] T-06 · PostgresTradeJournal adapter

**Spec**: REQ-01, Scenarios 1.1–1.4, Scenario 4.1, Scenario 4.2
**Files**: `src/infrastructure/postgres/connection.py`, `src/infrastructure/postgres/journal_adapter.py`

**KEYSTONE RED TEST** — `tests/unit/test_postgres_journal_adapter.py` using a fake psycopg connection:

```python
class _FakeCursor:
    def __init__(self, rows=()): self._rows = list(rows); self.executed = []
    def execute(self, sql, params=()): self.executed.append((sql, params))
    def fetchall(self): return self._rows
    def __enter__(self): return self
    def __exit__(self, *a): pass

class _FakeConn:
    def __init__(self, rows=()): self._rows = rows; self.committed = 0
    def cursor(self): return _FakeCursor(self._rows)
    def commit(self): self.committed += 1
    def __enter__(self): return self
    def __exit__(self, *a): pass

def test_record_entry_executes_insert_on_conflict_do_nothing(make_entry):
    conn = _FakeConn()
    adapter = PostgresTradeJournal(conn)
    adapter.record_entry(make_entry("D1"))
    cursor_sql = conn.cursor().executed  # check SQL shape
    assert any("ON CONFLICT" in sql for sql, _ in cursor_sql)
    assert conn.committed == 1

def test_record_entry_idempotent_on_duplicate(make_entry):
    # second call must not raise even if ON CONFLICT DO NOTHING swallows it
    conn = _FakeConn()
    adapter = PostgresTradeJournal(conn)
    adapter.record_entry(make_entry("D1"))
    adapter.record_entry(make_entry("D1"))  # should not raise

def test_record_result_uses_guarded_update(make_result):
    conn = _FakeConn()
    adapter = PostgresTradeJournal(conn)
    adapter.record_result(make_result("D1"))
    cursor_sql = conn.cursor().executed
    assert any("reconciled_at IS NULL" in sql for sql, _ in cursor_sql)

def test_open_entries_filters_reconciled_at_null(make_entry_row):
    open_row = make_entry_row("D1", reconciled_at=None)
    closed_row = make_entry_row("D2", reconciled_at="2024-01-01T10:00:00Z")
    conn = _FakeConn(rows=[open_row])  # DB already filtered by WHERE
    adapter = PostgresTradeJournal(conn)
    entries = adapter.open_entries()
    assert len(entries) == 1
    assert entries[0].deal_id == "D1"
```
Run: `FAIL` — `PostgresTradeJournal` does not exist.

**GREEN**:

`src/infrastructure/postgres/connection.py`:
```python
import psycopg

def connect(database_url: str):
    return psycopg.connect(database_url)
```

`src/infrastructure/postgres/journal_adapter.py` — `PostgresTradeJournal(TradeJournalPort)`:
- `record_entry`: `INSERT INTO trade_entries (...) VALUES (...) ON CONFLICT (deal_id) DO NOTHING`
- `record_result`: `UPDATE trade_entries SET closed_at=%s, close_price=%s, close_source=%s, realized_pnl=%s, fees=%s, realized_r=%s, reconciled_at=now() WHERE deal_id=%s AND reconciled_at IS NULL`
- `open_entries`: `SELECT ... FROM trade_entries WHERE reconciled_at IS NULL` → map rows to `JournalEntry`

**REFACTOR**: Extract SQL strings as module-level constants. Confirm `bid_at_decision` and `ask_at_decision` nullable fields are handled in both INSERT and SELECT.

---

## Group F — Operator Wiring

### [x] T-07 · Wire journal into RunTradingCycleUseCase (best-effort record_entry)

**Spec**: REQ-05, REQ-06, Scenarios 3.1–3.3
**Files**: `src/application/trading_cycle.py`, `tests/unit/test_trading_cycle.py`

**RED** — Extend `tests/unit/test_trading_cycle.py` with three new scenarios:

```python
def test_journal_record_entry_called_after_successful_open(make_use_case):
    # Scenario 3.1
    journal = FakeJournalPort()
    order = OrderResult(order_id="D1", status="OPEN", filled_price=1.1001)
    uc = make_use_case(order_result=order, journal=journal)
    uc.execute()
    assert len(journal.entry_calls) == 1
    assert journal.entry_calls[0].deal_id == "D1"

def test_journal_not_called_when_no_signal(make_use_case):
    # Scenario 3.2
    journal = FakeJournalPort()
    uc = make_use_case(signal=None, journal=journal)
    uc.execute()
    assert journal.entry_calls == []

def test_journal_failure_does_not_crash_cycle(make_use_case):
    # Scenario 3.3
    journal = RaisingJournalPort()
    order = OrderResult(order_id="D1", status="OPEN", filled_price=1.1001)
    uc = make_use_case(order_result=order, journal=journal)
    result = uc.execute()
    assert result is not None  # cycle returns normally
```
Run: `FAIL` — `RunTradingCycleUseCase` has no `journal` parameter.

**GREEN** — Modify `src/application/trading_cycle.py`:
- Add `journal: TradeJournalPort` constructor parameter (default to a no-op `NullJournalPort` so existing callers need no change — or make it required and fix all callers; pick the option that doesn't break existing tests).
- After `result = self._broker.open_position(...)`, add:
  ```python
  try:
      self._journal.record_entry(self._build_entry(signal, result, decision_candle_ts))
  except Exception:
      self._logger.exception("journal record_entry failed; continuing")
  ```
- Implement `_build_entry(signal, result, decision_candle_ts) -> JournalEntry` — construct `JournalEntry` from signal fields + `result.order_id` as `deal_id` + `result.filled_price` + current UTC time as `opened_at`.

**REFACTOR**: `_build_entry` must not duplicate field derivation logic already in `JournalEntry.__post_init__`. `NullJournalPort` (if used) lives in `domain.ports.trade_journal_port` or a shared location, not in tests.

---

### [x] T-08 · Wire journal into operator composition root

**Spec**: REQ-15, REQ-18, Scenario 8.1
**Files**: `src/__main__.py`

**RED** — No new pytest test needed here (Scenario 8.1 is already covered by T-01's config test). Verify that the existing `tests/unit/test_main_loop.py` still passes after changes. Confirm by running suite before modifying.

**GREEN** — Modify `src/__main__.py` `build_use_case`:
1. Call `run_migrations(connect(config.database_url))` before building the use case.
2. Pass `journal=PostgresTradeJournal(connect(config.database_url))` into `RunTradingCycleUseCase`.

**REFACTOR**: Connection should be created once per process start, not per cycle. Store in `build_use_case` scope and pass the same connection object to both migration runner and the adapter.

---

### [x] T-09 · Integration test — Postgres journal round-trip

**Spec**: Scenarios 1.1–1.4, 4.1–4.2 (real DB)
**Files**: `tests/integration/test_postgres_journal.py`

**RED** — Write the integration test with `pytest.mark.skipif` guard:

```python
import os
import pytest
DATABASE_URL = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")

def test_record_entry_then_open_entries_round_trip(pg_conn):
    adapter = PostgresTradeJournal(pg_conn)
    entry = make_entry("D1")
    adapter.record_entry(entry)
    open_ = adapter.open_entries()
    assert any(e.deal_id == "D1" for e in open_)

def test_record_result_closes_entry_guard(pg_conn):
    adapter = PostgresTradeJournal(pg_conn)
    entry = make_entry("D1")
    adapter.record_entry(entry)
    result = make_result("D1")
    adapter.record_result(result)
    open_ = adapter.open_entries()
    assert not any(e.deal_id == "D1" for e in open_)

def test_double_reconcile_is_no_op(pg_conn):
    adapter = PostgresTradeJournal(pg_conn)
    entry = make_entry("D1")
    adapter.record_entry(entry)
    result = make_result("D1")
    adapter.record_result(result)
    adapter.record_result(result)  # second call must not raise or double-write
    open_ = adapter.open_entries()
    assert not any(e.deal_id == "D1" for e in open_)
```
Run (without DATABASE_URL): `SKIP` — correct.
Run (with DATABASE_URL pointing at docker postgres): `FAIL` — table does not exist yet until migration runs.

**GREEN**: `pg_conn` fixture calls `run_migrations(conn)` before yielding, then wraps each test in a SAVEPOINT rollback for isolation.

**REFACTOR**: Confirm fixture cleans up correctly so tests are order-independent.

---

## Group G — Reconciler Path

### [x] T-10 · ReconcileClosedTradesUseCase

**Spec**: REQ-07, REQ-08, REQ-09, REQ-10, REQ-11, Scenarios 4.1–4.2, 5.1–5.4
**Files**: `src/application/reconcile_closed_trades.py`, `tests/unit/test_reconcile_use_case.py`

**RED** — Write `tests/unit/test_reconcile_use_case.py`:

```python
def test_open_entry_gets_reconciled_when_closed(fake_journal, fake_history):
    # Scenario 5.1 + realized_r math
    entry = make_entry("D1", filled_price=1.10, sl_distance=0.0020,
                        position_size=10000.0, direction="BUY")
    fake_journal.open_ = [entry]
    fake_history.responses["D1"] = ClosedTrade(
        deal_id="D1", closed_at=now(), close_price=1.1019,
        close_source="TP", realized_pnl=19.0, fees=1.0)
    uc = ReconcileClosedTradesUseCase(fake_journal, fake_history)
    uc.execute()
    assert len(fake_journal.result_calls) == 1
    r = fake_journal.result_calls[0]
    assert r.deal_id == "D1"
    assert r.realized_r == pytest.approx(0.9)  # (19.0 - 1.0) / (0.0020 * 10000)

def test_still_open_position_skipped(fake_journal, fake_history):
    # Scenario 5.2
    fake_journal.open_ = [make_entry("D1")]
    fake_history.responses["D1"] = None
    uc = ReconcileClosedTradesUseCase(fake_journal, fake_history)
    uc.execute()
    assert fake_journal.result_calls == []

def test_lookup_failure_does_not_abort_remaining(fake_journal, fake_history):
    # Scenario 5.3
    fake_journal.open_ = [make_entry("D1"), make_entry("D2")]
    fake_history.responses["D1"] = RuntimeError("API down")
    fake_history.responses["D2"] = ClosedTrade(deal_id="D2", ...)
    uc = ReconcileClosedTradesUseCase(fake_journal, fake_history)
    uc.execute()
    assert len(fake_journal.result_calls) == 1
    assert fake_journal.result_calls[0].deal_id == "D2"

def test_realized_r_sell_win(fake_journal, fake_history):
    # REQ-07 sign for SELL: move = filled_price - close_price
    entry = make_entry("D1", filled_price=1.10, sl_distance=0.0020,
                        position_size=10000.0, direction="SELL")
    fake_history.responses["D1"] = ClosedTrade(
        ..., realized_pnl=20.0, fees=1.0)
    uc = ReconcileClosedTradesUseCase(fake_journal, fake_history)
    uc.execute()
    r = fake_journal.result_calls[0]
    assert r.realized_r == pytest.approx(0.95)

def test_realized_r_losing_trade(fake_journal, fake_history):
    # Scenario 4.2
    entry = make_entry("D1", filled_price=1.10, sl_distance=0.0020,
                        position_size=10000.0, direction="BUY")
    fake_history.responses["D1"] = ClosedTrade(
        ..., realized_pnl=-20.0, fees=1.0)
    uc = ReconcileClosedTradesUseCase(fake_journal, fake_history)
    uc.execute()
    r = fake_journal.result_calls[0]
    assert r.realized_r == pytest.approx(-1.05)
```
Run: `FAIL` — `ReconcileClosedTradesUseCase` does not exist.

**GREEN** — Create `src/application/reconcile_closed_trades.py`:
```python
class ReconcileClosedTradesUseCase:
    def __init__(self, journal: TradeJournalPort, history: TradeHistoryPort) -> None:
        self._journal = journal
        self._history = history

    def execute(self) -> None:
        for entry in self._journal.open_entries():
            try:
                closed = self._history.closed_trade(entry.deal_id, entry.opened_at)
                if closed is None:
                    continue
                realized_r = self._compute_r(entry, closed)
                self._journal.record_result(JournalResult(
                    deal_id=entry.deal_id,
                    closed_at=closed.closed_at,
                    close_price=closed.close_price,
                    close_source=closed.close_source,
                    realized_pnl=closed.realized_pnl,
                    fees=closed.fees,
                    realized_r=realized_r,
                    reconciled_at=datetime.now(UTC),
                ))
            except Exception:
                logger.exception("reconcile failed for deal_id=%s", entry.deal_id)

    def _compute_r(self, entry: JournalEntry, closed: ClosedTrade) -> float:
        risk_currency = entry.sl_distance * entry.position_size
        return (closed.realized_pnl - closed.fees) / risk_currency
```

**REFACTOR**: `_compute_r` is pure — extract to a module-level function `compute_realized_r(pnl, fees, sl_distance, position_size)` so it can be tested directly and reused.

---

### [x] T-11 · CapitalTradeHistory adapter

**Spec**: REQ-08 (TradeHistoryPort impl)
**Files**: `src/infrastructure/capital/history_adapter.py`

**RED** — Write `tests/unit/test_capital_trade_history.py` using `FakeHttp` (existing fake):

```python
def test_closed_trade_returns_none_when_activity_empty(fake_http):
    fake_http.register("GET", "/history/activity", body={"activities": []})
    adapter = CapitalTradeHistory(session=fake_session, http=fake_http, base_url=BASE)
    result = adapter.closed_trade("D1", opened_at=datetime(...))
    assert result is None

def test_closed_trade_returns_closed_trade_on_hit(fake_http):
    fake_http.register("GET", "/history/activity", body={
        "activities": [{"dealId": "D1", "status": "ACCEPTED", "type": "POSITION_CLOSED",
                         "date": "2024-01-01T10:00:00Z", "level": "1.1019"}]
    })
    fake_http.register("GET", "/history/transactions", body={
        "transactions": [{"reference": "D1", "profitAndLoss": "19.0",
                           "commission": "1.0"}]
    })
    adapter = CapitalTradeHistory(session=fake_session, http=fake_http, base_url=BASE)
    result = adapter.closed_trade("D1", opened_at=datetime(...))
    assert result is not None
    assert result.deal_id == "D1"
    assert result.realized_pnl == pytest.approx(19.0)
    assert result.fees == pytest.approx(1.0)
```
Run: `FAIL` — `CapitalTradeHistory` does not exist.

**GREEN** — Create `src/infrastructure/capital/history_adapter.py`:
- `closed_trade(deal_id, opened_at)`:
  1. `GET /history/activity?dealId={deal_id}&detailed=true&from={opened_at ISO}&to={now ISO}`
  2. Filter `activities` by `dealId == deal_id` and `type == "POSITION_CLOSED"`.
  3. If no match, return `None`.
  4. `GET /history/transactions?from={opened_at ISO}&to={now ISO}` — filter by `reference == deal_id`.
  5. Extract `profitAndLoss` (realized_pnl) and `commission` (fees) from transaction row.
  6. Return `ClosedTrade(...)`.

**REFACTOR**: Timestamp ISO formatting must use UTC and match Capital.com API format. Extract `_to_iso(dt)` helper. Note the open question about P&L source (activity vs transaction) — use transaction row as primary (design assumption) but keep the mapping isolated so it can be swapped.

---

### [x] T-12 · Reconciler entrypoint (composition root + 1-min loop)

**Spec**: REQ-12, REQ-13, REQ-14, Scenario 6.1
**Files**: `src/reconciler.py`, `tests/unit/test_reconciler_loop.py`

**RED** — Write `tests/unit/test_reconciler_loop.py`:

```python
def test_reconciler_loop_catches_exception_and_continues():
    # Scenario 6.1
    call_count = 0
    def failing_use_case():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("use case exploded")

    fake_clock = FakeClock(...)
    _run_one_cycle(failing_use_case, fake_clock, logger=logging.getLogger("test"))
    assert call_count == 1  # did not re-raise

def test_reconciler_loop_sleeps_to_boundary():
    ...
```
Run: `FAIL` — `_run_one_cycle` / `run_reconciler_forever` does not exist.

**GREEN** — Create `src/reconciler.py`:
- `run_reconciler_forever(use_case, clock, logger)` — 60-second sleep loop:
  ```python
  while True:
      clock.sleep(60)
      try:
          use_case.execute()
      except Exception:
          logger.exception("reconciler cycle failed; retrying next boundary")
  ```
- `if __name__ == "__main__":` composition root — load config, connect to DB, run migrations, create `CapitalSession`, create `CapitalTradeHistory`, create `PostgresTradeJournal`, build `ReconcileClosedTradesUseCase`, call `run_reconciler_forever`.

**REFACTOR**: Composition root pattern mirrors `__main__.py` — extract shared logging setup if not already done. Do not merge the two entrypoints (REQ-12/REQ-13: separate OS processes).

---

## Group H — Infrastructure Bring-up

### [x] T-13 · docker-compose.yml + Makefile

**Spec**: REQ-19, REQ-20
**Files**: `docker-compose.yml`, `Makefile` (both in `operator/`)

No RED/GREEN needed — these are declarative infra files, not application code.

Write `operator/docker-compose.yml`:
```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: trade_journal
      POSTGRES_USER: operator
      POSTGRES_PASSWORD: operator_dev
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
volumes:
  pgdata: {}
```

Write `operator/Makefile`:
```makefile
.PHONY: up down logs operator reconciler

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

operator:
	cd src && ../.venv/bin/python3 -m src

reconciler:
	cd src && ../.venv/bin/python3 -m src.reconciler
```

Verify `make up` starts only postgres (REQ-19) and `make operator` / `make reconciler` are independent (REQ-20).

---

## Ordered Execution Sequence for sdd-apply

```
T-01  psycopg dep + DATABASE_URL config         [sequential — everything depends on this]
T-02  Journal entities (JournalEntry/Result)    [PARALLEL with T-03]
T-03  Ports (TradeJournalPort, TradeHistoryPort)[PARALLEL with T-02]
T-04a FakeJournalPort                           [PARALLEL with T-04b, after T-03]
T-04b FakeTradeHistoryPort                      [PARALLEL with T-04a, after T-03]
T-05  Migration SQL + runner                    [after T-02 + T-03]
T-06  PostgresTradeJournal adapter (KEYSTONE)   [after T-05]
T-07  Operator wiring (best-effort record_entry)[after T-04a + T-06]
T-08  Operator composition root (DB wiring)     [after T-07]
T-09  Integration test — journal round-trip     [PARALLEL with T-07, after T-06]
T-10  ReconcileClosedTradesUseCase              [after T-04a + T-04b + T-03]
T-11  CapitalTradeHistory adapter               [after T-03]
T-12  Reconciler entrypoint                     [after T-10 + T-11]
T-13  docker-compose + Makefile                 [PARALLEL — no code deps]
```

---

## Requirements Traceability

| Task | Spec Requirements |
|------|------------------|
| T-01 | REQ-18, Scenario 8.1 |
| T-02 | REQ-02, REQ-03, REQ-04, Scenario 2.1 |
| T-03 | REQ-01, REQ-08 |
| T-04a/b | (test infrastructure for T-07, T-10) |
| T-05 | REQ-15, REQ-16, REQ-17, Scenarios 7.1–7.3 |
| T-06 | REQ-01, Scenarios 1.1–1.4 |
| T-07 | REQ-05, REQ-06, Scenarios 3.1–3.3 |
| T-08 | REQ-15, REQ-18, Scenario 8.1 |
| T-09 | Scenarios 1.1–1.4, 4.1–4.2 (integration) |
| T-10 | REQ-07, REQ-09, REQ-10, REQ-11, Scenarios 4.1–4.2, 5.1–5.4 |
| T-11 | REQ-08 (TradeHistoryPort impl) |
| T-12 | REQ-12, REQ-13, REQ-14, Scenario 6.1 |
| T-13 | REQ-19, REQ-20 |

---

## Open Questions (carry forward to apply)

- [ ] Fees source: design assumes `/history/transactions` TRADE_COMMISSION row for `fees` and `realized_pnl`. Confirm P&L is from transaction row, not activity row. If wrong, only `history_adapter.py` (T-11) changes.
- [ ] `NullJournalPort` vs required param: decide whether journal is optional in `RunTradingCycleUseCase` (null object) or always required (simpler, but requires updating existing test helpers). Recommendation: always-required + update `_make_use_case` fixture in `test_trading_cycle.py`.
- [ ] `order_id` vs `deal_id`: `OrderResult.order_id` — confirm Capital.com returns the same `dealId` string in this field that `/history/activity` uses for matching. If not, T-07 and T-11 need alignment.
