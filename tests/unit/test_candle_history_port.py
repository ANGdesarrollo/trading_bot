from __future__ import annotations

import pytest


def test_candle_history_port_cannot_be_instantiated():
    from domain.ports.candle_history_port import CandleHistoryPort
    with pytest.raises(TypeError):
        CandleHistoryPort()  # type: ignore[abstract]


def test_candle_history_port_declares_fetch_history():
    from domain.ports.candle_history_port import CandleHistoryPort
    assert hasattr(CandleHistoryPort, "fetch_history")


def test_fetch_history_signature_accepts_four_params():
    import inspect
    from domain.ports.candle_history_port import CandleHistoryPort
    sig = inspect.signature(CandleHistoryPort.fetch_history)
    params = list(sig.parameters)
    assert "epic" in params
    assert "resolution" in params
    assert "count" in params
    assert "since" in params
