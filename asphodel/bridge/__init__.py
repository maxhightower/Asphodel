"""Live runtime authority bridge (M1).

Godot is a *client* of an authoritative Python :class:`~asphodel.orchestrator.World`.
This package is the seam: a small, versioned, JSON-line IPC protocol
(:mod:`asphodel.bridge.protocol`), a transport-free command processor that owns
the world (:class:`asphodel.bridge.session.WorldSession`), a localhost TCP server
that frames it on the wire (:mod:`asphodel.bridge.server`), and a Python client
mirrored by the GDScript ``sim_bridge.gd`` (:mod:`asphodel.bridge.client`).

The contract: **Python owns simulation truth.** Godot may render snapshots,
report focus, submit interventions, and request pause/advance/snapshot/shutdown.
Godot never advances the outbreak itself -- the world advances only, and exactly,
when an ``ADVANCE`` command says so.
"""

from .protocol import (
    PROTOCOL_VERSION,
    Command,
    ErrorCode,
    request,
    response,
    error_response,
    ProtocolError,
)
from .session import WorldSession
from .worldfactory import config_from_bundle, world_from_bundle, resolve_bundle_dir

__all__ = [
    "PROTOCOL_VERSION",
    "Command",
    "ErrorCode",
    "request",
    "response",
    "error_response",
    "ProtocolError",
    "WorldSession",
    "config_from_bundle",
    "world_from_bundle",
    "resolve_bundle_dir",
]
