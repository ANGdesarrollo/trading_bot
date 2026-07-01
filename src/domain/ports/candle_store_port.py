from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime

from domain.entities.candle import Candle
from domain.entities.candle_row import CandleRow


class CandleStorePort(ABC):
    @abstractmethod
    def recent_candles(self, symbol: str, count: int) -> Sequence[Candle]:
        """Return up to `count` most-recently closed candles oldest-first, OHLC as mid=(bid+ask)/2."""

    @abstractmethod
    def last_candle_start(self, symbol: str, resolution: str) -> datetime | None:
        """Return candle_start of the most recent row for (symbol, resolution), or None."""

    @abstractmethod
    def upsert_candle(self, row: CandleRow) -> None:
        """Write or overwrite a single candle row identified by (epic, resolution, candle_start)."""
