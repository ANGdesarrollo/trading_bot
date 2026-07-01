from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from domain.entities.candle_row import CandleRow

_STALE_PERIODS = 4


@dataclass(slots=True)
class _Partial:
    bid_o: Optional[float] = None
    bid_h: Optional[float] = None
    bid_l: Optional[float] = None
    bid_c: Optional[float] = None
    ask_o: Optional[float] = None
    ask_h: Optional[float] = None
    ask_l: Optional[float] = None
    ask_c: Optional[float] = None

    def has_bid(self) -> bool:
        return self.bid_o is not None

    def has_ask(self) -> bool:
        return self.ask_o is not None

    def complete(self) -> bool:
        return self.has_bid() and self.has_ask()


class PairBuffer:
    """Buffers partial bid/ask ohlc.event pairs until both sides arrive.

    period_ms_map maps (epic, resolution) -> period in milliseconds.
    Used to compute the staleness threshold (4 * period) for eviction.
    """

    def __init__(
        self,
        period_ms_map: dict[tuple[str, str], int],
        provider: str = "capital",
    ) -> None:
        self._period_ms_map = period_ms_map
        self._provider = provider
        self._partials: dict[tuple[str, str, int], _Partial] = {}
        self._newest_t_by_key: dict[tuple[str, str], int] = {}

    def on_event(
        self,
        msg: dict,
        upsert_fn: Callable[[CandleRow], None],
    ) -> None:
        payload = msg.get("payload", msg)
        epic: str = payload["epic"]
        resolution: str = payload["resolution"]
        t_ms: int = payload["t"]
        price_type: str = payload["priceType"]

        pair_key = (epic, resolution)
        buf_key = (epic, resolution, t_ms)

        self._update_newest(pair_key, t_ms)
        self._evict_stale(pair_key)

        partial = self._partials.setdefault(buf_key, _Partial())

        if price_type == "bid":
            partial.bid_o = float(payload["o"])
            partial.bid_h = float(payload["h"])
            partial.bid_l = float(payload["l"])
            partial.bid_c = float(payload["c"])
        elif price_type == "ask":
            partial.ask_o = float(payload["o"])
            partial.ask_h = float(payload["h"])
            partial.ask_l = float(payload["l"])
            partial.ask_c = float(payload["c"])

        if partial.complete():
            candle_start = datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc)
            row = CandleRow(
                provider=self._provider,
                epic=epic,
                resolution=resolution,
                candle_start=candle_start,
                open_bid=partial.bid_o,
                high_bid=partial.bid_h,
                low_bid=partial.bid_l,
                close_bid=partial.bid_c,
                open_ask=partial.ask_o,
                high_ask=partial.ask_h,
                low_ask=partial.ask_l,
                close_ask=partial.ask_c,
            )
            del self._partials[buf_key]
            upsert_fn(row)

    def _update_newest(self, pair_key: tuple[str, str], t_ms: int) -> None:
        current = self._newest_t_by_key.get(pair_key, 0)
        if t_ms > current:
            self._newest_t_by_key[pair_key] = t_ms

    def _evict_stale(self, pair_key: tuple[str, str]) -> None:
        newest = self._newest_t_by_key.get(pair_key, 0)
        period_ms = self._period_ms_map.get(pair_key, 60_000)
        cutoff = newest - _STALE_PERIODS * period_ms

        stale = [k for k in list(self._partials) if k[0] == pair_key[0] and k[1] == pair_key[1] and k[2] < cutoff]
        for k in stale:
            del self._partials[k]
