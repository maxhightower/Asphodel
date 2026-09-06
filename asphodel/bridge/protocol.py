"""The versioned Godot <-> World IPC protocol (M1).

Wire format is **newline-delimited JSON** ("JSON Lines"): one JSON object per
line, ``\\n``-terminated, requests and responses alike. Rationale over a binary
protocol: it is trivially debuggable (a human or a test can read the stream),
deterministic in ordering (the server answers one request before reading the
next), low-overhead for local single-client development, and Godot speaks it out
of the box (``StreamPeerTCP`` + ``JSON``). The framing lives in
:mod:`asphodel.bridge.server`; this module is pure data + validation and imports
nothing heavy, so both ends can share the vocabulary.

Every message is a flat JSON object. A **request** carries a ``cmd`` (one of
:class:`Command`) and command-specific fields; an optional integer ``id`` is
echoed back so a client can match replies. A **response** carries
``protocol_version``, ``ok`` (bool), the echoed ``cmd``/``id``, and either
result fields (``ok: true``) or an ``error`` object (``ok: false``).

The protocol layer deliberately does **not** re-interpret world state: where a
response needs to describe the world it embeds :meth:`World.snapshot` verbatim
under ``world``. There is one renderer contract, and it lives in the engine.
"""

from __future__ import annotations

from typing import Any


# Bump on any breaking change to command/response shape. A client HELLO carrying
# a different major version is rejected (see WorldSession.handle / Command.HELLO).
# v1: authoritative world (M1). v2: + Package 3 survival/interaction commands.
# v3: + GET_INTERIOR (walk-in interiors: authoritative interior descriptor).
# v4: + ADVANCE_TIME / MOBILITY_REPORT / GET_MOBILITY (embodied mobility: the
#      continuous movement clock, NEAR-body physical reports, the movement snapshot).
# v5: + SEED_OUTBREAK / GET_OUTBREAK and the START_WORLD `outbreak` option
#      (ASPHODEL_OUTBREAK_V1: per-citizen health, events, disruptions).
# v6: + GET_WORK / GET_ROOMS / SET_OBJECT_STATE and the START_WORLD `work`
#      option (ASPHODEL_SMART_OBJECTS_WORK_V1: rooms, smart objects, work).
# v7: + GET_COGNITION / GET_CITIZEN_CONTEXT and the START_WORLD `cognition`
#      option (ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1: memory, beliefs,
#      relationships, social actions; the context API for dialogue).
# v8: + TALK / GET_DIALOGUE and the START_WORLD `dialogue` option
#      (ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1: grounded conversations).
PROTOCOL_VERSION = 8


class Command:
    """The command vocabulary (Godot -> simulation)."""

    HELLO = "HELLO"            # handshake + version negotiation
    START_WORLD = "START_WORLD"  # construct the authoritative World
    SET_FOCUS = "SET_FOCUS"    # zones under player attention -> World.set_focus
    ADVANCE = "ADVANCE"        # advance the world by an exact tick count
    INTERVENE = "INTERVENE"    # World.intervene(...)
    INTERACT_WITH = "INTERACT_WITH"  # player engaged a citizen -> World.interact_with
    PAUSE = "PAUSE"            # freeze advancement
    RESUME = "RESUME"          # unfreeze
    SNAPSHOT = "SNAPSHOT"      # World.snapshot() without advancing
    SAVE = "SAVE"              # persist the authoritative world to a path
    LOAD = "LOAD"              # replace the world from a saved path
    SHUTDOWN = "SHUTDOWN"      # end the session/process cleanly

    # --- Package 3: survival-resource interaction (v2) ---------------------
    ENTER_BUILDING = "ENTER_BUILDING"        # player enters a building interior
    LEAVE_BUILDING = "LEAVE_BUILDING"        # player leaves the current building
    INSPECT_BUILDING = "INSPECT_BUILDING"    # enumerate a building's containers
    SEARCH_CONTAINER = "SEARCH_CONTAINER"    # reveal a container's contents
    TAKE_ITEM = "TAKE_ITEM"                  # take item(s) from a container
    DROP_ITEM = "DROP_ITEM"                  # drop item(s) into the world
    USE_ITEM = "USE_ITEM"                    # use/consume an item from inventory
    INSPECT_INVENTORY = "INSPECT_INVENTORY"  # read the player inventory + needs

    # --- Walk-in interiors (v3) -------------------------------------------
    GET_INTERIOR = "GET_INTERIOR"            # authoritative interior descriptor + deltas

    # --- Embodied mobility (v4) -------------------------------------------
    ADVANCE_TIME = "ADVANCE_TIME"            # advance continuous game seconds (movement clock)
    MOBILITY_REPORT = "MOBILITY_REPORT"      # NEAR bodies report physical positions/blockage
    GET_MOBILITY = "GET_MOBILITY"            # movement snapshot without advancing

    # --- Outbreak (v5) ----------------------------------------------------
    SEED_OUTBREAK = "SEED_OUTBREAK"          # enable the outbreak runtime / seed an index case
    GET_OUTBREAK = "GET_OUTBREAK"            # health rows + events since a sequence number
    # --- smart objects / work (v6) --------------------------------------
    GET_WORK = "GET_WORK"                    # sessions, reservations, queues, events since seq
    GET_ROOMS = "GET_ROOMS"                  # rooms, zones, smart objects and occupants of a building
    SET_OBJECT_STATE = "SET_OBJECT_STATE"    # authoritative external object state change
    # --- npc cognition (v7) ---------------------------------------------
    GET_COGNITION = "GET_COGNITION"          # cognition events since seq, counts, who is avoiding what
    GET_CITIZEN_CONTEXT = "GET_CITIZEN_CONTEXT"  # the structured context of one citizen (dialogue input)
    # --- npc dialogue (v8) ------------------------------------------------
    TALK = "TALK"                            # the player speaks one structured act to a NEAR citizen
    GET_DIALOGUE = "GET_DIALOGUE"            # dialogue events since seq, active conversations, requests

    ALL = frozenset({
        HELLO, START_WORLD, SET_FOCUS, ADVANCE, INTERVENE, INTERACT_WITH,
        PAUSE, RESUME, SNAPSHOT, SAVE, LOAD, SHUTDOWN,
        ENTER_BUILDING, LEAVE_BUILDING, INSPECT_BUILDING, SEARCH_CONTAINER,
        TAKE_ITEM, DROP_ITEM, USE_ITEM, INSPECT_INVENTORY,
        GET_INTERIOR,
        ADVANCE_TIME, MOBILITY_REPORT, GET_MOBILITY,
        SEED_OUTBREAK, GET_OUTBREAK,
        GET_WORK, GET_ROOMS, SET_OBJECT_STATE,
        GET_COGNITION, GET_CITIZEN_CONTEXT,
        TALK, GET_DIALOGUE,
    })


class ErrorCode:
    """Stable machine-readable error codes carried in an error response."""

    MALFORMED = "malformed"                # not a JSON object / missing cmd
    UNKNOWN_COMMAND = "unknown_command"
    VERSION_MISMATCH = "version_mismatch"
    NOT_STARTED = "not_started"            # command needs a world; none started
    ALREADY_STARTED = "already_started"
    BAD_ARGUMENT = "bad_argument"
    PAUSED = "paused"                      # ADVANCE refused while paused
    INTERNAL = "internal"                  # unexpected engine exception
    ILLEGAL_ACTION = "illegal_action"      # a rejected survival action (v2)


class ProtocolError(Exception):
    """Raised by helpers when a message cannot be formed/validated."""

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


def request(cmd: str, id: int | None = None, **fields: Any) -> dict:
    """Build a request envelope (client side)."""
    if cmd not in Command.ALL:
        raise ProtocolError(ErrorCode.UNKNOWN_COMMAND, f"unknown command {cmd!r}")
    msg: dict = {"cmd": cmd}
    if id is not None:
        msg["id"] = int(id)
    msg.update(fields)
    return msg


def response(cmd: str | None, id: int | None = None, **fields: Any) -> dict:
    """Build a success response envelope (server side)."""
    msg: dict = {"protocol_version": PROTOCOL_VERSION, "ok": True, "cmd": cmd}
    if id is not None:
        msg["id"] = int(id)
    msg.update(fields)
    return msg


def error_response(code: str, message: str,
                   cmd: str | None = None, id: int | None = None) -> dict:
    """Build an error response envelope (server side)."""
    msg: dict = {
        "protocol_version": PROTOCOL_VERSION,
        "ok": False,
        "cmd": cmd,
        "error": {"code": code, "message": message},
    }
    if id is not None:
        msg["id"] = int(id)
    return msg


def is_compatible(client_version: int) -> bool:
    """Version policy: exact match required for protocol v1."""
    return int(client_version) == PROTOCOL_VERSION
