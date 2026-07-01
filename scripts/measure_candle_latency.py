"""Measure real Capital.com candle publication latency per symbol around a 15m boundary.

Read-only diagnostic: polls GET /prices once per second per symbol and records the
wall-clock offset (seconds after the boundary) at which each symbol's newest candle
first flips to the boundary timestamp. Answers "how long does Capital take to publish
the just-closed 15m candle" for each instrument.
"""

from __future__ import annotations

import datetime as dt
import os
import time

import requests

BASE = "https://demo-api-capital.backend-capital.com/api/v1"
PERIOD = 15 * 60
POLL_INTERVAL = 1.0
PRE_BOUNDARY_START = 5.0
MAX_WAIT_AFTER_BOUNDARY = 180.0


def _authenticate(http: requests.Session) -> dict[str, str]:
    resp = http.post(
        f"{BASE}/session",
        json={"identifier": os.environ["IDENTIFIER"], "password": os.environ["PASSWORD"]},
        headers={"X-CAP-API-KEY": os.environ["CAPITAL_API_KEY"]},
    )
    resp.raise_for_status()
    return {"CST": resp.headers["CST"], "X-SECURITY-TOKEN": resp.headers["X-SECURITY-TOKEN"]}


def _latest_utc(http: requests.Session, epic: str, headers: dict[str, str]) -> str | None:
    resp = http.get(
        f"{BASE}/prices/{epic}?resolution=MINUTE_15&max=2",
        headers=headers,
    )
    if resp.status_code != 200:
        return f"HTTP {resp.status_code}"
    prices = resp.json().get("prices", [])
    if not prices:
        return None
    return prices[-1].get("snapshotTimeUTC")


def main() -> None:
    symbols = [s.strip() for s in os.environ.get("SYMBOLS", "").split(",") if s.strip()]
    epics = {s: os.environ[f"EPIC_{s}"] for s in symbols}

    now = dt.datetime.now(dt.timezone.utc)
    ne = now.timestamp()
    boundary_epoch = ne - (ne % PERIOD) + PERIOD
    boundary = dt.datetime.fromtimestamp(boundary_epoch, tz=dt.timezone.utc)
    target_ts = boundary.strftime("%Y-%m-%dT%H:%M:%S")

    print(f"boundary target = {target_ts} (waiting for newest candle to flip to this)")
    print(f"symbols = {symbols}")

    http = requests.Session()
    headers = _authenticate(http)

    time.sleep(max(0.0, boundary_epoch - PRE_BOUNDARY_START - time.time()))

    published_at: dict[str, float] = {}
    last_seen: dict[str, str | None] = {s: None for s in symbols}

    deadline = boundary_epoch + MAX_WAIT_AFTER_BOUNDARY
    while time.time() < deadline and len(published_at) < len(symbols):
        for s in symbols:
            if s in published_at:
                continue
            latest = _latest_utc(http, epics[s], headers)
            offset = time.time() - boundary_epoch
            if latest != last_seen[s]:
                print(f"  [{offset:+6.1f}s] {s:8s} newest -> {latest}")
                last_seen[s] = latest
            if latest == target_ts:
                published_at[s] = offset
                print(f"  >>> {s:8s} PUBLISHED at {offset:+.1f}s after boundary")
        time.sleep(POLL_INTERVAL)

    print("\n=== RESULT: seconds after boundary until 14:15 candle appeared ===")
    for s in symbols:
        if s in published_at:
            print(f"  {s:8s} {published_at[s]:+.1f}s")
        else:
            print(f"  {s:8s} NOT PUBLISHED within {MAX_WAIT_AFTER_BOUNDARY:.0f}s")


if __name__ == "__main__":
    main()
