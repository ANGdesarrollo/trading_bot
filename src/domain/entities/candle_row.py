from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class CandleRow:
    provider: str = "capital"
    _: dataclasses.KW_ONLY
    epic: str = dataclasses.field()
    resolution: str = dataclasses.field()
    candle_start: datetime = dataclasses.field()
    open_bid: float = dataclasses.field()
    high_bid: float = dataclasses.field()
    low_bid: float = dataclasses.field()
    close_bid: float = dataclasses.field()
    open_ask: float = dataclasses.field()
    high_ask: float = dataclasses.field()
    low_ask: float = dataclasses.field()
    close_ask: float = dataclasses.field()

    def __post_init__(self) -> None:
        if self.candle_start.tzinfo is None or self.candle_start.tzinfo != timezone.utc:
            raise ValueError(f"candle_start must be UTC-aware, got {self.candle_start!r}")
