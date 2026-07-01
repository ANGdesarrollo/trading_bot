"""Probe: what `source` does Capital stamp on a stop-loss close activity?

Opens ONE EURUSD position with a very tight SL so it fills and gets stopped out
within seconds, then polls /history/activity to capture the raw shape and the
`source` of the CLOSE activity. This tells us whether the reconciler's
`source != "USER"` close filter is correct for SL/TP closes (which is what the
live bot actually produces — the bot never closes with a manual DELETE).

DEMO only. Uses the same SL distance semantics verified earlier (absolute price
points). SIZE=100 (min deal size).

Usage:
    cd operator && uv run python scripts/probe_stop_close_source.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import requests
from dotenv import load_dotenv

from config import load_config
from infrastructure.capital.session import CapitalSession

_EPIC = "EURUSD"
_SIZE = 100.0
_SL_DISTANCE = 0.00025  # ~2 pips, safely above the 0.01% minimum
_TP_DISTANCE = 0.00300  # far so only the SL can hit
_POLL_SECONDS = 240
_POLL_INTERVAL = 3

_log = logging.getLogger("probe_stop_close_source")


def _headers(session: CapitalSession) -> dict[str, str]:
    t = session.tokens()
    return {"CST": t.cst, "X-SECURITY-TOKEN": t.security_token}


def _open(http, base_url: str, session: CapitalSession, direction: str) -> str:
    body = {
        "epic": _EPIC,
        "direction": direction,
        "size": _SIZE,
        "stopDistance": _SL_DISTANCE,
        "profitDistance": _TP_DISTANCE,
        "guaranteedStop": False,
    }
    _log.info("POST /positions %s", json.dumps(body))
    r = http.post(f"{base_url}/positions", json=body, headers=_headers(session))
    r.raise_for_status()
    ref = r.json()["dealReference"]
    c = http.get(f"{base_url}/confirms/{ref}", headers=_headers(session))
    c.raise_for_status()
    confirm = c.json()
    deal_id = next(
        (d["dealId"] for d in confirm.get("affectedDeals", []) if d.get("status") == "OPENED"),
        confirm["dealId"],
    )
    fill = confirm.get("level") or 0
    stop = fill - _SL_DISTANCE if direction == "BUY" else fill + _SL_DISTANCE
    _log.info("opened dealId=%s dir=%s fill=%s stop=%s", deal_id, direction, fill, stop)
    return deal_id


def _still_open(http, base_url: str, session: CapitalSession, deal_id: str) -> bool:
    r = http.get(f"{base_url}/positions", headers=_headers(session))
    r.raise_for_status()
    for p in r.json().get("positions", []):
        if p.get("position", {}).get("dealId") == deal_id:
            return True
    return False


def _dump_close_activity(http, base_url: str, session: CapitalSession, deal_id: str, since: datetime) -> None:
    frm = since.strftime("%Y-%m-%dT%H:%M:%S")
    url = f"{base_url}/history/activity?dealId={deal_id}&detailed=true&from={frm}"
    r = http.get(url, headers=_headers(session))
    r.raise_for_status()
    acts = r.json().get("activities", [])
    _log.info("=== activities for dealId=%s (%d) ===", deal_id, len(acts))
    for a in acts:
        det = a.get("details") or {}
        _log.info(
            "  type=%s status=%s source=%s dir=%s level=%s openPrice=%s",
            a.get("type"), a.get("status"), a.get("source"),
            det.get("direction"), det.get("level"), det.get("openPrice"),
        )
    closes = [
        a for a in acts
        if a.get("type") == "POSITION" and "openPrice" in (a.get("details") or {})
    ]
    if closes:
        c = closes[0]
        _log.info(">>> CLOSE activity source = %r  (reconciler filters source != 'USER')", c.get("source"))
    else:
        _log.warning(">>> no POSITION close activity with openPrice found yet")


def main() -> int:
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    cfg = load_config()
    if cfg.mode != "demo":
        _log.error("refusing: MODE=%s", cfg.mode)
        return 2

    http = requests.Session()
    session = CapitalSession(
        http=http, base_url=cfg.base_url, api_key=cfg.api_key,
        identifier=cfg.identifier, password=cfg.password,
    )
    session.authenticate()

    opened_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    deal_id = _open(http, cfg.base_url, session, "SELL")

    deadline = time.time() + _POLL_SECONDS
    stopped = False
    while time.time() < deadline:
        if not _still_open(http, cfg.base_url, session, deal_id):
            _log.info("position no longer open — stop likely triggered")
            stopped = True
            break
        time.sleep(_POLL_INTERVAL)

    if not stopped:
        _log.warning("stop did not trigger within %ds; closing manually to clean up", _POLL_SECONDS)
        http.delete(f"{cfg.base_url}/positions/{deal_id}", headers=_headers(session))

    time.sleep(2)
    _dump_close_activity(http, cfg.base_url, session, deal_id, opened_at)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
