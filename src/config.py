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
    session_refresh_ttl_seconds = float(env.get("SESSION_REFRESH_TTL_SECONDS", "540"))
    ws_ping_interval_seconds = int(env.get("WS_PING_INTERVAL_SECONDS", "540"))
    backfill_max_candles = int(env.get("BACKFILL_MAX_CANDLES", "500"))

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
    )
