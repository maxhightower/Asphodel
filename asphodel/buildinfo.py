"""Build / version identity for the simulation authority.

The Windows playable's handshake (Convergence V2, §11) must let the Godot client
detect a wrong or stale authority. This module is the single source of the
simulation's identity: its source SHA, protocol version and save version. It works
both from a git checkout (dev) and from a frozen/packaged authority that ships a
``SIM_SHA`` text file next to the executable.
"""
from __future__ import annotations

import os
import subprocess
import sys

from .bridge import protocol as _P
from .save import SAVE_VERSION

_CACHED_SHA: str | None = None


def _read_stamp() -> str | None:
    """A packaged authority ships its SHA in a stamp file (git is absent there)."""
    # next to this module, and next to a frozen executable
    candidates = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "SIM_SHA")]
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(os.path.dirname(sys.executable), "SIM_SHA"))
    for p in candidates:
        try:
            with open(p, "r", encoding="utf-8") as f:
                s = f.read().strip()
                if s:
                    return s
        except OSError:
            continue
    return None


def sim_sha() -> str:
    """Full source SHA of this authority. Cached. 'unknown' if unavailable."""
    global _CACHED_SHA
    if _CACHED_SHA is not None:
        return _CACHED_SHA
    sha = _read_stamp()
    if sha is None:
        try:
            repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            sha = subprocess.check_output(
                ["git", "-C", repo, "rev-parse", "HEAD"],
                stderr=subprocess.DEVNULL, timeout=5,
            ).decode().strip()
        except Exception:
            sha = "unknown"
    _CACHED_SHA = sha
    return sha


def protocol_version() -> int:
    return int(_P.PROTOCOL_VERSION)


def save_version() -> int:
    return int(SAVE_VERSION)


def build_info() -> dict:
    """The identity block echoed in the HELLO / START_WORLD handshake."""
    return {
        "sim_sha": sim_sha(),
        "protocol_version": protocol_version(),
        "save_version": save_version(),
    }
