from __future__ import annotations

import logging
from datetime import datetime, timezone

from domain.adapters.fade_strategy import SL_ATR_MULT
from domain.entities.journal import JournalEntry
from domain.entities.order import OrderResult
from domain.entities.signal import Signal
from domain.ports.broker_port import BrokerPort
from domain.ports.candle_store_port import CandleStorePort
from domain.ports.clock_port import ClockPort
from domain.ports.strategy_port import StrategyPort
from domain.ports.trade_journal_port import TradeJournalPort


class RunTradingCycleUseCase:
    def __init__(
        self,
        broker: BrokerPort,
        strategy: StrategyPort,
        symbol: str,
        size: float,
        logger: logging.Logger,
        clock: ClockPort,
        poll_minutes: int,
        candle_store: CandleStorePort,
        resolution: str,
        journal: TradeJournalPort,
    ) -> None:
        self._broker = broker
        self._strategy = strategy
        self._symbol = symbol
        self._size = size
        self._logger = logger
        self._clock = clock
        self._poll_minutes = poll_minutes
        self._candle_store = candle_store
        self._resolution = resolution
        self._journal = journal

    def execute(self) -> OrderResult | None:
        if self._broker.has_open_position(self._symbol):
            self._logger.info("position already open; skipping placement")
            return None

        candles = self._candle_store.recent_candles(
            self._symbol, self._resolution, self._strategy.required_candles)

        if len(candles) < self._strategy.required_candles:
            return None

        expected_decision_ts = self._expected_boundary()

        if candles[-1].timestamp != expected_decision_ts:
            self._logger.warning(
                "stale candle for %s at boundary %s; expected %s, got %s; skipping",
                self._symbol, expected_decision_ts,
                expected_decision_ts, candles[-1].timestamp,
            )
            return None

        signal = self._strategy.evaluate(candles)
        if signal is None:
            return None

        result = self._broker.open_position(self._symbol, signal, self._size)
        self._logger.info(
            "order placed",
            extra={"filled_price": result.filled_price},
        )
        try:
            entry = self._build_entry(signal, result, expected_decision_ts)
            self._journal.record_entry(entry)
        except Exception:
            self._logger.exception("journal record_entry failed; continuing")
        return result

    def _expected_boundary(self) -> datetime:
        period_secs = self._poll_minutes * 60
        now_epoch = self._clock.utcnow().timestamp()
        boundary_epoch = now_epoch - (now_epoch % period_secs)
        return datetime.fromtimestamp(boundary_epoch - period_secs, tz=timezone.utc)

    def _build_entry(
        self,
        signal: Signal,
        result: OrderResult,
        decision_candle_ts: datetime,
    ) -> JournalEntry:
        return JournalEntry(
            deal_id=result.order_id,
            symbol=self._symbol,
            direction=signal.direction.name,
            opened_at=self._clock.utcnow(),
            decision_candle_ts=decision_candle_ts,
            filled_price=result.filled_price,
            sl_distance=signal.sl_distance,
            tp_distance=signal.tp_distance,
            atr_at_entry=signal.sl_distance / SL_ATR_MULT,
            position_size=self._size,
            bid_at_decision=None,
            ask_at_decision=None,
        )
