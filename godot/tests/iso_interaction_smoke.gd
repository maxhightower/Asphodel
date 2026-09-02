extends Node

## IsometricInteractionSmoke — ISO-4 certification (needs the live Python bridge).
##
## Proves the continuous-distance interaction model resolves REAL entities (by
## authoritative id, never node name) and that every action reaches the
## authoritative command over SimBridge, with illegal actions rejected by Python.
##
##   tools/run_iso_cert.sh res://tests/IsometricInteractionSmoke.tscn -- --bundle houston

var _fail := 0
var _bundle := "houston"


func _check(cond: bool, label: String) -> void:
	if cond:
		print("  ok  %s" % label)
	else:
		_fail += 1
		push_error("FAIL: %s" % label)
		print("  FAIL: %s" % label)


func _ready() -> void:
	print("== IsometricInteractionSmoke ==")
	_parse_bundle_arg()
	var scene: Node3D = await _boot()
	if scene == null:
		get_tree().quit(1)
		return
	# Move to the most-populated promoted zone so there are live identified
	# citizens to target, then freeze ADVANCE for deterministic assertions.
	var pz: int = scene.focus_populated_zone()
	_check(pz >= 0, "focused a populated zone with live citizens (%d)" % pz)
	GameClock.set_paused(true)
	await get_tree().physics_frame

	# --- continuous-distance targeting resolves a real entity -----------------
	var candidates: Array = scene.gather_candidates()
	_check(candidates.size() > 0, "interaction gathered %d continuous candidates" % candidates.size())
	# Stand the player on a candidate's continuous position so a nearest-within-reach
	# target exists (prefer the building centroid — the nearest building is always a
	# candidate there), then resolve by distance (no cursor).
	var probe_pos := Vector3.ZERO
	for c in candidates:
		if int(c.get("kind", 0)) == IsometricInteraction.BUILDING:
			probe_pos = c.get("position", Vector3.ZERO)
			break
	if probe_pos == Vector3.ZERO and candidates.size() > 0:
		probe_pos = candidates[0].get("position", Vector3.ZERO)
	scene.teleport_player(probe_pos.x, probe_pos.z)
	await get_tree().physics_frame
	var resolved: Dictionary = scene.get_interaction().resolve_target(false)
	_check(not resolved.is_empty(),
		"continuous-distance targeting resolves the nearest entity within reach (kind=%d id=%d)"
			% [int(resolved.get("kind", -1)), int(resolved.get("id", -1))])
	# every candidate carries a real authoritative id (never a node name)
	var ids_ok := true
	for c in candidates:
		if int(c.get("id", -999)) == -999:
			ids_ok = false
	_check(ids_ok, "every candidate carries an authoritative id, not a node name")

	# --- NPC interaction reaches INTERACT_WITH (roster) -----------------------
	# Pick any identified citizen anywhere in the live snapshot (INTERACT_WITH is a
	# by-id authoritative op; it does not require the citizen to be in focus).
	var cid := _any_identified_citizen()
	var citizen_target := {}
	for c in candidates:
		if int(c.get("kind", 0)) == IsometricInteraction.CITIZEN and int(c.get("id", -1)) >= 0:
			citizen_target = c
			if cid < 0:
				cid = int(c.get("id"))
			break
	_check(cid >= 0, "found an identified citizen in the live world (%d)" % cid)
	if cid >= 0:
		var r: Dictionary = SimBridge.interact_with(cid)
		_check(r.get("ok", false), "NPC interaction reaches INTERACT_WITH")
		_check(r.get("in_roster", false), "citizen %d is now in the authoritative roster" % cid)
	if not citizen_target.is_empty():
		var acted: Dictionary = scene.execute_on(citizen_target)
		_check(not acted.is_empty(), "scene.execute_on drives the citizen interaction path")

	# --- building entry reaches ENTER_BUILDING ------------------------------
	var bid := _nearest_building_with_interior(scene)
	_check(bid >= 0, "found an enterable building (id=%d)" % bid)
	if bid >= 0:
		var gi: Dictionary = SimBridge.get_interior(bid)
		_check(gi.get("ok", false), "GET_INTERIOR returns the authoritative descriptor")
		var eb: Dictionary = SimBridge.enter_building(bid)
		_check(eb.get("ok", false), "building entry reaches ENTER_BUILDING")

		# --- container action reaches SEARCH_CONTAINER / TAKE_ITEM -----------
		var insp: Dictionary = SimBridge.inspect_building(bid)
		var ncont := _container_count(insp)
		_check(insp.get("ok", false), "INSPECT_BUILDING enumerates %d containers" % ncont)
		var found_take := false
		var idx := 0
		while idx < max(ncont, 1) and idx < 12:
			var sr: Dictionary = SimBridge.search_container(bid, idx)
			if sr.get("ok", false):
				var contents: Array = sr.get("contents", [])
				if contents.size() > 0:
					var kind := str(contents[0]["kind"])
					var inv0: Dictionary = _inv()
					var tk: Dictionary = SimBridge.take_item(bid, idx, kind, 1)
					_check(tk.get("ok", false), "container action reaches TAKE_ITEM (%s)" % kind)
					var inv1: Dictionary = _inv()
					_check(int(inv1.get(kind, 0)) > int(inv0.get(kind, 0)),
						"TAKE_ITEM changed authoritative inventory (%s: %d->%d)"
							% [kind, int(inv0.get(kind, 0)), int(inv1.get(kind, 0))])
					found_take = true
					break
			idx += 1
		if not found_take:
			# still prove SEARCH_CONTAINER reaches Python even if empty
			var sr0: Dictionary = SimBridge.search_container(bid, 0)
			_check(sr0.get("ok", false), "container action reaches SEARCH_CONTAINER")

		# --- illegal action is rejected by the authority --------------------
		var bad_take: Dictionary = SimBridge.take_item(bid, 0, "unobtanium_xyzzy", 99)
		_check(not bad_take.get("ok", false), "illegal TAKE_ITEM (nonexistent kind) is rejected")
		var bad_search: Dictionary = SimBridge.search_container(bid, 999999)
		_check(not bad_search.get("ok", false), "illegal SEARCH_CONTAINER (bad index) is rejected")

		SimBridge.leave_building()

	scene.queue_free()
	print("== IsometricInteractionSmoke done: %d failure(s) ==" % _fail)
	get_tree().quit(1 if _fail > 0 else 0)


# ------------------------------------------------------------------ helpers
func _parse_bundle_arg() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]


func _boot() -> Node3D:
	Session.bundle_dir = "res://bundles/" + _bundle
	Session.citizen = _first_citizen(Session.bundle_dir)
	var scene: Node3D = preload("res://IsometricWorld.tscn").instantiate()
	add_child(scene)
	for i in range(30):
		await get_tree().physics_frame
	await get_tree().create_timer(0.3).timeout
	if not SimBridge.is_connected_to_sim():
		print("  FAIL: no live bridge — start python -m asphodel.bridge.server")
		_fail += 1
		return null
	_check(true, "connected to the live Python world")
	_check(scene.focus_zone() >= 0, "player resolved to focus zone %d" % scene.focus_zone())
	return scene


func _any_identified_citizen() -> int:
	## Scan every promoted zone in the live snapshot for an identified citizen id.
	var agents: Dictionary = SimBridge.last_world.get("agents", {})
	for zkey in agents:
		var ids: Array = agents[zkey].get("citizen_id", [])
		for v in ids:
			if int(v) >= 0:
				return int(v)
	# Fall back: advance a few authoritative ticks and re-snapshot.
	SimBridge.advance(3, true)
	agents = SimBridge.last_world.get("agents", {})
	for zkey in agents:
		var ids: Array = agents[zkey].get("citizen_id", [])
		for v in ids:
			if int(v) >= 0:
				return int(v)
	return -1


func _nearest_building_with_interior(scene: Node3D) -> int:
	# Try the buildings nearest the player until one yields an interior descriptor.
	var pp: Vector3 = scene.get_player().position
	for probe in range(scene.building_count()):
		var gi: Dictionary = SimBridge.get_interior(probe)
		if gi.get("ok", false) and not gi.get("interior", {}).is_empty():
			return probe
		if probe > 40:
			break
	return -1


func _container_count(insp: Dictionary) -> int:
	var c = insp.get("containers", null)
	if c is Array:
		return c.size()
	if c is int:
		return c
	return 0


func _inv() -> Dictionary:
	var r: Dictionary = SimBridge.inspect_inventory()
	return r.get("inventory", {}) if r.get("ok", false) else {}


func _first_citizen(bundle_dir: String) -> Dictionary:
	var path := bundle_dir.path_join("citizens.json")
	if not FileAccess.file_exists(path):
		return {}
	var f := FileAccess.open(path, FileAccess.READ)
	var data = JSON.parse_string(f.get_as_text())
	var arr: Array = []
	if data is Array:
		arr = data
	elif data is Dictionary and data.has("citizens"):
		arr = data["citizens"]
	for i in range(arr.size()):
		var c = arr[i]
		if c is Dictionary and c.has("spawn_xy") and c["spawn_xy"] != null:
			c["citizen_id"] = i   # index == authoritative citizen id (roster order)
			return c
	if arr.size() > 0:
		arr[0]["citizen_id"] = 0
		return arr[0]
	return {}
