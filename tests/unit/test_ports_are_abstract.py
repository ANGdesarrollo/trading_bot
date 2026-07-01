from __future__ import annotations

import pytest

from domain.ports.trade_journal_port import TradeJournalPort
from domain.ports.trade_history_port import TradeHistoryPort


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
