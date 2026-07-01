from __future__ import annotations

import inspect

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


def test_recent_candles_has_provider_as_first_param_with_default():
    from domain.ports.candle_store_port import CandleStorePort
    sig = inspect.signature(CandleStorePort.recent_candles)
    params = list(sig.parameters)
    assert params[1] == "provider", f"expected 'provider' first, got {params[1:]}"
    assert sig.parameters["provider"].default == "capital"


def test_last_candle_start_has_provider_as_first_param_with_default():
    from domain.ports.candle_store_port import CandleStorePort
    sig = inspect.signature(CandleStorePort.last_candle_start)
    params = list(sig.parameters)
    assert params[1] == "provider", f"expected 'provider' first, got {params[1:]}"
    assert sig.parameters["provider"].default == "capital"


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
