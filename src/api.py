from __future__ import annotations

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

_RESOLUTION_MAP = {
    "1m": "MINUTE",
    "5m": "MINUTE_5",
    "15m": "MINUTE_15",
    "30m": "MINUTE_30",
    "1h": "HOUR",
    "4h": "HOUR_4",
    "1d": "DAY",
    "1w": "WEEK",
}


def run(host: str, port: int, cors_origins: list[str]) -> None:
    import contextlib

    import uvicorn
    from fastapi import FastAPI

    from config import load_api_config
    from infrastructure.http.candle_api import create_app
    from infrastructure.postgres.candle_store import PostgresCandleStore
    from infrastructure.postgres.connection import connect
    from infrastructure.postgres.migration_runner import run_migrations

    config = load_api_config()
    conn = connect(config.database_url)
    run_migrations(conn)

    store = PostgresCandleStore(conn)
    symbol_to_epic = {s.symbol: s.epic for s in config.symbols}

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        conn.close()

    app = create_app(
        store,
        symbol_to_epic=symbol_to_epic,
        resolution_map=_RESOLUTION_MAP,
        allow_origins=cors_origins,
        lifespan=lifespan,
    )

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import os

    from dotenv import load_dotenv

    load_dotenv()

    _host = os.environ.get("API_HOST", "0.0.0.0")
    _port = int(os.environ.get("API_PORT", "8001"))
    _raw_origins = os.environ.get("CORS_ALLOW_ORIGINS", "http://localhost:5173")
    _cors_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

    run(host=_host, port=_port, cors_origins=_cors_origins)
