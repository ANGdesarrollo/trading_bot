from __future__ import annotations

import pytest

from application.rebalance_portfolio import RebalanceSummary, RunPortfolioRebalanceUseCase
from domain.strategy.portfolio import BASKET


class FakePortfolioBroker:
    def __init__(
        self,
        *,
        cash: float = 0.0,
        positions: dict[str, float] | None = None,
    ) -> None:
        self._cash = cash
        self._positions = positions or {}
        self.buys: list[tuple[str, float]] = []
        self.sells: list[tuple[str, float]] = []

    def available_cash(self) -> float:
        return self._cash

    def positions(self) -> dict[str, float]:
        return dict(self._positions)

    def buy(self, symbol: str, amount_usd: float) -> str:
        self.buys.append((symbol, amount_usd))
        return f"buy-{symbol}"

    def sell(self, symbol: str, amount_usd: float) -> str:
        self.sells.append((symbol, amount_usd))
        return f"sell-{symbol}"


class TestRunPortfolioRebalanceUseCase:
    def _make_use_case(self, broker, min_order_usd: float = 10.0):
        return RunPortfolioRebalanceUseCase(broker=broker, min_order_usd=min_order_usd)

    def test_dry_run_returns_summary_without_calling_broker(self):
        positions = {s: 1_000.0 for s in BASKET}
        positions["BTCUSD"] = 2_000.0
        broker = FakePortfolioBroker(cash=0.0, positions=positions)
        use_case = self._make_use_case(broker)

        summary = use_case.execute(execute=False)

        assert isinstance(summary, RebalanceSummary)
        assert len(broker.buys) == 0
        assert len(broker.sells) == 0

    def test_execute_sells_before_buys(self):
        positions = {s: 1_000.0 for s in BASKET}
        positions["BTCUSD"] = 2_000.0
        broker = FakePortfolioBroker(cash=0.0, positions=positions)
        use_case = self._make_use_case(broker)

        use_case.execute(execute=True)

        assert len(broker.sells) > 0
        assert len(broker.buys) > 0

    def test_balanced_portfolio_places_no_orders(self):
        equity = 10_000.0
        positions = {s: equity / len(BASKET) for s in BASKET}
        broker = FakePortfolioBroker(cash=0.0, positions=positions)
        use_case = self._make_use_case(broker)

        use_case.execute(execute=True)

        assert len(broker.buys) == 0
        assert len(broker.sells) == 0

    def test_dust_orders_below_min_are_skipped(self):
        equity = 10_000.0
        positions = {s: equity / len(BASKET) for s in BASKET}
        positions["SPY"] += 5.0
        positions["QQQ"] -= 5.0
        broker = FakePortfolioBroker(cash=0.0, positions=positions)
        use_case = self._make_use_case(broker, min_order_usd=10.0)

        use_case.execute(execute=True)

        assert len(broker.buys) == 0
        assert len(broker.sells) == 0

    def test_summary_contains_order_table(self):
        positions = {s: 1_000.0 for s in BASKET}
        positions["BTCUSD"] = 2_000.0
        broker = FakePortfolioBroker(cash=200.0, positions=positions)
        use_case = self._make_use_case(broker)

        summary = use_case.execute(execute=False)

        assert len(summary.orders) == len(BASKET)
        btc_order = next(o for o in summary.orders if o.symbol == "BTCUSD")
        assert btc_order.delta < 0

    def test_cash_is_included_in_equity(self):
        positions = {s: 0.0 for s in BASKET}
        broker = FakePortfolioBroker(cash=8_000.0, positions=positions)
        use_case = self._make_use_case(broker)

        summary = use_case.execute(execute=False)

        assert summary.equity == pytest.approx(8_000.0)
        assert all(o.delta == pytest.approx(1_000.0) for o in summary.orders)
