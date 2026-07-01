from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain.entities.journal import JournalEntry, JournalResult
from infrastructure.postgres.journal_adapter import PostgresTradeJournal

_NOW = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)


class _FakeCursor:
    def __init__(self, rows: list = ()) -> None:
        self._rows = list(rows)
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql.strip(), params))

    def fetchall(self) -> list:
        return self._rows

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: object) -> None:
        pass


class _FakeConn:
    def __init__(self, rows: list = ()) -> None:
        self._shared_cursor = _FakeCursor(rows=rows)
        self.committed = 0

    def cursor(self) -> _FakeCursor:
        return self._shared_cursor

    def commit(self) -> None:
        self.committed += 1


def _make_entry(deal_id: str = "D1") -> JournalEntry:
    return JournalEntry(
        deal_id=deal_id,
        symbol="EURUSD",
        direction="BUY",
        opened_at=_NOW,
        decision_candle_ts=_NOW,
        filled_price=1.10,
        sl_distance=0.0020,
        tp_distance=0.0020,
        atr_at_entry=0.0010,
        position_size=10000.0,
        bid_at_decision=None,
        ask_at_decision=None,
    )


def _make_result(deal_id: str = "D1") -> JournalResult:
    return JournalResult(
        deal_id=deal_id,
        closed_at=_NOW,
        close_price=1.1019,
        close_source="TP",
        realized_pnl=19.0,
        fees=1.0,
        realized_r=0.9,
        reconciled_at=_NOW,
    )


def test_record_entry_uses_insert_on_conflict_do_nothing():
    conn = _FakeConn()
    adapter = PostgresTradeJournal(conn)
    adapter.record_entry(_make_entry("D1"))
    sqls = [s for s, _ in conn._shared_cursor.executed]
    assert any("ON CONFLICT" in s and "DO NOTHING" in s for s in sqls)


def test_record_entry_commits():
    conn = _FakeConn()
    adapter = PostgresTradeJournal(conn)
    adapter.record_entry(_make_entry("D1"))
    assert conn.committed >= 1


def test_record_entry_idempotent_on_duplicate():
    conn = _FakeConn()
    adapter = PostgresTradeJournal(conn)
    adapter.record_entry(_make_entry("D1"))
    adapter.record_entry(_make_entry("D1"))


def test_record_result_uses_guarded_update():
    conn = _FakeConn()
    adapter = PostgresTradeJournal(conn)
    adapter.record_result(_make_result("D1"))
    sqls = [s for s, _ in conn._shared_cursor.executed]
    assert any("reconciled_at IS NULL" in s for s in sqls)


def test_open_entries_maps_rows_to_journal_entries():
    row = (
        "D1", "EURUSD", "BUY", _NOW, _NOW,
        1.10, 0.0020, 0.0020, 0.0010, 10000.0,
        None, None,
    )
    conn = _FakeConn(rows=[row])
    adapter = PostgresTradeJournal(conn)
    entries = adapter.open_entries()
    assert len(entries) == 1
    assert entries[0].deal_id == "D1"
    assert entries[0].symbol == "EURUSD"


def test_open_entries_returns_empty_when_no_open_rows():
    conn = _FakeConn(rows=[])
    adapter = PostgresTradeJournal(conn)
    entries = adapter.open_entries()
    assert entries == []
