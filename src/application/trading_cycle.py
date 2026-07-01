from __future__ import annotations

import logging
from datetime import datetime, timezone

from domain.adapters.fade_strategy import SL_ATR_MULT
from domain.entities.journal import JournalEntry
from domain.entities.order import OrderResult
from domain.entities.signal import Signal
from domain.ports.broker_port import BrokerPort
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
        freshness_max_retries: int,
        freshness_retry_seconds: float,
        journal: TradeJournalPort,
    ) -> None:
        self._broker = broker
        self._strategy = strategy
        self._symbol = symbol
        self._size = size
        self._logger = logger
        self._clock = clock
        self._poll_minutes = poll_minutes
        self._freshness_max_retries = freshness_max_retries
        self._freshness_retry_seconds = freshness_retry_seconds
        self._journal = journal

    def execute(self) -> OrderResult | None:
        if self._broker.has_open_position(self._symbol):
            self._logger.info("position already open; skipping placement")
            return None

        period_secs = self._poll_minutes * 60
        now_epoch = self._clock.utcnow().timestamp()
        # epoch-modulo mirrors seconds_until_next_boundary to avoid off-by-one on boundary-exact times
        boundary_epoch = now_epoch - (now_epoch % period_secs)
        expected_decision_ts = datetime.fromtimestamp(
            boundary_epoch - period_secs, tz=timezone.utc)

        for attempt in range(self._freshness_max_retries + 1):
            candles = self._broker.recent_candles(
                self._symbol, self._strategy.required_candles)
            if candles[-1].timestamp == expected_decision_ts:
                break
            if attempt < self._freshness_max_retries:
                self._clock.sleep(self._freshness_retry_seconds)
        else:
            self._logger.warning(
                "stale candle for %s after %d retries at boundary %s; "
                "expected %s, got %s; skipping",
                self._symbol, self._freshness_max_retries, expected_decision_ts,
                expected_decision_ts, candles[-1].timestamp)
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
