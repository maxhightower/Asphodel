extends Node

## Certifies the real street_world walk-in gameplay path (Package 3D): enter a
## building through its entrance, get teleported into the streamed interior cell,
## leave through the same door and return to the exterior entrance, with the
## interior unloaded — plus a repeated enter/leave cycle leak check. Runs the
## actual StreetScene against the live Python bridge.
##
##   godot4 --path godot res://tests/LiveWalkIn.tscn -- --bundle houston --player 5

var _fail := 0
var _bundle := "houston"
var _player := 5


func _check(cond: bool, label: String) -> void:
	if cond:
		print("  ok  ", label)
	else:
		_fail += 1
		printerr("  FAIL  ", label)


func _ready() -> void:
	_parse_args()
	print("== live walk-in certification (bundle=%s) ==" % _bundle)
	var dir := "res://bundles/" + _bundle
	var citizens := BundleLoader.load_citizens(dir)
	if citizens.is_empty():
		printerr("no citizens"); return _finish()
	Session.bundle_dir = dir
	Session.citizen = citizens[_player] if _player < citizens.size() else citizens[0]

	var scene: Node = load("res://StreetScene.tscn").instantiate()
	add_child(scene)
	for i in range(30):
		await get_tree().physics_frame
	_check(SimBridge.is_connected_to_sim(), "StreetScene connected to live server")
	var player = scene.get("_player")
	_check(player != null, "player spawned")
	if player == null:
		return _finish()

	# Move the player adjacent to a real building entrance.
	var bid := 0
	var gi: Dictionary = SimBridge.get_interior(bid)
	_check(gi.get("ok", false), "GET_INTERIOR for building %d" % bid)
	var desc: Dictionary = gi.get("interior", {})
	var ents: Array = desc.get("entrances", [])
	_check(ents.size() > 0, "building has an entrance")
	if ents.is_empty():
		return _finish()
	var e = ents[0]
	# Stand just OUTSIDE the entrance (opposite the inward normal) — at the wall,
	# not inside the solid exterior mesh. AABB-based reach makes this enterable.
	var outside := Vector3(float(e["x"]) - float(e["nx"]) * 2.0, 2.0,
		float(e["y"]) - float(e["ny"]) * 2.0)
	player.position = outside
	var outside_pos: Vector3 = player.position

	# ENTER via the real interaction path.
	scene._try_interact()
	await get_tree().physics_frame
	_check(int(scene.get("_inside_building")) == bid, "entered building %d" % bid)
	_check(scene.get("_active_interior") != null, "interior materialized on enter")
	# player is now in the offset interior cell, near the entrance (continuity).
	var inside_pos: Vector3 = player.position
	_check(inside_pos.x > 50000.0, "player teleported into the streamed interior cell")

	# Walk to the exit marker and LEAVE via the same door.
	var interior = scene.get("_active_interior")
	var marker = interior.get_node_or_null("ExitMarker")
	if marker != null:
		player.position = marker.global_position + Vector3(0, 1.0, 0)
	scene._try_interact()
	await get_tree().physics_frame
	_check(int(scene.get("_inside_building")) == -1, "left the building")
	_check(scene.get("_active_interior") == null, "interior unloaded on leave")
	var horiz := Vector2(player.position.x - outside_pos.x, player.position.z - outside_pos.z)
	_check(horiz.length() < 3.0,
		"returned to the exterior entrance (coordinate continuity)")

	# Repeated enter/leave cycles: no node/interior leak.
	var base_nodes := Performance.get_monitor(Performance.OBJECT_NODE_COUNT)
	for i in range(25):
		player.position = outside
		scene._try_interact()                       # enter
		await get_tree().physics_frame
		var it = scene.get("_active_interior")
		if it != null:
			var m = it.get_node_or_null("ExitMarker")
			if m != null:
				player.position = m.global_position + Vector3(0, 1.0, 0)
		scene._try_interact()                       # leave
		await get_tree().physics_frame
	# let deferred frees settle
	for i in range(5):
		await get_tree().physics_frame
	var after_nodes := Performance.get_monitor(Performance.OBJECT_NODE_COUNT)
	_check(after_nodes <= base_nodes + 5,
		"no interior/node leak over 25 enter/leave cycles (%d -> %d)" % [base_nodes, after_nodes])
	_check(scene.get("_active_interior") == null, "no interior left resident after cycles")

	SimBridge.disconnect_from_sim()
	_finish()


func _parse_args() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--player" and i + 1 < args.size():
			_player = int(args[i + 1])


func _finish() -> void:
	print("== live walk-in cert done: %d failure(s) ==" % _fail)
	get_tree().quit(1 if _fail > 0 else 0)
