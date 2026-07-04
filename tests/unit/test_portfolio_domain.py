import pytest

from domain.strategy.portfolio import (
    BASKET,
    parse_positions,
    rebalance_orders,
    target_allocations,
)


class TestTargetAllocations:
    def test_splits_equity_equally_across_the_eight_assets(self):
        targets = target_allocations(10_000.0)

        assert set(targets) == set(BASKET)
        assert all(amount == pytest.approx(1_250.0) for amount in targets.values())

    def test_rejects_non_positive_equity(self):
        with pytest.raises(ValueError):
            target_allocations(0.0)


class TestRebalanceOrders:
    def test_balanced_portfolio_needs_no_orders(self):
        positions = {symbol: 1_250.0 for symbol in BASKET}

        orders = rebalance_orders(positions)

        assert all(delta == pytest.approx(0.0) for delta in orders.values())

    def test_sells_winners_and_buys_losers_back_to_equal_weight(self):
        positions = {symbol: 1_000.0 for symbol in BASKET}
        positions["BTCUSD"] = 2_000.0
        positions["TLT"] = 800.0

        orders = rebalance_orders(positions)

        equity = 6 * 1_000.0 + 2_000.0 + 800.0
        target = equity / len(BASKET)
        assert orders["BTCUSD"] == pytest.approx(target - 2_000.0)
        assert orders["TLT"] == pytest.approx(target - 800.0)
        assert sum(orders.values()) == pytest.approx(0.0)

    def test_cash_is_deployed_into_targets(self):
        positions = {symbol: 1_000.0 for symbol in BASKET}

        orders = rebalance_orders(positions, cash=800.0)

        assert all(delta == pytest.approx(100.0) for delta in orders.values())

    def test_missing_symbol_becomes_a_full_buy(self):
        positions = {symbol: 1_000.0 for symbol in BASKET if symbol != "EFA"}

        orders = rebalance_orders(positions)

        target = 7_000.0 / len(BASKET)
        assert orders["EFA"] == pytest.approx(target)

    def test_rejects_symbols_outside_the_basket(self):
        positions = {symbol: 1_000.0 for symbol in BASKET}
        positions["AAPL"] = 500.0

        with pytest.raises(ValueError, match="AAPL"):
            rebalance_orders(positions)


class TestParsePositions:
    def test_parses_comma_separated_symbol_value_pairs(self):
        positions = parse_positions("SPY=1300.50,qqq=1200")

        assert positions == {"SPY": 1300.50, "QQQ": 1200.0}

    def test_rejects_malformed_entries(self):
        with pytest.raises(ValueError):
            parse_positions("SPY:1300")
