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

const PROTOCOL_VERSION := 9   # v9: + GET_GROUPS / GROUP_QUERY (survivor groups); v8 dialogue; v7 cognition

var _peer: StreamPeerTCP = null
var _id := 0
var _connected := false
var last_summary: Dictionary = {}
var last_hello: Dictionary = {}   # the HELLO reply (server/sim_sha/protocol/save_version)

# The most recent authoritative snapshot (World.snapshot()), or {} if none.
var last_world: Dictionary = {}

# --- Embodied mobility (v4) --------------------------------------------------
# Whether the started world executes citizen itineraries (START_WORLD reply
# `mobility`). When true the GameClock drives ADVANCE_TIME (continuous game
# seconds) instead of tick-granular ADVANCE, and EmbodiedMobility instantiates
# CitizenBody/VehicleBody for the NEAR band around `focus_xy`.
var mobility_enabled := false
var focus_xy := Vector2.ZERO          # the player's ground position (sim frame: x, z)
var has_focus_xy := false
# The most recent movement block (World.mobility_snapshot()), or {} if none.
var last_mobility: Dictionary = {}
# --- Outbreak (v5) ---------------------------------------------------------------
var outbreak_enabled := false
var last_outbreak: Dictionary = {}
# --- smart objects / work (v6) ---------------------------------------------------
# Whether the started world runs the WorkRuntime (START_WORLD reply
# `work_enabled`; `work: false` opts out). When true, mobility citizen rows carry
# a `work` block (role/workplace_id/task/phase/object_id/room_id/zone/carrying)
# and GET_ROOMS/GET_WORK describe the building's rooms, smart objects and events.
var work_enabled := false
var last_work: Dictionary = {}
var last_rooms: Dictionary = {}
# --- npc cognition / social memory (v7) ------------------------------------------
# Whether the started world runs the CognitionRuntime (START_WORLD reply
# `cognition_enabled`; `cognition: false` opts out). When true, GET_COGNITION
# reports the perception/memory/social event log and GET_CITIZEN_CONTEXT the
# structured context of one citizen.
var cognition_enabled := false
var last_cognition: Dictionary = {}
var last_context: Dictionary = {}
# --- npc dialogue (v8) -----------------------------------------------------------
# Whether the started world runs the DialogueRuntime (START_WORLD reply
# `dialogue_enabled`; `dialogue: false` opts out). When true, TALK drives a
# player<->NPC conversation and GET_DIALOGUE reports every conversation, speech
# act and request the authority ran. Every line displayed comes from here.
var dialogue_enabled := false
var last_dialogue: Dictionary = {}

# --- survivor groups (v9) --------------------------------------------------------
# Whether the started world runs the GroupRuntime (START_WORLD / LOAD reply
# `groups_enabled`; `groups: false` opts out). When true, GET_GROUPS reports the
# roster of survivor groups (membership, shelter, roles, shared record, event
# delta) and GROUP_QUERY answers a bounded player question (membership / where /
# a grounded ask-to-join). Every group fact rendered comes from here.
var groups_enabled := false
var last_groups: Dictionary = {}


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
	last_hello = reply
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
		mobility_enabled = bool(r.get("mobility_enabled", false))
		outbreak_enabled = bool(r.get("outbreak_enabled", false))
		work_enabled = bool(r.get("work_enabled", false))
		cognition_enabled = bool(r.get("cognition_enabled", false))
		dialogue_enabled = bool(r.get("dialogue_enabled", false))
		groups_enabled = bool(r.get("groups_enabled", false))
		world_started.emit(r)
	return r


func set_focus(zones: Array, xy = null) -> Dictionary:
	var fields := {"zones": zones}
	if xy != null:
		fields["xy"] = [float(xy.x), float(xy.y)]
	elif has_focus_xy:
		fields["xy"] = [focus_xy.x, focus_xy.y]
	return _send("SET_FOCUS", fields)


# ---------------------------------------------------- embodied mobility (v4)
func advance_time(seconds: float, want: String = "mobility") -> Dictionary:
	## Advance the continuous movement clock by `seconds` of GAME time. The
	## server auto-runs the epidemic tick when the sub-tick clock crosses the
	## tick length (bit-identical to ADVANCE). `want` = "mobility" (movement
	## block), "world" (full snapshot) or "" (summary only).
	var fields := {"seconds": seconds}
	if has_focus_xy:
		fields["focus_xy"] = [focus_xy.x, focus_xy.y]
	if want == "mobility":
		fields["snapshot"] = "mobility"
	elif want == "world":
		fields["snapshot"] = true
	var r := _send("ADVANCE_TIME", fields)
	if _ok(r):
		last_summary = r
		if r.has("mobility") and r["mobility"] != null:
			last_mobility = r["mobility"]
		if r.has("world"):
			last_world = r["world"]
			if r["world"].has("mobility"):
				last_mobility = r["world"]["mobility"]
	return r


func mobility_report(bodies: Array, dt: float) -> Dictionary:
	## NEAR bodies report where physics actually put them (the physical result
	## is the authority for NEAR progress; it can hold a trip back, never push it).
	## bodies: [{"id": "cit:4", "x": .., "z": .., "blocked": bool}, ...]
	return _send("MOBILITY_REPORT", {"bodies": bodies, "dt": dt})


# ------------------------------------------------------------ outbreak (v5)
func seed_outbreak(pathogen: String = "classic_zombie", citizen_id: int = -1) -> Dictionary:
	## Enable the per-citizen outbreak and seed an index case (citizen_id < 0 =
	## the data-driven choice). Python decides everything; Godot only embodies.
	var fields := {"pathogen": pathogen}
	if citizen_id >= 0:
		fields["citizen_id"] = citizen_id
	var r := _send("SEED_OUTBREAK", fields)
	if _ok(r):
		outbreak_enabled = true
		if r.has("outbreak") and r["outbreak"] != null:
			last_outbreak = r["outbreak"]
	return r


func get_outbreak(since_seq: int = 0) -> Dictionary:
	var r := _send("GET_OUTBREAK", {"since_seq": since_seq})
	if _ok(r) and r.has("outbreak") and r["outbreak"] != null:
		last_outbreak = r["outbreak"]
	return r


# ------------------------------------------------- smart objects / work (v6)
func get_work(since_seq: int = 0) -> Dictionary:
	## Live work state: sessions, reservations, queues and the event log since
	## `since_seq` (EMPLOYED, CLOCK_IN, TASK_START, MOVE_TO_OBJECT, RESERVED,
	## USE_START/USE_END, SERVED, STATE_CHANGE, CLOCK_OUT, ...). Read-only truth:
	## Godot never invents a session, a reservation or an event.
	var r := _send("GET_WORK", {"since_seq": since_seq})
	if _ok(r) and r.has("work") and r["work"] != null:
		last_work = r["work"]
	return r


func get_rooms(building_id: int) -> Dictionary:
	## The rooms (kind + zone + AABB + doors), smart objects (stable
	## "so:<building>:<k>" ids, live state, holders, queue), entrance, occupants
	## by room and workplace status of one building. Interior coordinates are
	## WORLD metres — a staged interior adds IsometricWorld.interior_offset().
	var r := _send("GET_ROOMS", {"building_id": building_id})
	if _ok(r):
		last_rooms = r
	return r


func set_object_state(object_id: String, key: String, value) -> Dictionary:
	## Authoritative external change to one smart object (e.g. key "working"
	## value false breaks a station: Python evicts its holders and they re-select).
	## Godot asks; Python decides and reports the consequences.
	return _send("SET_OBJECT_STATE", {"object_id": object_id, "key": key, "value": value})


# ------------------------------------------------------- npc cognition (v7)
func get_cognition(since_seq: int = 0) -> Dictionary:
	## Live cognition state: the event log since `since_seq` (PERCEIVED,
	## WARNING_SHARED/RECEIVED, HELP_DECIDED/STARTED/COMPLETED, RECIPROCATED,
	## AVOID_ROOM_DECIDED, AVOID_DECIDED, AVOID_ENDED, SOCIAL_ACTION, ...), the
	## per-kind counts, who is avoiding what, and the memory/relationship totals.
	## Read-only truth: Godot never invents a memory, a belief or a decision.
	var r := _send("GET_COGNITION", {"since_seq": since_seq})
	if _ok(r) and r.has("cognition") and r["cognition"] != null:
		last_cognition = r["cognition"]
	return r


func get_citizen_context(citizen_id: int) -> Dictionary:
	## The structured context of one citizen: location, task, goal, needs,
	## health, personality, salient memories (+ n_memories), people nearby,
	## relationships, beliefs, perceived danger, what it is avoiding and the
	## recent social events it took part in. The authority's own row — the gate
	## and the dialogue layer read it, neither of them writes it.
	var r := _send("GET_CITIZEN_CONTEXT", {"citizen_id": citizen_id})
	if _ok(r) and r.has("context") and r["context"] != null:
		last_context = r["context"]
	return r


# --------------------------------------------------- npc dialogue (v8)
func talk(citizen_id: int, act: String, args: Dictionary = {}, player_citizen: int = -1) -> Dictionary:
	## The player speaks to one NPC. `act` is one of the authority's bounded
	## player acts (GREET, ASK_FACT, ASK_LOCATION, ASK_PERSON, ASK_SAFETY,
	## ASK_FOR_HELP, THANK, END_CONVERSATION) and `args` its structured
	## arguments (building_id / room_id / subject / citizen_id / event_ref /
	## kind / object_id). The reply carries the authority's own rendered lines
	## (`acts`, `lines`, `transcript`), the bounded `options`, the relationship
	## `warmth` — or ok:false with a `reason` when the NPC is unavailable or not
	## co-present. Godot composes NO dialogue: it displays these lines verbatim.
	var f := {"citizen_id": citizen_id, "act": act, "args": args}
	if player_citizen >= 0:
		f["player_citizen"] = player_citizen
	return _send("TALK", f)


func get_dialogue(since_seq: int = 0) -> Dictionary:
	## Live conversation state: active conversations, open requests and the
	## event log since `since_seq` (CONVERSATION_STARTED/ENDED/INTERRUPTED,
	## SPEECH_ACT, QUESTION_ASKED, ANSWERED, ANSWER_UNKNOWN, FACT_SHARED/
	## RECEIVED, REQUEST_MADE/ACCEPTED/REFUSED/COMPLETED/FAILED, GROUNDING_*).
	var r := _send("GET_DIALOGUE", {"since_seq": since_seq})
	if _ok(r) and r.has("dialogue") and r["dialogue"] != null:
		last_dialogue = r["dialogue"]
	return r


func get_groups_snapshot(since_seq: int = 0) -> Dictionary:
	## Live survivor-group state (v9): the roster of groups (membership, shelter,
	## roles, coordinator, shared record) and the event delta since `since_seq`
	## (GROUP_FORMED, SHELTER_SELECTED, ROLE_PROPOSED/ACCEPTED, SUPPLY_*,
	## GROUP_WARNING, MEMBER_LEFT, ...). The authority owns every fact here.
	var r := _send("GET_GROUPS", {"since_seq": since_seq})
	if _ok(r) and r.has("groups") and r["groups"] != null:
		last_groups = r["groups"]
	return r


func group_query(op: String, citizen_id: int, player_citizen: int = -1) -> Dictionary:
	## A bounded player question into the group layer (v9). `op` is one of:
	##   membership  -> {in_group, role}         does this citizen belong to a group?
	##   where       -> {group: {shelter, ...}}  where does its group shelter?
	##   ask_to_join -> {result: {ok, accept, reason, aggregate}}  a grounded admission
	## No free text; the reply is authoritative (the same decision NPCs use).
	var fields := {"op": op, "citizen_id": citizen_id}
	if player_citizen >= 0:
		fields["player_citizen"] = player_citizen
	return _send("GROUP_QUERY", fields)


func get_mobility(routes: bool = true) -> Dictionary:
	var r := _send("GET_MOBILITY", {"routes": routes})
	if _ok(r) and r.has("mobility") and r["mobility"] != null:
		last_mobility = r["mobility"]
	return r


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
		if r["world"].has("mobility"):
			last_mobility = r["world"]["mobility"]
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
		mobility_enabled = bool(r.get("mobility_enabled", mobility_enabled))
		outbreak_enabled = bool(r.get("outbreak_enabled", outbreak_enabled))
		work_enabled = bool(r.get("work_enabled", work_enabled))
		cognition_enabled = bool(r.get("cognition_enabled", cognition_enabled))
		dialogue_enabled = bool(r.get("dialogue_enabled", dialogue_enabled))
		groups_enabled = bool(r.get("groups_enabled", groups_enabled))
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
