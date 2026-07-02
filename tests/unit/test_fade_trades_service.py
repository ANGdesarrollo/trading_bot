from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from domain.entities.candle import Candle
from domain.strategy.fade import FadeTrade

_UTC = timezone.utc
_BASE = datetime(2024, 1, 1, 0, 0, 0, tzinfo=_UTC)


def _make_candles(n: int) -> list[Candle]:
    return [
        Candle(_BASE + timedelta(minutes=15 * i), open=1.08, high=1.09, low=1.07, close=1.085)
        for i in range(n)
    ]


_CANDLES_50 = _make_candles(50)

_FAKE_TRADE = FadeTrade(
    run_end_idx=1,
    entry_idx=2,
    exit_idx=4,
    direction=1,
    entry_price=1.08,
    sl_price=1.075,
    tp_price=1.085,
    exit_price=1.085,
    outcome="tp",
    r_multiple=0.95,
)


class TestEmptyInput:
    def test_empty_candles_returns_empty_trades(self):
        from application.fade_trades import build_fade_trades_response
        result = build_fade_trades_response([], symbol="EURUSD", timeframe="15m")
        assert result["trades"] == []

    def test_empty_candles_zeroed_meta(self):
        from application.fade_trades import build_fade_trades_response
        result = build_fade_trades_response([], symbol="EURUSD", timeframe="15m")
        meta = result["meta"]
        assert meta["trades"] == 0
        assert meta["win_rate"] == 0.0
        assert meta["total_r"] == 0.0
        assert meta["expectancy_r"] == 0.0

    def test_empty_candles_symbol_and_timeframe_in_meta(self):
        from application.fade_trades import build_fade_trades_response
        result = build_fade_trades_response([], symbol="GBPUSD", timeframe="1h")
        assert result["meta"]["symbol"] == "GBPUSD"
        assert result["meta"]["timeframe"] == "1h"


class TestIdxToTimestampMapping:
    def test_entry_time_mapped_from_candle_index(self):
        from application.fade_trades import build_fade_trades_response
        with patch("application.fade_trades.simulate_fades", return_value=[_FAKE_TRADE]):
            result = build_fade_trades_response(_CANDLES_50, symbol="EURUSD", timeframe="15m")
        trade = result["trades"][0]
        assert trade["entry_time"] == _CANDLES_50[_FAKE_TRADE.entry_idx].timestamp.isoformat()

    def test_exit_time_mapped_from_candle_index(self):
        from application.fade_trades import build_fade_trades_response
        with patch("application.fade_trades.simulate_fades", return_value=[_FAKE_TRADE]):
            result = build_fade_trades_response(_CANDLES_50, symbol="EURUSD", timeframe="15m")
        trade = result["trades"][0]
        assert trade["exit_time"] == _CANDLES_50[_FAKE_TRADE.exit_idx].timestamp.isoformat()


class TestTradeShape:
    def test_per_trade_has_exactly_nine_keys(self):
        from application.fade_trades import build_fade_trades_response
        with patch("application.fade_trades.simulate_fades", return_value=[_FAKE_TRADE]):
            result = build_fade_trades_response(_CANDLES_50, symbol="EURUSD", timeframe="15m")
        trade = result["trades"][0]
        assert set(trade.keys()) == {
            "entry_time", "exit_time", "direction",
            "entry_price", "sl_price", "tp_price", "exit_price",
            "outcome", "r_multiple",
        }

    def test_r_multiple_rounded_to_3_decimals(self):
        from application.fade_trades import build_fade_trades_response
        raw = FadeTrade(
            run_end_idx=0, entry_idx=1, exit_idx=2, direction=1,
            entry_price=1.08, sl_price=1.075, tp_price=1.085, exit_price=1.085,
            outcome="tp", r_multiple=0.94999999,
        )
        with patch("application.fade_trades.simulate_fades", return_value=[raw]):
            result = build_fade_trades_response(_CANDLES_50, symbol="EURUSD", timeframe="15m")
        assert result["trades"][0]["r_multiple"] == round(0.94999999, 3)


class TestMetaMath:
    def _tp_trade(self, entry_idx: int, exit_idx: int, r: float) -> FadeTrade:
        return FadeTrade(
            run_end_idx=entry_idx - 1, entry_idx=entry_idx, exit_idx=exit_idx,
            direction=1, entry_price=1.08, sl_price=1.075, tp_price=1.085,
            exit_price=1.085, outcome="tp", r_multiple=r,
        )

    def _sl_trade(self, entry_idx: int, exit_idx: int) -> FadeTrade:
        return FadeTrade(
            run_end_idx=entry_idx - 1, entry_idx=entry_idx, exit_idx=exit_idx,
            direction=-1, entry_price=1.08, sl_price=1.085, tp_price=1.075,
            exit_price=1.085, outcome="sl", r_multiple=-1.0,
        )

    def test_win_rate_counts_tp_outcomes(self):
        from application.fade_trades import build_fade_trades_response
        trades = [self._tp_trade(1, 2, 0.9), self._sl_trade(3, 4)]
        with patch("application.fade_trades.simulate_fades", return_value=trades):
            result = build_fade_trades_response(_CANDLES_50, symbol="EURUSD", timeframe="15m")
        assert result["meta"]["win_rate"] == 0.5

    def test_total_r_sums_r_multiples(self):
        from application.fade_trades import build_fade_trades_response
        trades = [self._tp_trade(1, 2, 0.9), self._tp_trade(3, 4, 0.8)]
        with patch("application.fade_trades.simulate_fades", return_value=trades):
            result = build_fade_trades_response(_CANDLES_50, symbol="EURUSD", timeframe="15m")
        assert round(result["meta"]["total_r"], 3) == round(0.9 + 0.8, 3)

    def test_expectancy_r_is_mean_r(self):
        from application.fade_trades import build_fade_trades_response
        trades = [self._tp_trade(1, 2, 1.0), self._sl_trade(3, 4)]
        with patch("application.fade_trades.simulate_fades", return_value=trades):
            result = build_fade_trades_response(_CANDLES_50, symbol="EURUSD", timeframe="15m")
        assert round(result["meta"]["expectancy_r"], 3) == round((1.0 + -1.0) / 2, 3)

    def test_meta_trades_count(self):
        from application.fade_trades import build_fade_trades_response
        trades = [self._tp_trade(1, 2, 0.9), self._tp_trade(3, 4, 0.8)]
        with patch("application.fade_trades.simulate_fades", return_value=trades):
            result = build_fade_trades_response(_CANDLES_50, symbol="EURUSD", timeframe="15m")
        assert result["meta"]["trades"] == 2


class TestCostPct:
    def test_known_symbol_uses_mapped_cost(self):
        from application.fade_trades import build_fade_trades_response, _COST_PCT_BY_SYMBOL, _MIN_CANDLES_FOR_STRATEGY
        candles = _make_candles(_MIN_CANDLES_FOR_STRATEGY)
        captured = {}

        def spy(df, cost_pct):
            captured["cost_pct"] = cost_pct
            return []

        with patch("application.fade_trades.simulate_fades", side_effect=spy):
            build_fade_trades_response(candles, symbol="EURUSD", timeframe="15m")

        assert captured["cost_pct"] == _COST_PCT_BY_SYMBOL["EURUSD"]

    def test_unknown_symbol_uses_default_cost(self):
        from application.fade_trades import build_fade_trades_response, _DEFAULT_COST_PCT, _MIN_CANDLES_FOR_STRATEGY
        candles = _make_candles(_MIN_CANDLES_FOR_STRATEGY)
        captured = {}

        def spy(df, cost_pct):
            captured["cost_pct"] = cost_pct
            return []

        with patch("application.fade_trades.simulate_fades", side_effect=spy):
            build_fade_trades_response(candles, symbol="XYZABC", timeframe="15m")

        assert captured["cost_pct"] == _DEFAULT_COST_PCT

    def test_cost_pct_in_meta(self):
        from application.fade_trades import build_fade_trades_response, _COST_PCT_BY_SYMBOL
        result = build_fade_trades_response([], symbol="EURUSD", timeframe="15m")
        assert result["meta"]["cost_pct"] == _COST_PCT_BY_SYMBOL["EURUSD"]
