from __future__ import annotations

from collections.abc import Sequence

from domain.entities.journal import JournalEntry, JournalResult
from domain.ports.trade_journal_port import TradeJournalPort


class FakeJournalPort(TradeJournalPort):
    def __init__(self, open_: list[JournalEntry] | None = None) -> None:
        self.entry_calls: list[JournalEntry] = []
        self.result_calls: list[JournalResult] = []
        self.open_: list[JournalEntry] = open_ or []

    def record_entry(self, entry: JournalEntry) -> None:
        self.entry_calls.append(entry)

    def record_result(self, result: JournalResult) -> None:
        self.result_calls.append(result)

    def open_entries(self) -> Sequence[JournalEntry]:
        return self.open_


class RaisingJournalPort(TradeJournalPort):
    def record_entry(self, entry: JournalEntry) -> None:
        raise RuntimeError("journal down")

    def record_result(self, result: JournalResult) -> None:
        raise RuntimeError("journal down")

    def open_entries(self) -> Sequence[JournalEntry]:
        return []
