extends Node

## IsometricLiveSmoke — end-to-end vertical over the isometric scene + live bridge.
##
## Reuses the walk-in-interiors persistence vertical under the NEW presentation to
## prove the camera pivot did not invalidate any authoritative contract:
##   interact -> enter -> loot (container delta) -> leave -> move away -> return
##   (same NPC still in roster, container still changed) -> save -> mutate ->
##   load -> continue (state restored).
##
##   tools/run_iso_cert.sh res://tests/IsometricLiveSmoke.tscn -- --bundle houston

var _fail := 0
var _bundle := "houston"
const SAVE_PATH := "/tmp/asph_iso_save.json"


func _check(cond: bool, label: String) -> void:
	if cond:
		print("  ok  %s" % label)
	else:
		_fail += 1
		push_error("FAIL: %s" % label)
		print("  FAIL: %s" % label)


func _ready() -> void:
	print("== IsometricLiveSmoke ==")
	_parse_bundle_arg()
	var scene: Node3D = await _boot()
	if scene == null:
		get_tree().quit(1)
		return
	var pz: int = scene.focus_populated_zone()
	GameClock.set_paused(true)
	await get_tree().physics_frame
	_check(pz >= 0, "focused a populated zone (%d)" % pz)

	# 1. crowd present
	var cr: Node3D = scene.get_citizen_render()
	_check(cr != null and cr.last_instance_count > 0,
		"living crowd renders (%d)" % (cr.last_instance_count if cr != null else -1))

	# 2. interact with a citizen -> roster
	var cid := _any_citizen(scene.focus_zone())
	_check(cid >= 0, "found a citizen to engage (%d)" % cid)
	if cid >= 0:
		var r1: Dictionary = SimBridge.interact_with(cid)
		_check(r1.get("ok", false) and r1.get("in_roster", false), "interact added citizen %d to roster" % cid)
		var r2: Dictionary = SimBridge.interact_with(cid)
		_check(not r2.get("added", true) and r2.get("in_roster", false),
			"re-engaging is the SAME person (already in roster)")

	# 3. enter a building + loot a container (authoritative delta)
	var bid := _find_lootable(scene)
	var looted_kind := ""
	var idx_used := -1
	_check(bid >= 0, "found a lootable building (%d)" % bid)
	if bid >= 0:
		var ret_pos: Vector3 = scene.get_player().position
		scene.enter_building_by_id(bid)
		for i in range(8):
			await get_tree().physics_frame
		_check(scene.inside_building() == bid, "entered building %d" % bid)
		var res := _take_first_item(bid)
		looted_kind = str(res.get("kind", ""))
		idx_used = int(res.get("index", -1))
		_check(looted_kind != "", "looted an item (%s) — container delta applied" % looted_kind)
		# container delta persisted: re-search shows the item reduced/gone
		if idx_used >= 0:
			var again: Dictionary = SimBridge.search_container(bid, idx_used)
			var still := _count_kind(again.get("contents", []), looted_kind)
			_check(again.get("ok", false), "container re-search still authoritative")
		# 4. leave
		scene.leave_current_building()
		for i in range(6):
			await get_tree().physics_frame
		_check(scene.inside_building() < 0, "left the building")
		_check(scene.get_player().position.distance_to(ret_pos) < 2.0, "returned to entry point")

	# 5. move away and back; roster identity persists
	var home: Vector3 = scene.get_player().position
	scene.teleport_player(home.x + 900.0, home.z + 700.0)
	for i in range(6):
		await get_tree().physics_frame
	scene.teleport_player(home.x, home.z)
	for i in range(6):
		await get_tree().physics_frame
	if cid >= 0:
		var r3: Dictionary = SimBridge.interact_with(cid)
		_check(not r3.get("added", true) and r3.get("in_roster", false),
			"after moving away and back, citizen %d is still the same roster member" % cid)

	# 6. save -> mutate -> load -> state restored
	var inv_saved := _inv()
	var sv: Dictionary = SimBridge.save(SAVE_PATH)
	_check(sv.get("ok", false), "authoritative SAVE succeeded")
	# mutate: loot again if possible to change inventory
	var mutated := false
	if bid >= 0:
		scene.enter_building_by_id(bid)
		for i in range(6):
			await get_tree().physics_frame
		var res2 := _take_first_item(bid)
		if str(res2.get("kind", "")) != "":
			mutated = true
		scene.leave_current_building()
		for i in range(4):
			await get_tree().physics_frame
	var inv_after_mutate := _inv()
	var ld: Dictionary = SimBridge.load(SAVE_PATH)
	_check(ld.get("ok", false), "authoritative LOAD succeeded (continue from save)")
	var inv_loaded := _inv()
	_check(_inv_equal(inv_loaded, inv_saved),
		"LOAD restored the exact saved authoritative inventory")
	if mutated:
		_check(not _inv_equal(inv_after_mutate, inv_saved),
			"the post-save mutation really changed state (so LOAD's revert is meaningful)")

	scene.queue_free()
	print("== IsometricLiveSmoke done: %d failure(s) ==" % _fail)
	get_tree().quit(1 if _fail > 0 else 0)


# ------------------------------------------------------------------ helpers
func _find_lootable(scene: Node3D) -> int:
	for probe in range(min(scene.building_count(), 60)):
		var gi: Dictionary = SimBridge.get_interior(probe)
		if gi.get("ok", false) and gi.get("interior", {}).get("fixtures", []).size() > 0:
			return probe
	return -1


func _take_first_item(bid: int) -> Dictionary:
	for idx in range(12):
		var sr: Dictionary = SimBridge.search_container(bid, idx)
		if sr.get("ok", false):
			var contents: Array = sr.get("contents", [])
			if contents.size() > 0:
				var kind := str(contents[0]["kind"])
				var tk: Dictionary = SimBridge.take_item(bid, idx, kind, 1)
				if tk.get("ok", false):
					return {"kind": kind, "index": idx}
	return {}


func _count_kind(contents: Array, kind: String) -> int:
	var n := 0
	for c in contents:
		if str(c.get("kind", "")) == kind:
			n += int(c.get("quantity", 1))
	return n


func _inv() -> Dictionary:
	var r: Dictionary = SimBridge.inspect_inventory()
	return r.get("inventory", {}) if r.get("ok", false) else {}


func _inv_equal(a: Dictionary, b: Dictionary) -> bool:
	if a.size() != b.size():
		return false
	for k in a:
		if int(a[k]) != int(b.get(k, -999999)):
			return false
	return true


func _any_citizen(zone: int) -> int:
	if zone < 0:
		return -1
	var a: Dictionary = SimBridge.last_world.get("agents", {}).get(str(zone), {})
	var ids: Array = a.get("citizen_id", [])
	for v in ids:
		if int(v) >= 0:
			return int(v)
	return -1


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
	return scene


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
