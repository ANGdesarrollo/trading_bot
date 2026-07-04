from __future__ import annotations

import logging
from dataclasses import dataclass

from domain.ports.portfolio_broker_port import PortfolioBrokerPort
from domain.strategy.portfolio import BASKET, rebalance_orders

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrderLine:
    symbol: str
    current_usd: float
    target_usd: float
    delta: float
    action: str


@dataclass(frozen=True)
class RebalanceSummary:
    equity: float
    orders: tuple[OrderLine, ...]
    executed: bool


class RunPortfolioRebalanceUseCase:
    def __init__(
        self,
        broker: PortfolioBrokerPort,
        min_order_usd: float = 10.0,
    ) -> None:
        self._broker = broker
        self._min_order_usd = min_order_usd

    def execute(self, *, execute: bool) -> RebalanceSummary:
        cash = self._broker.available_cash()
        positions = self._broker.positions()
        equity = sum(positions.values()) + cash

        _log.info("portfolio equity=%.2f cash=%.2f positions=%s", equity, cash, len(positions))

        deltas = rebalance_orders(positions, cash=cash)
        target_per_asset = equity / len(BASKET)

        order_lines = tuple(
            OrderLine(
                symbol=symbol,
                current_usd=positions.get(symbol, 0.0),
                target_usd=target_per_asset,
                delta=delta,
                action="BUY" if delta > 0 else "SELL" if delta < 0 else "HOLD",
            )
            for symbol, delta in deltas.items()
        )

        self._log_order_table(order_lines, equity, target_per_asset)

        actionable = [o for o in order_lines if abs(o.delta) >= self._min_order_usd]

        if execute:
            sells = [o for o in actionable if o.delta < 0]
            buys = [o for o in actionable if o.delta > 0]

            for order in sells:
                _log.info("SELL %s %.2f", order.symbol, abs(order.delta))
                self._broker.sell(order.symbol, abs(order.delta))

            for order in buys:
                _log.info("BUY  %s %.2f", order.symbol, order.delta)
                self._broker.buy(order.symbol, order.delta)
        else:
            _log.info("dry-run mode — no orders placed")

        return RebalanceSummary(equity=equity, orders=order_lines, executed=execute)

    def _log_order_table(
        self,
        orders: tuple[OrderLine, ...],
        equity: float,
        target_per_asset: float,
    ) -> None:
        _log.info(
            "equity=%.2f  target/asset=%.2f  (%.1f%% each)",
            equity, target_per_asset, 100.0 / len(BASKET),
        )
        _log.info("%-8s %12s %12s %12s  %s", "SYMBOL", "CURRENT", "TARGET", "DELTA", "ACTION")
        for o in sorted(orders, key=lambda x: x.delta):
            _log.info(
                "%-8s %12.2f %12.2f %12.2f  %s",
                o.symbol, o.current_usd, o.target_usd, o.delta, o.action,
            )
