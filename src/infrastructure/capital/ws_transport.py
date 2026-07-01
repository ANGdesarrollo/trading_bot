from __future__ import annotations

import json

import websocket

_RECV_TIMEOUT_S = 30.0


class RecvTimeout(Exception):
    """recv() blocked past the socket timeout with no frame available."""


class WebsocketClientTransport:
    """Wraps websocket-client WebSocket as a synchronous WS transport.

    Implements the transport seam expected by CapitalWsIngester:
    connect / send / recv / ping / close.

    recv() uses a socket timeout so the caller regains control on idle
    connections and can send a keepalive ping before an upstream proxy
    drops the connection.
    """

    def __init__(self, recv_timeout_seconds: float = _RECV_TIMEOUT_S) -> None:
        self._ws: websocket.WebSocket | None = None
        self._recv_timeout = recv_timeout_seconds

    def connect(self, url: str) -> None:
        self._ws = websocket.WebSocket()
        self._ws.connect(url)
        self._ws.settimeout(self._recv_timeout)

    def send(self, payload: str | dict) -> None:
        assert self._ws is not None
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        try:
            self._ws.send(payload)
        except (websocket.WebSocketException, OSError) as exc:
            raise ConnectionError(str(exc)) from exc

    def recv(self) -> str:
        assert self._ws is not None
        try:
            return self._ws.recv()
        except websocket.WebSocketTimeoutException:
            raise RecvTimeout from None
        except (websocket.WebSocketException, OSError) as exc:
            raise ConnectionError(str(exc)) from exc

    def ping(self) -> None:
        assert self._ws is not None
        try:
            self._ws.ping()
        except (websocket.WebSocketException, OSError) as exc:
            raise ConnectionError(str(exc)) from exc

    def close(self) -> None:
        if self._ws is not None:
            self._ws.close()
            self._ws = None
