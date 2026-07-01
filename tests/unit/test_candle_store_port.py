from __future__ import annotations

import pytest


def test_candle_store_port_cannot_be_instantiated():
    from domain.ports.candle_store_port import CandleStorePort
    with pytest.raises(TypeError):
        CandleStorePort()  # type: ignore[abstract]


def test_candle_store_port_declares_three_abstract_methods():
    from domain.ports.candle_store_port import CandleStorePort
    assert hasattr(CandleStorePort, "recent_candles")
    assert hasattr(CandleStorePort, "last_candle_start")
    assert hasattr(CandleStorePort, "upsert_candle")


def test_candle_store_port_has_no_infra_imports():
    import importlib, sys
    if "domain.ports.candle_store_port" in sys.modules:
        del sys.modules["domain.ports.candle_store_port"]
    mod = importlib.import_module("domain.ports.candle_store_port")
    src = mod.__file__
    assert src is not None
    text = open(src).read()
    assert "psycopg" not in text
    assert "infrastructure" not in text
