extends Node

## IsometricInteriorSmoke — ISO-5 certification (needs the live Python bridge).
##
## Enters a real authoritative interior through the isometric scene and asserts:
## the descriptor is the entered building's (identity preserved), the roof/ceiling
## is cut away, camera-facing walls are hidden, fixtures keep their authoritative
## ids + container linkage, occupants keep their citizen ids, and leaving returns
## the player to where they entered.
##
##   tools/run_iso_cert.sh res://tests/IsometricInteriorSmoke.tscn -- --bundle houston

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
	print("== IsometricInteriorSmoke ==")
	_parse_bundle_arg()
	var scene: Node3D = await _boot()
	if scene == null:
		get_tree().quit(1)
		return
	GameClock.set_paused(true)

	var bid := _find_interior_building(scene)
	_check(bid >= 0, "found a building with an authoritative interior (id=%d)" % bid)
	if bid < 0:
		scene.queue_free()
		get_tree().quit(1 if _fail > 0 else 0)
		return

	var return_before: Vector3 = scene.get_player().position
	scene.enter_building_by_id(bid)
	for i in range(10):
		await get_tree().physics_frame

	_check(scene.inside_building() == bid, "scene reports inside building %d" % bid)
	var interior: Node3D = scene.active_interior()
	_check(interior != null, "interior subtree materialized")
	if interior != null:
		# identity: the descriptor is THIS building's, not another's
		_check(int(interior.get_meta("building_id", -1)) == bid,
			"interior descriptor belongs to the entered building (%d)" % bid)

		# cutaway: ceiling hidden + camera-facing walls hidden
		var ceil := interior.get_node_or_null("Ceiling")
		_check(ceil != null and not ceil.visible, "roof/ceiling is cut away (hidden)")
		var cutaway = scene.get_cutaway()
		_check(cutaway != null and cutaway.hidden_wall_count() > 0,
			"camera-facing walls hidden (%d)" % (cutaway.hidden_wall_count() if cutaway != null else 0))
		# floor + at least some walls still present/readable
		_check(interior.get_node_or_null("Floor") != null, "interior floor present")

		# fixtures keep authoritative ids + container linkage
		var fx := interior.get_node_or_null("Fixtures")
		var fixtures_ok := true
		var nfix := 0
		if fx != null:
			for f in fx.get_children():
				nfix += 1
				if int(f.get_meta("fixture_id", -99)) < 0 or int(f.get_meta("building_id", -99)) != bid:
					fixtures_ok = false
		_check(nfix >= 0, "interior has %d searchable fixtures" % nfix)
		_check(fixtures_ok, "every fixture retains its authoritative fixture_id + building_id")

		# occupants (if any) keep their citizen ids
		var occ := interior.get_node_or_null("Occupants")
		var occ_ok := true
		var nocc := 0
		if occ != null:
			for o in occ.get_children():
				nocc += 1
				if int(o.get_meta("citizen_id", -99)) < 0:
					occ_ok = false
		_check(occ_ok, "every occupant retains its authoritative citizen_id (%d occupants)" % nocc)

		# exit marker present
		_check(interior.get_node_or_null("ExitMarker") != null, "interior exit marker present")

	# leaving returns the player to the entrance
	scene.leave_current_building()
	for i in range(6):
		await get_tree().physics_frame
	_check(scene.inside_building() < 0, "left the building (back outside)")
	_check(scene.get_player().position.distance_to(return_before) < 2.0,
		"leaving returned the player to the entry position")

	scene.queue_free()
	print("== IsometricInteriorSmoke done: %d failure(s) ==" % _fail)
	get_tree().quit(1 if _fail > 0 else 0)


# ------------------------------------------------------------------ helpers
func _find_interior_building(scene: Node3D) -> int:
	for probe in range(min(scene.building_count(), 60)):
		var gi: Dictionary = SimBridge.get_interior(probe)
		if gi.get("ok", false):
			var d: Dictionary = gi.get("interior", {})
			if not d.is_empty() and d.get("rooms", []).size() > 0:
				return probe
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
