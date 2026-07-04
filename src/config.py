from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence

_DEMO_BASE_URL = "https://demo-api-capital.backend-capital.com/api/v1"
_LIVE_BASE_URL = "https://api-capital.backend-capital.com/api/v1"  # UNVERIFIED

WARMUP_BARS = 128

_WS_PING_MAX_SECONDS = 600


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
class SymbolConfig:
    symbol: str
    epic: str
    size: float


@dataclass(frozen=True)
class ApiConfig:
    database_url: str
    symbols: tuple[SymbolConfig, ...]
    provider: str = "capital"


@dataclass(frozen=True)
class Config:
    mode: str
    base_url: str
    api_key: str
    identifier: str
    password: str
    symbols: tuple[SymbolConfig, ...]
    timeframe: str
    warmup_bars: int
    candle_settle_seconds: int
    poll_minutes: int
    reconciler_interval_seconds: int
    session_refresh_ttl_seconds: float
    database_url: str
    ws_ping_interval_seconds: int
    required_candles: int
    backfill_max_candles: int
    auth_max_retries: int
    provider: str = "capital"
    polygon_api_key: str = ""
    polygon_base_url: str = "https://api.massive.com"

    @property
    def epics(self) -> dict[str, str]:
        return {s.symbol: s.epic for s in self.symbols}


def _parse_symbols(env: dict[str, str]) -> list[SymbolConfig]:
    raw = env.get("SYMBOLS", "").strip()
    if not raw:
        raise ValueError("SYMBOLS environment variable is required and must not be empty")

    names = [s.strip() for s in raw.split(",") if s.strip()]
    if not names:
        raise ValueError("SYMBOLS environment variable is required and must not be empty")

    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise ValueError(f"Duplicate symbol in SYMBOLS: {name}")
        seen.add(name)

    global_size = float(env.get("SIZE", "1000"))

    result: list[SymbolConfig] = []
    for name in names:
        epic = env.get(f"EPIC_{name}", "").strip()
        if not epic:
            raise ValueError(
                f"Missing or blank EPIC_{name}: every listed symbol requires an explicit epic"
            )
        size = float(env.get(f"SIZE_{name}", str(global_size)))
        result.append(SymbolConfig(symbol=name, epic=epic, size=size))

    return result


def load_config() -> Config:
    env = dict(os.environ)

    mode = env.get("MODE", "demo").lower()
    base_url = _resolve_base_url(mode)

    api_key = env.get("CAPITAL_API_KEY", "")
    identifier = env.get("IDENTIFIER", "")
    password = env.get("PASSWORD", "")
    database_url = env.get("DATABASE_URL", "")
    timeframe = env.get("TIMEFRAME", "MINUTE_15")
    warmup_bars = int(env.get("WARMUP", str(WARMUP_BARS)))
    candle_settle_seconds = int(env.get("CANDLE_SETTLE_SECONDS", "5"))
    poll_minutes = int(env.get("POLL_MINUTES", "15"))
    reconciler_interval_seconds = int(env.get("RECONCILER_INTERVAL_SECONDS", "300"))
    session_refresh_ttl_seconds = float(env.get("SESSION_REFRESH_TTL_SECONDS", "300"))
    ws_ping_interval_seconds = int(env.get("WS_PING_INTERVAL_SECONDS", "45"))
    backfill_max_candles = int(env.get("BACKFILL_MAX_CANDLES", "500"))
    auth_max_retries = int(env.get("AUTH_MAX_RETRIES", "5"))
    provider = env.get("PROVIDER", "capital").strip().lower()
    if not provider:
        raise ValueError("PROVIDER must not be empty when set")
    polygon_api_key = env.get("POLYGON_API_KEY", "")
    polygon_base_url = env.get("POLYGON_BASE_URL", "https://api.massive.com")

    if ws_ping_interval_seconds >= _WS_PING_MAX_SECONDS:
        raise ValueError(
            f"WS_PING_INTERVAL_SECONDS must be < {_WS_PING_MAX_SECONDS}, "
            f"got {ws_ping_interval_seconds}"
        )

    missing_shared = [name for name, val in [
        ("CAPITAL_API_KEY", api_key),
        ("IDENTIFIER", identifier),
        ("PASSWORD", password),
        ("DATABASE_URL", database_url),
    ] if not val]
    if missing_shared:
        raise SystemExit(
            f"Missing required environment variables: {', '.join(missing_shared)}"
        )

    symbols = tuple(_parse_symbols(env))

    return Config(
        mode=mode,
        base_url=base_url,
        api_key=api_key,
        identifier=identifier,
        password=password,
        symbols=symbols,
        timeframe=timeframe,
        warmup_bars=warmup_bars,
        candle_settle_seconds=candle_settle_seconds,
        poll_minutes=poll_minutes,
        reconciler_interval_seconds=reconciler_interval_seconds,
        session_refresh_ttl_seconds=session_refresh_ttl_seconds,
        database_url=database_url,
        ws_ping_interval_seconds=ws_ping_interval_seconds,
        required_candles=warmup_bars,
        backfill_max_candles=backfill_max_candles,
        auth_max_retries=auth_max_retries,
        provider=provider,
        polygon_api_key=polygon_api_key,
        polygon_base_url=polygon_base_url,
    )


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


def load_api_config() -> ApiConfig:
    env = dict(os.environ)

    database_url = env.get("DATABASE_URL", "")
    if not database_url:
        raise SystemExit("Missing required environment variables: DATABASE_URL")

    provider = env.get("PROVIDER", "capital").strip().lower()
    if not provider:
        raise ValueError("PROVIDER must not be empty when set")

    return ApiConfig(
        database_url=database_url,
        symbols=tuple(_parse_symbols(env)),
        provider=provider,
    )
