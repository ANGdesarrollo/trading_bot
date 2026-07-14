import pytest

from config import load_etoro_config

_DEMO_ENV = {
    "ETORO_API_KEY": "demo-api",
    "ETORO_USER_KEY": "demo-user",
}

_REAL_ENV = {
    "ETORO_MODE": "real",
    "ETORO_LIVE_API_KEY": "live-api",
    "ETORO_LIVE_USER_KEY": "live-user",
    "I_UNDERSTAND_THIS_IS_REAL_MONEY": "YES",
}


class TestEToroKeySelection:
    def test_demo_mode_uses_demo_keys(self):
        cfg = load_etoro_config(env=_DEMO_ENV)

        assert cfg.mode == "demo"
        assert cfg.api_key == "demo-api"
        assert cfg.user_key == "demo-user"

    def test_real_mode_uses_live_keys(self):
        cfg = load_etoro_config(env=_REAL_ENV)

        assert cfg.mode == "real"
        assert cfg.api_key == "live-api"
        assert cfg.user_key == "live-user"

    def test_real_mode_ignores_demo_keys(self):
        env = {**_REAL_ENV, **_DEMO_ENV, "ETORO_MODE": "real"}

        cfg = load_etoro_config(env=env)

        assert cfg.api_key == "live-api"
        assert cfg.user_key == "live-user"

    def test_real_mode_without_live_keys_fails(self):
        env = {**_DEMO_ENV, "ETORO_MODE": "real"}

        with pytest.raises(SystemExit, match="ETORO_LIVE_API_KEY, ETORO_LIVE_USER_KEY"):
            load_etoro_config(env=env)

    def test_real_mode_requires_real_money_acknowledgement(self):
        env = {k: v for k, v in _REAL_ENV.items() if k != "I_UNDERSTAND_THIS_IS_REAL_MONEY"}

        with pytest.raises(SystemExit, match="I_UNDERSTAND_THIS_IS_REAL_MONEY"):
            load_etoro_config(env=env)
