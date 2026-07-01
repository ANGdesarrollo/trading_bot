from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain.entities.journal import ClosedTrade, JournalEntry, JournalResult

_NOW = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)


def _make_entry(**kwargs) -> JournalEntry:
    defaults = dict(
        deal_id="D1",
        symbol="EURUSD",
        direction="BUY",
        opened_at=_NOW,
        decision_candle_ts=_NOW,
        filled_price=1.10,
        sl_distance=0.0020,
        tp_distance=0.0020,
        atr_at_entry=0.0010,
        position_size=10000.0,
        bid_at_decision=None,
        ask_at_decision=None,
    )
    defaults.update(kwargs)
    return JournalEntry(**defaults)


def test_atr_at_entry_stored_as_supplied():
    entry = _make_entry(sl_distance=0.0020, atr_at_entry=0.0010)
    assert entry.atr_at_entry == pytest.approx(0.0010)


def test_atr_at_entry_different_value_stored():
    entry = _make_entry(sl_distance=0.0040, atr_at_entry=0.0020)
    assert entry.atr_at_entry == pytest.approx(0.0020)


def test_journal_entry_is_immutable():
    entry = _make_entry()
    with pytest.raises((AttributeError, TypeError)):
        entry.deal_id = "X"


def test_journal_entry_has_provider_field_defaulting_to_capital():
    entry = _make_entry()
    assert entry.provider == "capital"


def test_journal_entry_provider_override():
    entry = _make_entry(provider="ic_markets")
    assert entry.provider == "ic_markets"


def test_journal_entry_provider_is_immutable():
    entry = _make_entry()
    with pytest.raises((AttributeError, TypeError)):
        entry.provider = "ic_markets"  # type: ignore[misc]


def test_journal_result_close_source_values():
    for src in ("SL", "TP", "USER", "CLOSE_OUT"):
        r = JournalResult(
            deal_id="D1",
            closed_at=_NOW,
            close_price=1.10,
            close_source=src,
            realized_pnl=10.0,
            fees=0.5,
            realized_r=0.95,
            reconciled_at=_NOW,
        )
        assert r.close_source == src


def test_journal_result_is_immutable():
    r = JournalResult(
        deal_id="D1",
        closed_at=_NOW,
        close_price=1.10,
        close_source="SL",
        realized_pnl=10.0,
        fees=0.5,
        realized_r=0.95,
        reconciled_at=_NOW,
    )
    with pytest.raises((AttributeError, TypeError)):
        r.deal_id = "X"


def test_closed_trade_holds_pnl_and_fees():
    ct = ClosedTrade(
        deal_id="D1",
        closed_at=_NOW,
        close_price=1.10,
        close_source="SL",
        realized_pnl=-20.0,
        fees=1.0,
    )
    assert ct.realized_pnl == pytest.approx(-20.0)
    assert ct.fees == pytest.approx(1.0)
