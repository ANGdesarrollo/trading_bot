from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from application.fade_trades import _MIN_CANDLES_FOR_STRATEGY
from domain.entities.candle import Candle
from infrastructure.http.candle_api import candle_to_dict, create_app
from tests.fakes.fake_candle_store import FakeCandleStore

_UTC = timezone.utc


def _make_candles(n: int) -> list[Candle]:
    base = datetime(2024, 1, 1, 0, 0, 0, tzinfo=_UTC)
    return [
        Candle(base + timedelta(minutes=15 * i), open=1.08, high=1.09, low=1.07, close=1.085)
        for i in range(n)
    ]

_C1 = Candle(datetime(2024, 1, 1, 0, 0, 0, tzinfo=_UTC), open=1.08, high=1.09, low=1.07, close=1.085)
_C2 = Candle(datetime(2024, 1, 1, 0, 15, 0, tzinfo=_UTC), open=1.085, high=1.095, low=1.08, close=1.09)
_C3 = Candle(datetime(2024, 1, 1, 0, 30, 0, tzinfo=_UTC), open=1.09, high=1.10, low=1.085, close=1.095)

_SYMBOL_MAP = {"EURUSD": "CS.D.EURUSD.MINI.IP"}
_RESOLUTION_MAP = {"15m": "MINUTE_15", "1h": "HOUR", "1d": "DAY"}


def _make_app(*, candles=None):
    store = FakeCandleStore(candles=candles or [])
    return create_app(store, symbol_to_epic=_SYMBOL_MAP, resolution_map=_RESOLUTION_MAP), store


class TestCandleToDict:
    def test_time_is_isoformat(self):
        d = candle_to_dict(_C1)
        assert d["time"] == _C1.timestamp.isoformat()

    def test_ohlc_preserved(self):
        d = candle_to_dict(_C1)
        assert d["open"] == _C1.open
        assert d["high"] == _C1.high
        assert d["low"] == _C1.low
        assert d["close"] == _C1.close

    def test_volume_is_zero(self):
        assert candle_to_dict(_C1)["volume"] == 0

    def test_tz_aware_timestamp_includes_offset(self):
        d = candle_to_dict(_C1)
        assert "+00:00" in d["time"]


class TestCandleApiHappyPath:
    def test_returns_200(self):
        app, _ = _make_app(candles=[_C1, _C2, _C3])
        with TestClient(app) as client:
            resp = client.get("/api/scan/candles?symbol=EURUSD&timeframe=15m&limit=3")
        assert resp.status_code == 200

    def test_meta_fields(self):
        app, _ = _make_app(candles=[_C1, _C2, _C3])
        with TestClient(app) as client:
            body = client.get("/api/scan/candles?symbol=EURUSD&timeframe=15m&limit=3").json()
        assert body["meta"] == {"symbol": "EURUSD", "timeframe": "15m", "bars": 3}

    def test_candles_length(self):
        app, _ = _make_app(candles=[_C1, _C2, _C3])
        with TestClient(app) as client:
            body = client.get("/api/scan/candles?symbol=EURUSD&timeframe=15m&limit=3").json()
        assert len(body["candles"]) == 3

    def test_candle_shape(self):
        app, _ = _make_app(candles=[_C1])
        with TestClient(app) as client:
            body = client.get("/api/scan/candles?symbol=EURUSD&timeframe=15m").json()
        c = body["candles"][0]
        assert set(c.keys()) == {"time", "open", "high", "low", "close", "volume"}

    def test_store_called_with_mapped_args(self):
        app, store = _make_app(candles=[_C1, _C2, _C3])
        with TestClient(app) as client:
            client.get("/api/scan/candles?symbol=EURUSD&timeframe=15m&limit=3")
        assert store.recent_candles_calls == [("capital", "CS.D.EURUSD.MINI.IP", "MINUTE_15", 3)]

    def test_default_provider_is_capital(self):
        app, store = _make_app(candles=[_C1])
        with TestClient(app) as client:
            client.get("/api/scan/candles?symbol=EURUSD&timeframe=15m")
        provider, *_ = store.recent_candles_calls[0]
        assert provider == "capital"

    def test_default_limit_is_500(self):
        app, store = _make_app(candles=[_C1])
        with TestClient(app) as client:
            client.get("/api/scan/candles?symbol=EURUSD&timeframe=15m")
        *_, count = store.recent_candles_calls[0]
        assert count == 500


class TestCandleApiProviderParam:
    def test_custom_provider_forwarded(self):
        app, store = _make_app(candles=[_C1])
        with TestClient(app) as client:
            client.get("/api/scan/candles?symbol=EURUSD&timeframe=15m&provider=ic_markets")
        provider, *_ = store.recent_candles_calls[0]
        assert provider == "ic_markets"


class TestCandleApiErrorCases:
    def test_unknown_symbol_returns_404(self):
        app, _ = _make_app()
        with TestClient(app) as client:
            resp = client.get("/api/scan/candles?symbol=UNKNOWN&timeframe=15m")
        assert resp.status_code == 404

    def test_unknown_timeframe_returns_400(self):
        app, _ = _make_app()
        with TestClient(app) as client:
            resp = client.get("/api/scan/candles?symbol=EURUSD&timeframe=INVALID")
        assert resp.status_code == 400

    def test_missing_symbol_returns_422(self):
        app, _ = _make_app()
        with TestClient(app) as client:
            resp = client.get("/api/scan/candles?timeframe=15m")
        assert resp.status_code == 422

    def test_missing_timeframe_returns_422(self):
        app, _ = _make_app()
        with TestClient(app) as client:
            resp = client.get("/api/scan/candles?symbol=EURUSD")
        assert resp.status_code == 422

    def test_limit_zero_returns_422(self):
        app, _ = _make_app()
        with TestClient(app) as client:
            resp = client.get("/api/scan/candles?symbol=EURUSD&timeframe=15m&limit=0")
        assert resp.status_code == 422

    def test_limit_negative_returns_422(self):
        app, _ = _make_app()
        with TestClient(app) as client:
            resp = client.get("/api/scan/candles?symbol=EURUSD&timeframe=15m&limit=-1")
        assert resp.status_code == 422

    def test_empty_result_returns_200_with_zero_bars(self):
        app, _ = _make_app(candles=[])
        with TestClient(app) as client:
            body = client.get("/api/scan/candles?symbol=EURUSD&timeframe=15m").json()
        assert body["meta"]["bars"] == 0
        assert body["candles"] == []


class TestCandleApiCors:
    def test_cors_header_present(self):
        store = FakeCandleStore(candles=[])
        app = create_app(
            store,
            symbol_to_epic=_SYMBOL_MAP,
            resolution_map=_RESOLUTION_MAP,
            allow_origins=["http://localhost:5173"],
        )
        with TestClient(app) as client:
            resp = client.get(
                "/api/scan/candles?symbol=EURUSD&timeframe=15m",
                headers={"Origin": "http://localhost:5173"},
            )
        assert "access-control-allow-origin" in resp.headers


class TestTradesApiHappyPath:
    def test_returns_200_with_well_formed_body(self):
        app, _ = _make_app(candles=[_C1, _C2, _C3])
        with TestClient(app) as client:
            resp = client.get("/api/scan/trades?symbol=EURUSD&timeframe=15m&limit=3")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["trades"], list)
        assert set(body["meta"].keys()) == {
            "symbol", "timeframe", "trades", "win_rate", "total_r", "expectancy_r", "cost_pct",
        }

    def test_meta_symbol_and_timeframe(self):
        app, _ = _make_app(candles=[_C1, _C2, _C3])
        with TestClient(app) as client:
            body = client.get("/api/scan/trades?symbol=EURUSD&timeframe=15m&limit=3").json()
        assert body["meta"]["symbol"] == "EURUSD"
        assert body["meta"]["timeframe"] == "15m"

    def test_store_called_with_mapped_args(self):
        app, store = _make_app(candles=[_C1, _C2, _C3])
        with TestClient(app) as client:
            client.get("/api/scan/trades?symbol=EURUSD&timeframe=15m&limit=3")
        assert ("capital", "CS.D.EURUSD.MINI.IP", "MINUTE_15", 3) in store.recent_candles_calls

    def test_default_provider_is_capital(self):
        app, store = _make_app(candles=[_C1])
        with TestClient(app) as client:
            client.get("/api/scan/trades?symbol=EURUSD&timeframe=15m")
        provider, *_ = store.recent_candles_calls[0]
        assert provider == "capital"

    def test_default_limit_is_500(self):
        app, store = _make_app(candles=[_C1])
        with TestClient(app) as client:
            client.get("/api/scan/trades?symbol=EURUSD&timeframe=15m")
        *_, count = store.recent_candles_calls[0]
        assert count == 500

    def test_empty_candles_returns_empty_trades(self):
        app, _ = _make_app(candles=[])
        with TestClient(app) as client:
            body = client.get("/api/scan/trades?symbol=EURUSD&timeframe=15m").json()
        assert body["trades"] == []


class TestTradesApiStrategyMinimumBoundary:
    def test_below_minimum_returns_empty_trades(self):
        app, _ = _make_app(candles=_make_candles(_MIN_CANDLES_FOR_STRATEGY - 1))
        with TestClient(app) as client:
            resp = client.get("/api/scan/trades?symbol=EURUSD&timeframe=15m")
        assert resp.status_code == 200
        assert resp.json()["trades"] == []

    def test_at_minimum_returns_200_with_well_formed_body(self):
        app, _ = _make_app(candles=_make_candles(_MIN_CANDLES_FOR_STRATEGY))
        with TestClient(app) as client:
            resp = client.get("/api/scan/trades?symbol=EURUSD&timeframe=15m")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["trades"], list)
        assert body["meta"]["trades"] == len(body["trades"])


class TestTradesApiErrorCases:
    def test_unknown_symbol_returns_404(self):
        app, _ = _make_app()
        with TestClient(app) as client:
            resp = client.get("/api/scan/trades?symbol=UNKNOWN&timeframe=15m")
        assert resp.status_code == 404

    def test_unknown_timeframe_returns_400(self):
        app, _ = _make_app()
        with TestClient(app) as client:
            resp = client.get("/api/scan/trades?symbol=EURUSD&timeframe=INVALID")
        assert resp.status_code == 400

    def test_missing_symbol_returns_422(self):
        app, _ = _make_app()
        with TestClient(app) as client:
            resp = client.get("/api/scan/trades?timeframe=15m")
        assert resp.status_code == 422

    def test_missing_timeframe_returns_422(self):
        app, _ = _make_app()
        with TestClient(app) as client:
            resp = client.get("/api/scan/trades?symbol=EURUSD")
        assert resp.status_code == 422

    def test_limit_zero_returns_422(self):
        app, _ = _make_app()
        with TestClient(app) as client:
            resp = client.get("/api/scan/trades?symbol=EURUSD&timeframe=15m&limit=0")
        assert resp.status_code == 422

    def test_limit_negative_returns_422(self):
        app, _ = _make_app()
        with TestClient(app) as client:
            resp = client.get("/api/scan/trades?symbol=EURUSD&timeframe=15m&limit=-1")
        assert resp.status_code == 422


class TestDatasetsEndpoint:
    def test_returns_200(self):
        app, _ = _make_app()
        with TestClient(app) as client:
            resp = client.get("/api/scan/datasets")
        assert resp.status_code == 200

    def test_symbols_are_friendly_and_sorted(self):
        store = FakeCandleStore(candles=[])
        app = create_app(
            store,
            symbol_to_epic={"GBPUSD": "CS.D.GBPUSD.MINI.IP", "EURUSD": "CS.D.EURUSD.MINI.IP"},
            resolution_map=_RESOLUTION_MAP,
        )
        with TestClient(app) as client:
            body = client.get("/api/scan/datasets").json()
        assert body["symbols"] == ["EURUSD", "GBPUSD"]

    def test_datasets_are_symbols_times_timeframes(self):
        app, _ = _make_app()
        with TestClient(app) as client:
            body = client.get("/api/scan/datasets").json()
        assert len(body["datasets"]) == len(_RESOLUTION_MAP)
        assert all(set(d.keys()) == {"symbol", "timeframe"} for d in body["datasets"])
        assert all(d["symbol"] == "EURUSD" for d in body["datasets"])

    def test_empty_symbol_map_returns_empty(self):
        store = FakeCandleStore(candles=[])
        app = create_app(store, symbol_to_epic={}, resolution_map=_RESOLUTION_MAP)
        with TestClient(app) as client:
            body = client.get("/api/scan/datasets").json()
        assert body["symbols"] == []
        assert body["datasets"] == []
