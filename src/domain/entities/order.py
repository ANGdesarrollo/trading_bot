from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OrderResult:
    order_id: str
    status: str
    filled_price: float
