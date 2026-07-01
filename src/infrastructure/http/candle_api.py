from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from starlette.middleware.cors import CORSMiddleware

from domain.entities.candle import Candle
from domain.ports.candle_store_port import CandleStorePort

_DEFAULT_ORIGINS = ["http://localhost:5173"]


def candle_to_dict(candle: Candle) -> dict:
    return {
        "time": candle.timestamp.isoformat(),
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        # Candle entity carries no volume; frontend requires the field — 0 is honest.
        "volume": 0,
    }


def create_app(
    store: CandleStorePort,
    *,
    symbol_to_epic: dict[str, str],
    resolution_map: dict[str, str],
    allow_origins: list[str] | None = None,
    lifespan=None,
) -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins if allow_origins is not None else _DEFAULT_ORIGINS,
        allow_methods=["GET"],
        allow_headers=["Content-Type"],
    )

    @app.get("/api/scan/datasets")
    def get_datasets():
        symbols = sorted(symbol_to_epic)
        datasets = [
            {"symbol": symbol, "timeframe": timeframe}
            for symbol in symbols
            for timeframe in resolution_map
        ]
        return {"datasets": datasets, "symbols": symbols}

    @app.get("/api/scan/candles")
    def get_candles(
        symbol: str,
        timeframe: str,
        provider: str = "capital",
        limit: Annotated[int, Query(gt=0)] = 500,
    ):
        epic = symbol_to_epic.get(symbol)
        if epic is None:
            raise HTTPException(status_code=404, detail=f"Unknown symbol: {symbol}")

        resolution = resolution_map.get(timeframe)
        if resolution is None:
            raise HTTPException(status_code=400, detail=f"Unknown timeframe: {timeframe}")

        candles = store.recent_candles(
            provider=provider, symbol=epic, resolution=resolution, count=limit
        )
        bars = [candle_to_dict(c) for c in candles]
        return {
            "meta": {"symbol": symbol, "timeframe": timeframe, "bars": len(bars)},
            "candles": bars,
        }

    return app
