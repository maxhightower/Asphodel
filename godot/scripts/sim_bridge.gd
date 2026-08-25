extends Node

## SimBridge — Godot's client of the authoritative Python World (M1).
##
## Registered as the autoload singleton "SimBridge". This is the ONLY source of
## outbreak truth in the game: Godot renders what the live Python
## `asphodel.orchestrator.World` reports and submits player intent back over a
## small newline-delimited JSON protocol (see `asphodel/bridge/protocol.py`).
## Godot never advances the outbreak itself — the world advances only, and
## exactly, when we send ADVANCE.
##
## Transport: a synchronous localhost TCP StreamPeerTCP. Every request is one
## JSON line; we block for exactly one response line. Single-client, in order —
## which is what keeps the command stream a deterministic driver of the world.
##
## This mirrors `asphodel/bridge/client.py` one-to-one so the Python integration
## tests exercise the exact contract this speaks.

signal connected_changed(is_connected: bool)
signal world_started(summary: Dictionary)
signal advanced(tick: int, outbreak: float, summary: Dictionary)

const PROTOCOL_VERSION := 3   # v3: + GET_INTERIOR (walk-in interiors)

var _peer: StreamPeerTCP = null
var _id := 0
var _connected := false
var last_summary: Dictionary = {}

# The most recent authoritative snapshot (World.snapshot()), or {} if none.
var last_world: Dictionary = {}


func is_connected_to_sim() -> bool:
	return _connected


func connect_to_sim(host: String = "127.0.0.1", port: int = 8765, timeout_ms: int = 5000) -> bool:
	## Connect and complete the HELLO handshake. Returns true on success.
	_peer = StreamPeerTCP.new()
	var err := _peer.connect_to_host(host, port)
	if err != OK:
		push_error("SimBridge: connect_to_host failed: %d" % err)
		return false
	var deadline := Time.get_ticks_msec() + timeout_ms
	while _peer.get_status() == StreamPeerTCP.STATUS_CONNECTING:
		_peer.poll()
		if Time.get_ticks_msec() > deadline:
			push_error("SimBridge: connect timeout")
			return false
		OS.delay_msec(5)
	if _peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		push_error("SimBridge: not connected (status %d)" % _peer.get_status())
		return false
	var reply := _send("HELLO", {"protocol_version": PROTOCOL_VERSION})
	if not _ok(reply):
		push_error("SimBridge: HELLO rejected: %s" % str(reply))
		return false
	_set_connected(true)
	return true


func disconnect_from_sim() -> void:
	if _peer != null and _connected:
		_send("SHUTDOWN", {})
	if _peer != null:
		_peer.disconnect_from_host()
	_peer = null
	_set_connected(false)


# ------------------------------------------------------------------ commands
func start_world(bundle: String, opts: Dictionary = {}) -> Dictionary:
	var fields := {"bundle": bundle}
	for k in opts:
		fields[k] = opts[k]
	var r := _send("START_WORLD", fields)
	if _ok(r):
		last_summary = r
		world_started.emit(r)
	return r


func set_focus(zones: Array) -> Dictionary:
	return _send("SET_FOCUS", {"zones": zones})


func advance(ticks: int = 1, want_snapshot: bool = false) -> Dictionary:
	## Advance the authoritative world by exactly `ticks`. Returns the response;
	## emits `advanced` with the authoritative mean outbreak belief.
	var r := _send("ADVANCE", {"ticks": ticks, "snapshot": want_snapshot})
	if _ok(r):
		last_summary = r
		if r.has("world"):
			last_world = r["world"]
		advanced.emit(int(r.get("tick", 0)), _mean_belief_from(r), r)
	return r


func intervene(action: String, zones = null, params: Dictionary = {}) -> Dictionary:
	var fields := {"action": action}
	if zones != null:
		fields["zones"] = zones
	for k in params:
		fields[k] = params[k]
	return _send("INTERVENE", fields)


func interact_with(citizen_id: int) -> Dictionary:
	## The player engaged a citizen -> authoritative roster promotion.
	return _send("INTERACT_WITH", {"citizen_id": citizen_id})


# ----------------------------------------------- Package 3: survival-resource
func enter_building(building_id: int) -> Dictionary:
	## Player enters a building interior (authoritative container access).
	return _send("ENTER_BUILDING", {"building_id": building_id})


func leave_building() -> Dictionary:
	return _send("LEAVE_BUILDING", {})


func inspect_building(building_id: int) -> Dictionary:
	## Enumerate a building's containers (counts; contents stay implicit).
	return _send("INSPECT_BUILDING", {"building_id": building_id})


func search_container(building_id: int, index: int) -> Dictionary:
	## Reveal a container's authoritative current contents.
	return _send("SEARCH_CONTAINER", {"building_id": building_id, "index": index})


func take_item(building_id: int, index: int, kind: String, quantity: int = 1) -> Dictionary:
	## Take item(s) from a container into the authoritative player inventory.
	return _send("TAKE_ITEM", {"building_id": building_id, "index": index,
		"kind": kind, "quantity": quantity})


func drop_item(kind: String, quantity: int, x: float, y: float, zone: int = -1,
		building_id: int = -1) -> Dictionary:
	## Drop item(s) into the world at (x, y) as a persistent world item. Pass a
	## building_id >= 0 for an indoor drop bound to that interior.
	return _send("DROP_ITEM", {"kind": kind, "quantity": quantity,
		"x": x, "y": y, "zone": zone, "building_id": building_id})


func get_interior(building_id: int, gen_version: int = -1) -> Dictionary:
	## Fetch the authoritative interior descriptor (immutable geometry) + the
	## per-fixture persistent-delta overlay. Godot materializes geometry from this;
	## it never invents rooms, fixtures, or container assignments.
	var fields := {"building_id": building_id}
	if gen_version >= 0:
		fields["gen_version"] = gen_version
	return _send("GET_INTERIOR", fields)


func use_item(kind: String) -> Dictionary:
	## Use/consume an item; authoritative survival state changes.
	return _send("USE_ITEM", {"kind": kind})


func inspect_inventory() -> Dictionary:
	## Read the authoritative player inventory + survival needs.
	return _send("INSPECT_INVENTORY", {})


func pause() -> Dictionary:
	return _send("PAUSE", {})


func resume() -> Dictionary:
	return _send("RESUME", {})


func snapshot() -> Dictionary:
	var r := _send("SNAPSHOT", {})
	if _ok(r) and r.has("world"):
		last_world = r["world"]
	return r


func save(path: String) -> Dictionary:
	## Ask Python to persist the authoritative world to a path (Python serializes).
	var r := _send("SAVE", {"path": path})
	if _ok(r):
		last_summary = r
	return r


func load(path: String) -> Dictionary:
	## Replace the authoritative world from a saved path (Python deserializes).
	var r := _send("LOAD", {"path": path})
	if _ok(r):
		last_summary = r
	return r


# ------------------------------------------------------------------ internals
func _set_connected(v: bool) -> void:
	if _connected == v:
		return
	_connected = v
	connected_changed.emit(v)


func _ok(reply: Dictionary) -> bool:
	return reply.get("ok", false) == true


func _mean_belief_from(reply: Dictionary) -> float:
	## Authoritative outbreak intensity = mean zone belief from the live world.
	## Prefer an embedded snapshot; else fall back to a cached one.
	var world: Dictionary = reply.get("world", last_world)
	if world.is_empty():
		return 0.0
	var zones: Array = world.get("zones", [])
	if zones.is_empty():
		return 0.0
	var s := 0.0
	for z in zones:
		s += float(z.get("belief", 0.0))
	return clampf(s / zones.size(), 0.0, 1.0)


func _send(cmd: String, fields: Dictionary) -> Dictionary:
	if _peer == null:
		return {"ok": false, "error": {"code": "no_connection", "message": "not connected"}}
	_id += 1
	var msg := {"cmd": cmd, "id": _id}
	for k in fields:
		msg[k] = fields[k]
	var line := JSON.stringify(msg) + "\n"
	_peer.put_data(line.to_utf8_buffer())
	return _read_reply()


func _read_reply() -> Dictionary:
	## Block until a full newline-terminated JSON line is available.
	var buf := PackedByteArray()
	while true:
		_peer.poll()
		var status := _peer.get_status()
		if status != StreamPeerTCP.STATUS_CONNECTED:
			return {"ok": false, "error": {"code": "disconnected", "message": "peer closed"}}
		var avail := _peer.get_available_bytes()
		if avail > 0:
			var chunk := _peer.get_data(avail)
			if chunk[0] == OK:
				buf.append_array(chunk[1])
				var nl := buf.find(10)  # '\n'
				if nl >= 0:
					var line := buf.slice(0, nl)
					var text := line.get_string_from_utf8()
					var parsed = JSON.parse_string(text)
					if parsed is Dictionary:
						return parsed
					return {"ok": false, "error": {"code": "bad_reply", "message": text}}
		else:
			OS.delay_msec(1)
	# Unreachable (the loop only exits via return), but GDScript's static analyser
	# requires every code path to return a Dictionary.
	return {"ok": false, "error": {"code": "unreachable", "message": ""}}
