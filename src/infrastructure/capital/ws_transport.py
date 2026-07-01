from __future__ import annotations

import json

import websocket


class WebsocketClientTransport:
    """Wraps websocket-client WebSocket as a synchronous WS transport.

    Implements the transport seam expected by CapitalWsIngester:
    connect / send / recv / ping / close.
    """

    def __init__(self) -> None:
        self._ws: websocket.WebSocket | None = None

    def connect(self, url: str) -> None:
        self._ws = websocket.WebSocket()
        self._ws.connect(url)

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
