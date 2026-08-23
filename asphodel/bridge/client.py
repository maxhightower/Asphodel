"""A small synchronous Python client for the bridge (M1).

Used by the integration tests and mirrored one-to-one by the GDScript
``godot/scripts/sim_bridge.gd`` client, so the Python tests exercise the exact
request/response contract Godot will speak. Every call sends one request line and
blocks for exactly one response line (the server is synchronous), which keeps the
command stream an ordered, deterministic driver of the authoritative world.
"""

from __future__ import annotations

import json
import socket

from . import protocol as P
from .protocol import Command


class BridgeClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None
        self._file = None
        self._id = 0

    # -------------------------------------------------------------- lifecycle
    def connect(self, timeout: float = 5.0) -> "BridgeClient":
        self._sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self._file = self._sock.makefile("rb")
        return self

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass

    def __enter__(self) -> "BridgeClient":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    # -------------------------------------------------------------- raw send
    def send(self, cmd: str, **fields) -> dict:
        """Send one request, return the one response dict."""
        self._id += 1
        msg = P.request(cmd, id=self._id, **fields)
        self._sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        line = self._file.readline()
        if not line:
            raise ConnectionError("bridge closed the connection")
        return json.loads(line.decode("utf-8"))

    def send_raw(self, raw: str) -> dict:
        """Send an arbitrary raw line (for malformed-input tests)."""
        self._sock.sendall((raw + "\n").encode("utf-8"))
        line = self._file.readline()
        if not line:
            raise ConnectionError("bridge closed the connection")
        return json.loads(line.decode("utf-8"))

    # -------------------------------------------------------------- typed calls
    def hello(self, protocol_version: int = P.PROTOCOL_VERSION) -> dict:
        return self.send(Command.HELLO, protocol_version=protocol_version)

    def start_world(self, bundle: str, **kw) -> dict:
        return self.send(Command.START_WORLD, bundle=bundle, **kw)

    def set_focus(self, zones) -> dict:
        return self.send(Command.SET_FOCUS, zones=list(zones))

    def advance(self, ticks: int = 1, snapshot: bool = False) -> dict:
        return self.send(Command.ADVANCE, ticks=ticks, snapshot=snapshot)

    def intervene(self, action: str, zones=None, **params) -> dict:
        extra = dict(params)
        if zones is not None:
            extra["zones"] = list(zones) if not isinstance(zones, int) else zones
        return self.send(Command.INTERVENE, action=action, **extra)

    def pause(self) -> dict:
        return self.send(Command.PAUSE)

    def resume(self) -> dict:
        return self.send(Command.RESUME)

    def snapshot(self) -> dict:
        return self.send(Command.SNAPSHOT)

    def shutdown(self) -> dict:
        return self.send(Command.SHUTDOWN)
