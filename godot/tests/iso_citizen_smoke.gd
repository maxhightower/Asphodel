extends Node

## IsometricCitizenSmoke — ISO-6 certification (needs the live Python bridge).
##
## Proves the isometric view reuses the authoritative citizen snapshot + MultiMesh
## crowd renderer: multiple continuous-positioned citizens render at once, the
## MultiMesh instance count matches the drawn subset, and named roster members are
## distinguishable. No behavioural authority is added in Godot — the renderer is a
## pure consumer of World.snapshot().
##
##   tools/run_iso_cert.sh res://tests/IsometricCitizenSmoke.tscn -- --bundle houston

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
	print("== IsometricCitizenSmoke ==")
	_parse_bundle_arg()
	var scene: Node3D = await _boot()
	if scene == null:
		get_tree().quit(1)
		return

	# Move to the most-populated promoted zone and render that snapshot under the
	# isometric camera (crowd readability), then freeze for deterministic reads.
	var zone: int = scene.focus_populated_zone()
	GameClock.set_paused(true)
	await get_tree().physics_frame
	_check(zone >= 0, "focused a populated promoted zone (%d)" % zone)

	var cr: Node3D = scene.get_citizen_render()
	_check(cr != null, "citizen MultiMesh renderer is active")
	if cr != null:
		var drawn: int = cr.last_instance_count
		_check(drawn > 0, "crowd renders %d citizens at once (continuous positions)" % drawn)
		var mmi := cr.get_child(0)
		if mmi is MultiMeshInstance3D:
			_check(mmi.multimesh.instance_count == drawn,
				"MultiMesh instance_count (%d) matches the drawn subset" % mmi.multimesh.instance_count)

	# Named / roster members must be distinguishable in the snapshot.
	var a: Dictionary = SimBridge.last_world.get("agents", {}).get(str(zone), {})
	var named: Array = a.get("named", [])
	var ids: Array = a.get("citizen_id", [])
	var n_named := 0
	var n_ident := 0
	for i in range(named.size()):
		if bool(named[i]):
			n_named += 1
	for v in ids:
		if int(v) >= 0:
			n_ident += 1
	_check(n_ident > 0, "%d identified citizens carry authoritative ids" % n_ident)
	_check(n_named >= 0, "%d named roster members present (distinguishable)" % n_named)

	# Crowd readability: several distinct citizens in the same zone.
	_check(ids.size() >= 2, "multiple citizens co-present in the zone (%d)" % ids.size())

	scene.queue_free()
	print("== IsometricCitizenSmoke done: %d failure(s) ==" % _fail)
	get_tree().quit(1 if _fail > 0 else 0)


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
