from __future__ import annotations

import os
from dataclasses import dataclass

_ETORO_DEMO_BASE_URL = "https://public-api.etoro.com"
_ETORO_REAL_BASE_URL = "https://public-api.etoro.com"

# Domain symbols come from the validated research basket; eToro tickers are the
# cheapest same-index instruments available there (fee research, 2026-07):
# VOO 0.03% TER over SPY 0.09%, IEMG 0.09% over EEM 0.68%, IEFA 0.07% over
# EFA 0.32%, GLDM 0.10% over GLD 0.40%. QQQM/VTWO are not listed on eToro.
_ETORO_DEFAULT_SYMBOL_MAP = {
    "SPY": "VOO",
    "QQQ": "QQQ",
    "IWM": "IWM",
    "EEM": "IEMG",
    "EFA": "IEFA",
    "TLT": "TLT",
    "XAUUSD": "GLDM",
    "BTCUSD": "BTC",
}


@dataclass(frozen=True)
class EToroConfig:
    mode: str
    api_key: str
    user_key: str
    min_order_usd: float
    symbol_to_etoro_ticker: dict[str, str]


def load_etoro_config(env: dict[str, str] | None = None, min_order_usd: float = 10.0) -> EToroConfig:
    if env is None:
        env = dict(os.environ)

    mode = env.get("ETORO_MODE", "demo").lower()
    api_key = env.get("ETORO_API_KEY", "")
    user_key = env.get("ETORO_USER_KEY", "")

    missing = [name for name, val in [("ETORO_API_KEY", api_key), ("ETORO_USER_KEY", user_key)] if not val]
    if missing:
        raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")

    if mode == "real":
        ack = env.get("I_UNDERSTAND_THIS_IS_REAL_MONEY", "")
        if ack != "YES":
            raise SystemExit(
                "Refusing real-money eToro rebalance: set I_UNDERSTAND_THIS_IS_REAL_MONEY=YES "
                "to confirm you understand this uses real money."
            )

    symbol_map = dict(_ETORO_DEFAULT_SYMBOL_MAP)
    for domain_sym in list(symbol_map):
        override = env.get(f"ETORO_TICKER_{domain_sym}", "").strip()
        if override:
            symbol_map[domain_sym] = override

    return EToroConfig(
        mode=mode,
        api_key=api_key,
        user_key=user_key,
        min_order_usd=min_order_usd,
        symbol_to_etoro_ticker=symbol_map,
    )
