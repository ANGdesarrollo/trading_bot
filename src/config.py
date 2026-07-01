"""Trading engine configuration.

Single source of truth for all runtime parameters. Frozen strategy constants
(L_FROZEN, ATR_PERIOD, etc.) live ONLY in research.lib.fade_strategy and are
imported by the domain adapter — never duplicated here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

_DEMO_BASE_URL = "https://demo-api-capital.backend-capital.com/api/v1"
_LIVE_BASE_URL = "https://api-capital.backend-capital.com/api/v1"  # UNVERIFIED

WARMUP_BARS = 128


def _resolve_base_url(mode: str) -> str:
    if mode == "live":
        ack = os.environ.get("I_UNDERSTAND_THIS_IS_REAL_MONEY", "")
        if ack != "YES":
            raise SystemExit(
                "Refusing live trading: set I_UNDERSTAND_THIS_IS_REAL_MONEY=YES "
                "to confirm you understand this uses real money."
            )
        return _LIVE_BASE_URL
    return _DEMO_BASE_URL


@dataclass(frozen=True)
class Config:
    mode: str
    base_url: str
    api_key: str
    identifier: str
    password: str
    symbol: str
    epics: dict[str, str]
    timeframe: str
    trade_size: float
    warmup_bars: int
    candle_settle_seconds: int
    poll_minutes: int
    freshness_max_retries: int
    freshness_retry_seconds: float
    database_url: str


def load_config() -> Config:
    mode = os.environ.get("MODE", "demo").lower()
    base_url = _resolve_base_url(mode)

    api_key = os.environ.get("CAPITAL_API_KEY", "")
    identifier = os.environ.get("IDENTIFIER", "")
    password = os.environ.get("PASSWORD", "")
    symbol = os.environ.get("SYMBOL", "EURUSD")
    epic = os.environ.get("EPIC", "")
    timeframe = os.environ.get("TIMEFRAME", "MINUTE_15")
    trade_size = float(os.environ.get("SIZE", "1000"))
    warmup_bars = int(os.environ.get("WARMUP", str(WARMUP_BARS)))
    candle_settle_seconds = int(os.environ.get("CANDLE_SETTLE_SECONDS", "5"))
    poll_minutes = int(os.environ.get("POLL_MINUTES", "15"))
    freshness_max_retries = int(os.environ.get("FRESHNESS_MAX_RETRIES", "3"))
    freshness_retry_seconds = float(os.environ.get("FRESHNESS_RETRY_SECONDS", "2.0"))

    database_url = os.environ.get("DATABASE_URL", "")

    missing = [name for name, val in [
        ("CAPITAL_API_KEY", api_key), ("IDENTIFIER", identifier),
        ("PASSWORD", password), ("EPIC", epic),
        ("DATABASE_URL", database_url),
    ] if not val]
    if missing:
        raise SystemExit(
            f"Missing required environment variables: {', '.join(missing)}"
        )

    return Config(
        mode=mode,
        base_url=base_url,
        api_key=api_key,
        identifier=identifier,
        password=password,
        symbol=symbol,
        epics={symbol: epic},
        timeframe=timeframe,
        trade_size=trade_size,
        warmup_bars=warmup_bars,
        candle_settle_seconds=candle_settle_seconds,
        poll_minutes=poll_minutes,
        freshness_max_retries=freshness_max_retries,
        freshness_retry_seconds=freshness_retry_seconds,
        database_url=database_url,
    )
