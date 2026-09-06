"""Frozen-authority entrypoint for the Asphodel Windows/Linux client.

This is the single script PyInstaller freezes (see tools/package_authority.py).
It exists so the freeze has a concrete file to analyze (PyInstaller prefers a
script over ``-m``), and so the shipped authority has ONE stable entry name.

Behavior is intentionally identical to ``python -m asphodel.bridge.server``:
it starts the authoritative :class:`BridgeServer` and, once bound, prints the
JSON line ``{"event":"listening","host":...,"port":...}`` on stdout so the Godot
launcher can read back the OS-negotiated port. Pass ``--port 0`` for an
ephemeral port (recommended) or a fixed ``--port N``.

    authority --host 127.0.0.1 --port 0
"""

from __future__ import annotations

import multiprocessing
import sys

from asphodel.bridge.server import main


if __name__ == "__main__":
    # Frozen apps that ever spawn processes must call this first on Windows.
    multiprocessing.freeze_support()
    raise SystemExit(main(sys.argv[1:]))
