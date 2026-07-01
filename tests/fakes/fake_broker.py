from __future__ import annotations

from domain.entities.order import OrderResult
from domain.entities.signal import Signal
from domain.ports.broker_port import BrokerPort


class FakeBroker(BrokerPort):
    def __init__(
        self,
        *,
        has_open: bool = False,
        order_result: OrderResult | None = None,
    ) -> None:
        self._has_open = has_open
        self._order_result = order_result

        self.open_position_calls: list[tuple[str, Signal, float]] = []

    def has_open_position(self, symbol: str) -> bool:
        return self._has_open

    def open_position(self, symbol: str, signal: Signal, size: float) -> OrderResult:
        self.open_position_calls.append((symbol, signal, size))
        if self._order_result is None:
            raise RuntimeError("FakeBroker: order_result not configured")
        return self._order_result
