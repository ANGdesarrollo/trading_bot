"""Probe Capital.com WebSocket OHLC streaming (read-only diagnostic).

Connects to streamingHost, subscribes to EURUSD MINUTE OHLC, and streams updates
across at least one minute boundary. Each message is stamped with wall-clock time
so we can measure how long after a candle's theoretical close Capital pushes the
final OHLC. Also fetches the same candle via REST to compare bid/ask/mid fidelity.
Answers the timing + fidelity questions before committing to a streaming
ingestion architecture.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time

import requests
import websocket

REST_BASE = "https://demo-api-capital.backend-capital.com/api/v1"
EPIC = "EURUSD"
RESOLUTION = "MINUTE"
RUN_SECONDS = 150


def authenticate() -> tuple[str, str, str]:
    http = requests.Session()
    r = http.post(
        f"{REST_BASE}/session",
        json={"identifier": os.environ["IDENTIFIER"], "password": os.environ["PASSWORD"]},
        headers={"X-CAP-API-KEY": os.environ["CAPITAL_API_KEY"]},
    )
    r.raise_for_status()
    streaming_host = r.json()["streamingHost"].rstrip("/")
    return r.headers["CST"], r.headers["X-SECURITY-TOKEN"], streaming_host


def rest_latest_candles(cst: str, xst: str) -> list[dict]:
    http = requests.Session()
    r = http.get(
        f"{REST_BASE}/prices/{EPIC}?resolution={RESOLUTION}&max=3",
        headers={"CST": cst, "X-SECURITY-TOKEN": xst},
    )
    r.raise_for_status()
    return r.json()["prices"]


def main() -> None:
    cst, xst, streaming_host = authenticate()
    print(f"streamingHost = {streaming_host}")

    ws_url = f"{streaming_host}/connect"
    ws = websocket.create_connection(ws_url, timeout=RUN_SECONDS + 10)
    print(f"connected to {ws_url}")

    subscribe = {
        "destination": "OHLCMarketData.subscribe",
        "correlationId": "1",
        "cst": cst,
        "securityToken": xst,
        "payload": {"epics": [EPIC], "resolutions": [RESOLUTION], "type": "classic"},
    }
    ws.send(json.dumps(subscribe))
    print(f"sent OHLCMarketData.subscribe for {EPIC} {RESOLUTION}\n")

    received = 0
    deadline = time.time() + RUN_SECONDS
    while time.time() < deadline:
        try:
            raw = ws.recv()
        except Exception as exc:
            print("recv error:", exc)
            break
        now = dt.datetime.now(dt.timezone.utc)
        msg = json.loads(raw)
        payload = msg.get("payload", {})
        candle_t = payload.get("t")
        candle_utc = (
            dt.datetime.fromtimestamp(candle_t / 1000, tz=dt.timezone.utc).isoformat()
            if isinstance(candle_t, (int, float))
            else None
        )
        summary = {
            "recv_utc": now.isoformat(),
            "dest": msg.get("destination"),
            "epic": payload.get("epic"),
            "resolution": payload.get("resolution"),
            "candle_start_utc": candle_utc,
            "o": payload.get("o"),
            "h": payload.get("h"),
            "l": payload.get("l"),
            "c": payload.get("c"),
            "priceType": payload.get("priceType"),
        }
        print(f"--- message {received} ---")
        print(json.dumps(summary))
        received += 1

    ws.close()

    print("\n=== REST comparison (last 3 candles) ===")
    for c in rest_latest_candles(cst, xst):
        print(json.dumps({
            "snapshotTimeUTC": c.get("snapshotTimeUTC"),
            "openPrice": c.get("openPrice"),
            "highPrice": c.get("highPrice"),
            "lowPrice": c.get("lowPrice"),
            "closePrice": c.get("closePrice"),
        }))


if __name__ == "__main__":
    main()
