from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class CandleRow:
    epic: str
    resolution: str
    candle_start: datetime
    open_bid: float
    high_bid: float
    low_bid: float
    close_bid: float
    open_ask: float
    high_ask: float
    low_ask: float
    close_ask: float

    def __post_init__(self) -> None:
        if self.candle_start.tzinfo is None or self.candle_start.tzinfo != timezone.utc:
            raise ValueError(f"candle_start must be UTC-aware, got {self.candle_start!r}")
