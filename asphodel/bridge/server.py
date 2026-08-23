"""Localhost TCP JSON-lines server wrapping a :class:`WorldSession` (M1).

Transport choice: **TCP on 127.0.0.1**, one JSON object per line. Justification
over a Unix socket or pipes: it is cross-platform (Godot ships to Windows, which
has no ``AF_UNIX`` in older runtimes), Godot speaks it natively via
``StreamPeerTCP``, and a localhost socket has negligible overhead for a single
local client. The server is deliberately **single-client, synchronous**: it reads
one request, fully processes it against the authoritative world, writes exactly
one response, then reads the next. That ordering is what makes the command stream
a deterministic driver of world state -- there is no concurrency to reorder
advancement.

Run standalone for Godot to spawn::

    python -m asphodel.bridge.server --host 127.0.0.1 --port 8765

Port ``0`` binds an ephemeral port; the chosen port is printed as a JSON line
``{"event":"listening","host":...,"port":...}`` on stdout so a launcher can read
it back.
"""

from __future__ import annotations

import argparse
import json
import socket
import threading

from .session import WorldSession
from . import protocol as P
from .protocol import ErrorCode


class BridgeServer:
    """A single-client JSON-lines TCP server over one authoritative world."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0,
                 stop_on_shutdown: bool = True) -> None:
        self.host = host
        self.port = port
        self.stop_on_shutdown = stop_on_shutdown
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self.last_session: WorldSession | None = None

    # -------------------------------------------------------------- lifecycle
    def start(self) -> int:
        """Bind + listen, spawn the accept loop in a background thread, return
        the actually-bound port."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def __enter__(self) -> "BridgeServer":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # -------------------------------------------------------------- accept loop
    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, _addr = self._sock.accept()
            except OSError:
                break  # socket closed by stop()
            try:
                self._serve_client(conn)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
            if not self._running:
                break

    def _serve_client(self, conn: socket.socket) -> None:
        session = WorldSession()
        self.last_session = session
        buf = b""
        conn_file = conn.makefile("rb")
        for raw in conn_file:
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as e:
                resp = P.error_response(ErrorCode.MALFORMED, f"invalid JSON: {e}")
            else:
                resp = session.handle(msg)
            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
            if session.should_stop:
                break
        if session.should_stop and self.stop_on_shutdown:
            self._running = False
            try:
                self._sock.close()
            except OSError:
                pass


def serve_forever(host: str, port: int) -> None:
    srv = BridgeServer(host=host, port=port, stop_on_shutdown=True)
    bound = srv.start()
    print(json.dumps({"event": "listening", "host": host, "port": bound}),
          flush=True)
    try:
        while srv._running:
            if srv._thread is not None:
                srv._thread.join(timeout=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Asphodel live World bridge server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)
    serve_forever(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
