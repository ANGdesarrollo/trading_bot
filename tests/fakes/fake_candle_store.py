from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from domain.entities.candle import Candle
from domain.entities.candle_row import CandleRow
from domain.ports.candle_store_port import CandleStorePort


class FakeCandleStore(CandleStorePort):
    def __init__(
        self,
        *,
        candles: Sequence[Candle] | None = None,
        last_start: datetime | None = None,
    ) -> None:
        self._candles = list(candles or [])
        self._last_start = last_start
        self.recent_candles_calls: list[tuple[str, str, str, int]] = []
        self.last_candle_start_calls: list[tuple[str, str, str]] = []
        self.upsert_calls: list[CandleRow] = []

    def recent_candles(
        self, provider: str = "capital", *, symbol: str, resolution: str, count: int
    ) -> Sequence[Candle]:
        self.recent_candles_calls.append((provider, symbol, resolution, count))
        return self._candles

    def last_candle_start(
        self, provider: str = "capital", *, symbol: str, resolution: str
    ) -> datetime | None:
        self.last_candle_start_calls.append((provider, symbol, resolution))
        return self._last_start

    def upsert_candle(self, row: CandleRow) -> None:
        self.upsert_calls.append(row)
