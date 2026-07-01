from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime

from domain.entities.candle_row import CandleRow


class CandleHistoryPort(ABC):
    @abstractmethod
    def fetch_history(
        self,
        *,
        provider: str = "capital",
        epic: str,
        resolution: str,
        count: int,
        since: datetime | None,
    ) -> Sequence[CandleRow]:
        """Fetch up to `count` closed candles for `provider`. If `since` is given, fetch from that point forward."""
