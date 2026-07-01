from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from application.reconcile_closed_trades import ReconcileClosedTradesUseCase
from domain.entities.journal import ClosedTrade, JournalEntry
from tests.fakes.fake_history import FakeTradeHistoryPort
from tests.fakes.fake_journal import FakeJournalPort

_NOW = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)


def _make_entry(deal_id: str = "D1", filled_price: float = 1.10,
                sl_distance: float = 0.0020, position_size: float = 10000.0,
                direction: str = "BUY") -> JournalEntry:
    return JournalEntry(
        deal_id=deal_id,
        symbol="EURUSD",
        direction=direction,
        opened_at=_NOW,
        decision_candle_ts=_NOW,
        filled_price=filled_price,
        sl_distance=sl_distance,
        tp_distance=sl_distance,
        atr_at_entry=sl_distance / 2.0,
        position_size=position_size,
        bid_at_decision=None,
        ask_at_decision=None,
    )


def _make_closed(deal_id: str = "D1", realized_pnl: float = 19.0,
                 fees: float = 1.0, close_source: str = "TP") -> ClosedTrade:
    return ClosedTrade(
        deal_id=deal_id,
        closed_at=_NOW,
        close_price=1.1019,
        close_source=close_source,
        realized_pnl=realized_pnl,
        fees=fees,
    )


def test_open_entry_gets_reconciled_when_closed():
    journal = FakeJournalPort(open_=[_make_entry("D1", sl_distance=0.0020, position_size=10000.0)])
    history = FakeTradeHistoryPort({"D1": _make_closed("D1", realized_pnl=19.0, fees=1.0)})
    uc = ReconcileClosedTradesUseCase(journal, history)
    uc.execute()
    assert len(journal.result_calls) == 1
    r = journal.result_calls[0]
    assert r.deal_id == "D1"
    assert r.realized_r == pytest.approx((19.0 - 1.0) / (0.0020 * 10000.0))


def test_still_open_position_skipped():
    journal = FakeJournalPort(open_=[_make_entry("D1")])
    history = FakeTradeHistoryPort({"D1": None})
    uc = ReconcileClosedTradesUseCase(journal, history)
    uc.execute()
    assert journal.result_calls == []


def test_lookup_failure_does_not_abort_remaining():
    journal = FakeJournalPort(open_=[_make_entry("D1"), _make_entry("D2")])
    history = FakeTradeHistoryPort({
        "D1": RuntimeError("API down"),
        "D2": _make_closed("D2", realized_pnl=20.0, fees=1.0),
    })
    uc = ReconcileClosedTradesUseCase(journal, history)
    uc.execute()
    assert len(journal.result_calls) == 1
    assert journal.result_calls[0].deal_id == "D2"


def test_realized_r_losing_trade():
    journal = FakeJournalPort(open_=[_make_entry("D1", sl_distance=0.0020, position_size=10000.0)])
    history = FakeTradeHistoryPort({"D1": _make_closed("D1", realized_pnl=-20.0, fees=1.0)})
    uc = ReconcileClosedTradesUseCase(journal, history)
    uc.execute()
    r = journal.result_calls[0]
    assert r.realized_r == pytest.approx((-20.0 - 1.0) / (0.0020 * 10000.0))


def test_already_reconciled_entry_not_returned_by_open_entries():
    journal = FakeJournalPort(open_=[])
    history = FakeTradeHistoryPort({"D1": _make_closed("D1")})
    uc = ReconcileClosedTradesUseCase(journal, history)
    uc.execute()
    assert journal.result_calls == []
