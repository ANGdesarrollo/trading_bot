from __future__ import annotations

import pytest

from domain.ports.trade_journal_port import TradeJournalPort
from domain.ports.trade_history_port import TradeHistoryPort
from domain.ports.candle_store_port import CandleStorePort
from domain.ports.candle_history_port import CandleHistoryPort


def test_trade_journal_port_cannot_be_instantiated():
    with pytest.raises(TypeError):
        TradeJournalPort()


def test_trade_history_port_cannot_be_instantiated():
    with pytest.raises(TypeError):
        TradeHistoryPort()


def test_trade_journal_port_declares_three_methods():
    assert hasattr(TradeJournalPort, "record_entry")
    assert hasattr(TradeJournalPort, "record_result")
    assert hasattr(TradeJournalPort, "open_entries")


def test_trade_history_port_declares_closed_trade():
    assert hasattr(TradeHistoryPort, "closed_trade")


def test_candle_store_port_cannot_be_instantiated():
    with pytest.raises(TypeError):
        CandleStorePort()  # type: ignore[abstract]


def test_candle_store_port_declares_three_methods():
    assert hasattr(CandleStorePort, "recent_candles")
    assert hasattr(CandleStorePort, "last_candle_start")
    assert hasattr(CandleStorePort, "upsert_candle")


def test_candle_history_port_cannot_be_instantiated():
    with pytest.raises(TypeError):
        CandleHistoryPort()  # type: ignore[abstract]


def test_candle_history_port_declares_fetch_history():
    assert hasattr(CandleHistoryPort, "fetch_history")
