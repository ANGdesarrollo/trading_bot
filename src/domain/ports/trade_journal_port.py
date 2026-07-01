from __future__ import annotations

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
