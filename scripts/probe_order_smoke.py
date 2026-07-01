"""Bounded end-to-end order smoke probe against Capital DEMO.

Opens ONE minimal EURUSD position through the REAL CapitalBrokerAdapter with a
known SL/TP, captures the raw POST /positions and GET /confirms shapes, verifies
what SL/TP the broker actually anchored versus what was requested, then CLOSES
the position so no exposure is left open.

Refuses to run unless MODE=demo. Read-only w.r.t. our code (uses production
adapter and session); the only side effect is a demo open+close round-trip.

Usage:
    cd operator && uv run python scripts/probe_order_smoke.py
"""

from __future__ import annotations

import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import requests
from dotenv import load_dotenv

from config import load_config
from domain.entities.direction import Direction
from domain.entities.signal import Signal
from infrastructure.capital.broker import CapitalBrokerAdapter
from infrastructure.capital.session import CapitalSession

_EPIC = "EURUSD"
_SYMBOL = "EURUSD"
_SIZE = 100.0
_SL_DISTANCE = 0.0020
_TP_DISTANCE = 0.0020

_log = logging.getLogger("probe_order_smoke")


class _CapturingHttp:
    """Wraps requests.Session and logs each POST/GET request+response body."""

    def __init__(self, inner: requests.Session) -> None:
        self._inner = inner

    def post(self, url: str, **kwargs):
        _log.info("POST %s\n  body=%s", url, json.dumps(kwargs.get("json"), indent=2))
        resp = self._inner.post(url, **kwargs)
        _log.info("  -> %s %s", resp.status_code, _safe_body(resp))
        return resp

    def get(self, url: str, **kwargs):
        resp = self._inner.get(url, **kwargs)
        _log.info("GET %s -> %s %s", url, resp.status_code, _safe_body(resp))
        return resp

    def delete(self, url: str, **kwargs):
        resp = self._inner.delete(url, **kwargs)
        _log.info("DELETE %s -> %s %s", url, resp.status_code, _safe_body(resp))
        return resp


def _safe_body(resp) -> str:
    try:
        return json.dumps(resp.json())[:600]
    except Exception:
        return resp.text[:300]


def _auth_headers(session: CapitalSession) -> dict[str, str]:
    t = session.tokens()
    return {"CST": t.cst, "X-SECURITY-TOKEN": t.security_token}


def _find_open_position(http, base_url: str, session: CapitalSession, deal_id: str):
    resp = http.get(f"{base_url}/positions", headers=_auth_headers(session))
    resp.raise_for_status()
    for p in resp.json().get("positions", []):
        pos = p.get("position", {})
        if pos.get("dealId") == deal_id or p.get("market", {}).get("epic") == _EPIC:
            return p
    return None


def _close_position(http, base_url: str, session: CapitalSession, deal_id: str) -> None:
    _log.info("closing position dealId=%s", deal_id)
    resp = http.delete(
        f"{base_url}/positions/{deal_id}", headers=_auth_headers(session)
    )
    if resp.status_code >= 400:
        _log.error("close failed: %s %s", resp.status_code, _safe_body(resp))
        return
    _log.info("close accepted")


def main() -> int:
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    config = load_config()
    if config.mode != "demo":
        _log.error("refusing: MODE=%s (expected demo)", config.mode)
        return 2

    inner_http = requests.Session()
    session = CapitalSession(
        http=inner_http,
        base_url=config.base_url,
        api_key=config.api_key,
        identifier=config.identifier,
        password=config.password,
    )
    _log.info("authenticating ...")
    session.authenticate()
    _log.info("authenticated")

    http = _CapturingHttp(inner_http)
    broker = CapitalBrokerAdapter(
        session=session,
        http=http,
        base_url=config.base_url,
        epics={_SYMBOL: _EPIC},
        timeframe=config.timeframe,
    )

    signal = Signal(
        direction=Direction.BUY,
        sl_distance=_SL_DISTANCE,
        tp_distance=_TP_DISTANCE,
    )

    _log.info(
        "opening %s %s size=%s sl_dist=%s tp_dist=%s",
        _SYMBOL, signal.direction.name, _SIZE, _SL_DISTANCE, _TP_DISTANCE,
    )
    result = broker.open_position(_SYMBOL, signal, _SIZE)
    _log.info(
        "OrderResult: order_id=%s status=%s filled_price=%s",
        result.order_id, result.status, result.filled_price,
    )

    deal_id = result.order_id
    try:
        pos = _find_open_position(http, config.base_url, session, deal_id)
        if pos is None:
            _log.warning("could not locate open position to verify SL/TP anchoring")
        else:
            position = pos.get("position", {})
            fill = result.filled_price
            stop_level = position.get("stopLevel")
            limit_level = position.get("limitLevel")
            _log.info("--- SL/TP anchoring check ---")
            _log.info("  fill_price   = %s", fill)
            _log.info("  stopLevel    = %s (expected ~ %.5f)", stop_level, fill - _SL_DISTANCE)
            _log.info("  limitLevel   = %s (expected ~ %.5f)", limit_level, fill + _TP_DISTANCE)
            if stop_level is not None:
                _log.info("  actual SL distance from fill = %.5f (requested %.5f)",
                          abs(fill - float(stop_level)), _SL_DISTANCE)
            if limit_level is not None:
                _log.info("  actual TP distance from fill = %.5f (requested %.5f)",
                          abs(float(limit_level) - fill), _TP_DISTANCE)
    finally:
        _close_position(http, config.base_url, session, deal_id)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
