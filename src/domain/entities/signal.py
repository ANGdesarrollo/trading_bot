from __future__ import annotations

from dataclasses import dataclass

from domain.entities.direction import Direction


@dataclass(frozen=True, slots=True)
class Signal:
    """A strategy's decision to enter a trade, expressed as risk distances.

    sl_distance and tp_distance are relative price offsets the broker anchors
    to the actual fill, so the engine never re-derives risk from a speculative
    signal-time price.
    """

    direction: Direction
    sl_distance: float
    tp_distance: float

    def __post_init__(self) -> None:
        if self.sl_distance <= 0:
            raise ValueError("sl_distance must be > 0")
        if self.tp_distance <= 0:
            raise ValueError("tp_distance must be > 0")
