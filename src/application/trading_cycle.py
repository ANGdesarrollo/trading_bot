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

_CANDLE_WAIT_MAX_ATTEMPTS = 10
_CANDLE_WAIT_INTERVAL_S = 1.0


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
        provider: str = "capital",
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
        self._provider = provider

    def execute(self) -> OrderResult | None:
        self._logger.info(
            "[%s] running cycle: looking for the last closed %s candle",
            self._symbol, self._resolution,
        )

        if self._broker.has_open_position(self._symbol):
            self._logger.info("[%s] position already open; nothing to do", self._symbol)
            return None

        expected_decision_ts = self._expected_boundary()
        candles = self._await_candles(expected_decision_ts)
        if candles is None:
            return None

        signal = self._strategy.evaluate(candles)
        if signal is None:
            self._logger.info(
                "[%s] strategy evaluated on candle %s: no signal; nothing to do",
                self._symbol, expected_decision_ts,
            )
            return None

        self._logger.info(
            "[%s] signal %s on candle %s; placing order",
            self._symbol, signal.direction.name, expected_decision_ts,
        )
        result = self._broker.open_position(self._symbol, signal, self._size)
        self._logger.info(
            "[%s] order placed at %s",
            self._symbol, result.filled_price,
        )
        try:
            entry = self._build_entry(signal, result, expected_decision_ts)
            self._journal.record_entry(entry)
        except Exception:
            self._logger.exception("journal record_entry failed; continuing")
        return result

    def _await_candles(self, expected_decision_ts: datetime):
        """Poll the store until the just-closed candle is persisted.

        The WS ingester writes the boundary candle a moment after it closes,
        so the store can briefly lag the decision boundary. Retry rather than
        skip the cycle, or we would rarely trade at all.
        """
        for attempt in range(_CANDLE_WAIT_MAX_ATTEMPTS):
            candles = self._candle_store.recent_candles(
                provider=self._provider, symbol=self._symbol,
                resolution=self._resolution, count=self._strategy.required_candles)

            if (len(candles) >= self._strategy.required_candles
                    and candles[-1].timestamp == expected_decision_ts):
                return candles

            self._logger.info(
                "[%s] candle %s not in store yet (attempt %d/%d); waiting %.0fs",
                self._symbol, expected_decision_ts, attempt + 1,
                _CANDLE_WAIT_MAX_ATTEMPTS, _CANDLE_WAIT_INTERVAL_S,
            )
            self._clock.sleep(_CANDLE_WAIT_INTERVAL_S)

        self._logger.warning(
            "[%s] candle %s never arrived after %d attempts; skipping",
            self._symbol, expected_decision_ts, _CANDLE_WAIT_MAX_ATTEMPTS,
        )
        return None

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
            provider=self._provider,
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
