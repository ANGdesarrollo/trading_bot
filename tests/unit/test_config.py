"""Tests for config.py — MODE guard and multi-symbol configuration."""

import dataclasses
import os

import pytest


def _load_config(env: dict[str, str]):
    """Load Config with a patched environment (isolated from real env)."""
    import importlib
    import sys

    # Capture current values for keys we are about to set, plus any keys in
    # the current environment that are NOT in env (so we can clear them).
    all_relevant = set(env) | {
        k for k in os.environ
        if k.startswith(("EPIC_", "SIZE_", "SYMBOLS"))
        or k in (
            "MODE", "CAPITAL_API_KEY", "IDENTIFIER", "PASSWORD", "DATABASE_URL",
            "TIMEFRAME", "WARMUP", "CANDLE_SETTLE_SECONDS", "POLL_MINUTES",
            "RECONCILER_INTERVAL_SECONDS", "SESSION_REFRESH_TTL_SECONDS",
            "WS_PING_INTERVAL_SECONDS", "BACKFILL_MAX_CANDLES",
            "I_UNDERSTAND_THIS_IS_REAL_MONEY",
        )
    }
    original = {k: os.environ.get(k) for k in all_relevant}

    # Wipe all relevant keys, then set only what the test provides.
    for k in all_relevant:
        os.environ.pop(k, None)
    for k, v in env.items():
        os.environ[k] = v

    if "config" in sys.modules:
        del sys.modules["config"]

    try:
        from config import load_config
        return load_config()
    finally:
        for k in all_relevant:
            original_v = original[k]
            if original_v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original_v
        if "config" in sys.modules:
            del sys.modules["config"]


_REQUIRED_ENV = {
    "CAPITAL_API_KEY": "key123",
    "IDENTIFIER": "user@example.com",
    "PASSWORD": "pass",
    "SYMBOLS": "EURUSD",
    "EPIC_EURUSD": "CS.D.EURUSD.MINI.IP",
    "DATABASE_URL": "postgresql://op:op@localhost/trade_journal",
}


def test_demo_mode_loads_without_confirmation():
    env = {**_REQUIRED_ENV, "MODE": "demo"}
    os.environ.pop("I_UNDERSTAND_THIS_IS_REAL_MONEY", None)
    config = _load_config(env)
    assert config.mode == "demo"


def test_live_mode_without_confirmation_raises_system_exit():
    env = {**_REQUIRED_ENV, "MODE": "live"}
    os.environ.pop("I_UNDERSTAND_THIS_IS_REAL_MONEY", None)
    with pytest.raises(SystemExit):
        _load_config(env)


def test_default_trade_size_is_1000():
    cfg = _load_config(_REQUIRED_ENV)
    assert cfg.symbols[0].size == 1000.0


def test_live_mode_with_confirmation_proceeds():
    env = {**_REQUIRED_ENV, "MODE": "live", "I_UNDERSTAND_THIS_IS_REAL_MONEY": "YES"}
    config = _load_config(env)
    assert config.mode == "live"


def test_default_warmup_bars_is_128():
    config = _load_config(_REQUIRED_ENV)
    assert config.warmup_bars == 128


def test_warmup_bars_128_loads_successfully():
    config = _load_config({**_REQUIRED_ENV, "WARMUP": "128"})
    assert config.warmup_bars == 128


def test_legacy_api_key_only_raises_system_exit():
    env = {**_REQUIRED_ENV, "CAPITAL_API_KEY": ""}
    with pytest.raises(SystemExit):
        _load_config(env)



def test_reconciler_interval_defaults_to_300():
    config = _load_config(_REQUIRED_ENV)
    assert config.reconciler_interval_seconds == 300


def test_reconciler_interval_env_override():
    config = _load_config({**_REQUIRED_ENV, "RECONCILER_INTERVAL_SECONDS": "120"})
    assert config.reconciler_interval_seconds == 120


def test_session_refresh_ttl_defaults_to_540():
    config = _load_config(_REQUIRED_ENV)
    assert config.session_refresh_ttl_seconds == 540.0


def test_session_refresh_ttl_env_override():
    config = _load_config({**_REQUIRED_ENV, "SESSION_REFRESH_TTL_SECONDS": "480"})
    assert config.session_refresh_ttl_seconds == 480.0


def test_database_url_missing_raises_system_exit(monkeypatch):
    env_without_db = {k: v for k, v in _REQUIRED_ENV.items() if k != "DATABASE_URL"}
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="DATABASE_URL"):
        _load_config(env_without_db)


def test_database_url_present_populates_config():
    cfg = _load_config(_REQUIRED_ENV)
    assert cfg.database_url == "postgresql://op:op@localhost/trade_journal"


# ---------------------------------------------------------------------------
# Phase 1 — SymbolConfig value object
# ---------------------------------------------------------------------------

def test_symbol_config_is_a_frozen_dataclass():
    from config import SymbolConfig
    sc = SymbolConfig(symbol="EURUSD", epic="CS.D.EURUSD.MINI.IP", size=1000.0)
    assert sc.symbol == "EURUSD"
    assert sc.epic == "CS.D.EURUSD.MINI.IP"
    assert sc.size == 1000.0
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        sc.symbol = "USDJPY"  # type: ignore[misc]


_MULTI_ENV_TWO = {
    "CAPITAL_API_KEY": "key123",
    "IDENTIFIER": "user@example.com",
    "PASSWORD": "pass",
    "DATABASE_URL": "postgresql://op:op@localhost/trade_journal",
    "SYMBOLS": "EURUSD,USDJPY",
    "EPIC_EURUSD": "CS.D.EURUSD.MINI.IP",
    "EPIC_USDJPY": "CS.D.USDJPY.MINI.IP",
}


def test_config_holds_symbols_tuple_and_derived_epics():
    cfg = _load_config(_MULTI_ENV_TWO)
    assert len(cfg.symbols) == 2
    assert cfg.symbols[0].__class__.__name__ == "SymbolConfig"
    assert cfg.epics == {
        "EURUSD": "CS.D.EURUSD.MINI.IP",
        "USDJPY": "CS.D.USDJPY.MINI.IP",
    }


# ---------------------------------------------------------------------------
# Phase 2 — load_config multi-symbol parsing
# ---------------------------------------------------------------------------

_SIX_SYMBOLS_ENV = {
    "CAPITAL_API_KEY": "key123",
    "IDENTIFIER": "user@example.com",
    "PASSWORD": "pass",
    "DATABASE_URL": "postgresql://op:op@localhost/trade_journal",
    "SYMBOLS": "EURUSD,USDJPY,GBPUSD,AUDUSD,USDCAD,USDCHF",
    "EPIC_EURUSD": "CS.D.EURUSD.MINI.IP",
    "EPIC_USDJPY": "CS.D.USDJPY.MINI.IP",
    "EPIC_GBPUSD": "CS.D.GBPUSD.MINI.IP",
    "EPIC_AUDUSD": "CS.D.AUDUSD.MINI.IP",
    "EPIC_USDCAD": "CS.D.USDCAD.MINI.IP",
    "EPIC_USDCHF": "CS.D.USDCHF.MINI.IP",
}


def test_load_config_parses_six_symbols():
    cfg = _load_config(_SIX_SYMBOLS_ENV)
    assert len(cfg.symbols) == 6
    symbols = [s.symbol for s in cfg.symbols]
    assert symbols == ["EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF"]


def test_per_symbol_size_overrides_global():
    cfg = _load_config({**_MULTI_ENV_TWO, "SIZE": "1000", "SIZE_USDJPY": "2000"})
    sizes = {s.symbol: s.size for s in cfg.symbols}
    assert sizes["EURUSD"] == 1000.0
    assert sizes["USDJPY"] == 2000.0


def test_missing_epic_raises_value_error_naming_symbol():
    env = {**_MULTI_ENV_TWO}
    env.pop("EPIC_USDJPY")
    with pytest.raises(ValueError, match="USDJPY"):
        _load_config(env)


def test_blank_epic_raises_value_error():
    with pytest.raises(ValueError, match="EURUSD"):
        _load_config({**_MULTI_ENV_TWO, "EPIC_EURUSD": ""})


def test_empty_symbols_raises_value_error():
    env = {k: v for k, v in _MULTI_ENV_TWO.items() if k != "SYMBOLS"}
    env["SYMBOLS"] = ""
    with pytest.raises(ValueError, match="SYMBOLS"):
        _load_config(env)


def test_duplicate_symbol_raises_value_error():
    env = {
        **_MULTI_ENV_TWO,
        "SYMBOLS": "EURUSD,EURUSD",
    }
    with pytest.raises(ValueError, match="EURUSD"):
        _load_config(env)


# ---------------------------------------------------------------------------
# Slice 1 — ws-candle-ingestion config fields
# ---------------------------------------------------------------------------

def test_ws_ping_interval_seconds_defaults_to_540():
    cfg = _load_config(_REQUIRED_ENV)
    assert cfg.ws_ping_interval_seconds == 540


def test_ws_ping_interval_seconds_env_override():
    cfg = _load_config({**_REQUIRED_ENV, "WS_PING_INTERVAL_SECONDS": "300"})
    assert cfg.ws_ping_interval_seconds == 300


def test_ws_ping_interval_seconds_must_be_less_than_600():
    with pytest.raises((ValueError, SystemExit)):
        _load_config({**_REQUIRED_ENV, "WS_PING_INTERVAL_SECONDS": "600"})


def test_required_candles_equals_warmup_bars():
    cfg = _load_config({**_REQUIRED_ENV, "WARMUP": "64"})
    assert cfg.required_candles == 64


def test_required_candles_default_is_128():
    cfg = _load_config(_REQUIRED_ENV)
    assert cfg.required_candles == 128


def test_backfill_max_candles_defaults_to_500():
    cfg = _load_config(_REQUIRED_ENV)
    assert cfg.backfill_max_candles == 500


def test_backfill_max_candles_env_override():
    cfg = _load_config({**_REQUIRED_ENV, "BACKFILL_MAX_CANDLES": "1000"})
    assert cfg.backfill_max_candles == 1000


def test_freshness_fields_absent_from_config():
    cfg = _load_config(_REQUIRED_ENV)
    assert not hasattr(cfg, "freshness_max_retries")
    assert not hasattr(cfg, "freshness_retry_seconds")


# ---------------------------------------------------------------------------
# provider-aware-data-model — Config.provider
# ---------------------------------------------------------------------------

def test_config_provider_defaults_to_capital():
    cfg = _load_config(_REQUIRED_ENV)
    assert cfg.provider == "capital"


def test_config_provider_reads_from_env():
    cfg = _load_config({**_REQUIRED_ENV, "PROVIDER": "ic_markets"})
    assert cfg.provider == "ic_markets"


def test_config_provider_lowercased():
    cfg = _load_config({**_REQUIRED_ENV, "PROVIDER": "IC_MARKETS"})
    assert cfg.provider == "ic_markets"
