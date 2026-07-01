"""Tests for config.py MODE guard (T-19, REQ-13, REQ-14).

Scenarios:
  7.1 — demo mode starts without confirmation env var
  7.2 — live mode without confirmation raises SystemExit
  7.3 — live mode with I_UNDERSTAND_THIS_IS_REAL_MONEY=YES proceeds
"""

import os

import pytest


def _load_config(env: dict[str, str]):
    """Load Config with a patched environment."""
    import importlib
    import sys

    original = {k: os.environ.get(k) for k in env}
    for k, v in env.items():
        os.environ[k] = v

    if "config" in sys.modules:
        del sys.modules["config"]

    try:
        from config import Config, load_config
        return load_config()
    finally:
        for k, original_v in original.items():
            if original_v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original_v
        if "config" in sys.modules:
            del sys.modules["config"]


def test_demo_mode_loads_without_confirmation():
    env = {
        "MODE": "demo",
        "CAPITAL_API_KEY": "key123",
        "IDENTIFIER": "user@example.com",
        "PASSWORD": "pass",
        "EPIC": "CS.D.EURUSD.MINI.IP",
        "DATABASE_URL": "postgresql://op:op@localhost/trade_journal",
    }
    os.environ.pop("I_UNDERSTAND_THIS_IS_REAL_MONEY", None)
    config = _load_config(env)
    assert config.mode == "demo"


def test_live_mode_without_confirmation_raises_system_exit():
    env = {
        "MODE": "live",
        "CAPITAL_API_KEY": "key123",
        "IDENTIFIER": "user@example.com",
        "PASSWORD": "pass",
        "EPIC": "CS.D.EURUSD.MINI.IP",
        "DATABASE_URL": "postgresql://op:op@localhost/trade_journal",
    }
    os.environ.pop("I_UNDERSTAND_THIS_IS_REAL_MONEY", None)

    with pytest.raises(SystemExit):
        _load_config(env)


def test_default_trade_size_is_1000():
    env = {
        "CAPITAL_API_KEY": "key123",
        "IDENTIFIER": "user@example.com",
        "PASSWORD": "pass",
        "EPIC": "CS.D.EURUSD.MINI.IP",
        "DATABASE_URL": "postgresql://op:op@localhost/trade_journal",
    }
    config = _load_config(env)
    assert config.trade_size == 1000


def test_live_mode_with_confirmation_proceeds():
    env = {
        "MODE": "live",
        "I_UNDERSTAND_THIS_IS_REAL_MONEY": "YES",
        "CAPITAL_API_KEY": "key123",
        "IDENTIFIER": "user@example.com",
        "PASSWORD": "pass",
        "EPIC": "CS.D.EURUSD.MINI.IP",
        "DATABASE_URL": "postgresql://op:op@localhost/trade_journal",
    }
    config = _load_config(env)
    assert config.mode == "live"


_REQUIRED_ENV = {
    "CAPITAL_API_KEY": "key123",
    "IDENTIFIER": "user@example.com",
    "PASSWORD": "pass",
    "EPIC": "CS.D.EURUSD.MINI.IP",
    "DATABASE_URL": "postgresql://op:op@localhost/trade_journal",
}


def test_default_warmup_bars_is_128():
    config = _load_config(_REQUIRED_ENV)
    assert config.warmup_bars == 128


def test_warmup_bars_128_loads_successfully():
    config = _load_config({**_REQUIRED_ENV, "WARMUP": "128"})
    assert config.warmup_bars == 128


def test_legacy_api_key_only_raises_system_exit():
    env = {
        "API_KEY": "key123",
        "CAPITAL_API_KEY": "",
        "IDENTIFIER": "user@example.com",
        "PASSWORD": "pass",
        "EPIC": "CS.D.EURUSD.MINI.IP",
        "DATABASE_URL": "postgresql://op:op@localhost/trade_journal",
    }
    with pytest.raises(SystemExit):
        _load_config(env)


def test_freshness_fields_default_values():
    config = _load_config(_REQUIRED_ENV)
    assert config.freshness_max_retries == 3
    assert config.freshness_retry_seconds == 2.0


def test_freshness_fields_env_override():
    config = _load_config({
        **_REQUIRED_ENV,
        "FRESHNESS_MAX_RETRIES": "5",
        "FRESHNESS_RETRY_SECONDS": "1.5",
    })
    assert config.freshness_max_retries == 5
    assert config.freshness_retry_seconds == 1.5


def test_database_url_missing_raises_system_exit(monkeypatch):
    env_without_db = {k: v for k, v in _REQUIRED_ENV.items() if k != "DATABASE_URL"}
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="DATABASE_URL"):
        _load_config(env_without_db)


def test_database_url_present_populates_config():
    cfg = _load_config(_REQUIRED_ENV)
    assert cfg.database_url == "postgresql://op:op@localhost/trade_journal"
