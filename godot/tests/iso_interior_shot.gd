extends Node

## Fast interior-only cutaway screenshot: enter an authoritative interior and frame
## the roofless room plan from a near-top-down isometric angle. No exterior sweep,
## so it renders quickly. WITH rendering under xvfb + software GL.
##
##   xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 godot --path godot \
##     --rendering-method gl_compatibility --rendering-driver opengl3 \
##     res://tests/IsoInteriorShot.tscn -- --bundle houston --out /tmp/shot.png

var _bundle := "houston"
var _out := "/tmp/asph_iso_interior.png"
var _zoom := 34.0
var _pitch := 58.0
var _bid := -1


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--out" and i + 1 < args.size():
			_out = args[i + 1]
		elif args[i] == "--zoom" and i + 1 < args.size():
			_zoom = float(args[i + 1])
		elif args[i] == "--pitch" and i + 1 < args.size():
			_pitch = float(args[i + 1])
		elif args[i] == "--bid" and i + 1 < args.size():
			_bid = int(args[i + 1])
	await _run()


func _run() -> void:
	Session.bundle_dir = "res://bundles/" + _bundle
	Session.citizen = _first_citizen(Session.bundle_dir)
	var scene: Node3D = preload("res://IsometricWorld.tscn").instantiate()
	add_child(scene)
	for i in range(20):
		await get_tree().physics_frame
	await get_tree().create_timer(0.4).timeout

	if not SimBridge.is_connected_to_sim():
		print("no bridge — cannot capture interior")
		return get_tree().quit(1)
	GameClock.set_paused(true)
	GameClock.hour = 13.0
	GameClock.ticked.emit(GameClock.game_day, 13.0, 0.0)

	var bid := _bid if _bid >= 0 else _find_interior(scene)
	if bid < 0:
		print("no interior found")
		return get_tree().quit(1)
	var gi_dbg: Dictionary = SimBridge.get_interior(bid)
	var d_dbg: Dictionary = gi_dbg.get("interior", {})
	print("DEBUG chosen bid=%d hull=%s entrances=%s nrooms=%d" % [bid,
		str(d_dbg.get("hull", [])), str(d_dbg.get("entrances", [])), d_dbg.get("rooms", []).size()])
	scene.enter_building_by_id(bid)
	var player: CharacterBody3D = scene.get_player()
	print("DEBUG player_right_after_enter=%s" % str(player.position))
	for i in range(6):
		await get_tree().physics_frame

	var interior: Node3D = scene.active_interior()
	# Dump the real node positions so we frame on actual geometry.
	var floor_node: Node3D = interior.get_node_or_null("Floor")
	var fxn: Node3D = interior.get_node_or_null("Fixtures")
	print("DEBUG interior_root=%s floor=%s" % [str(interior.global_position),
		str(floor_node.global_position if floor_node != null else Vector3.ZERO)])
	if fxn != null:
		for f in fxn.get_children():
			print("DEBUG fixture %s @ %s" % [f.name, str(f.global_position)])
	# For a clear layout+furniture evidence shot show the FULL plan (keep every wall,
	# only the ceiling is off) and centre the camera on the FLOOR (the geometric
	# centre of the descriptor), not the player or occupants.
	var cutaway = scene.get_cutaway()
	if cutaway != null:
		cutaway.face_threshold = 5.0
	# Target the FURNITURE cluster so fixtures read clearly. Each fixture's true world
	# position = its body's global position + the "fixture_pos" meta (the mesh offset
	# inside the body).
	var center: Vector3 = scene.interior_center_world()
	if fxn != null and fxn.get_child_count() > 0:
		# Target the furniture centroid so all fixtures fill the frame (good for a
		# small building where they cluster).
		var acc := Vector3.ZERO
		var nf := 0
		for f in fxn.get_children():
			var fp: Vector3 = f.get_meta("fixture_pos", Vector3.ZERO)
			var wp: Vector3 = f.global_position + fp
			print("DEBUG fixture %s world=%s" % [f.name, str(wp)])
			acc += wp
			nf += 1
		if nf > 0:
			center = acc / float(nf)
	var anchor := Node3D.new()
	anchor.position = center
	add_child(anchor)
	player.teleport(Vector3(center.x, center.y + 0.5, center.z))
	var cam = scene.get_camera()
	cam.pitch_deg = _pitch
	cam.boom_length = 300.0
	cam.set_zoom(_zoom)
	cam.set_target(anchor)
	cam.settle()
	for i in range(3):
		await get_tree().physics_frame
	cam.settle()
	print("DEBUG cam_pos=%s cam_focus=%s" % [str(cam.global_position), str(cam.get_focus())])
	await get_tree().create_timer(0.5).timeout

	var img := get_viewport().get_texture().get_image()
	img.save_png(_out)
	print("INTERIOR SHOT saved: %s (%dx%d)" % [_out, img.get_size().x, img.get_size().y])
	print("hidden_walls=%d fixtures=%s" % [
		(cutaway.hidden_wall_count() if cutaway != null else -1),
		str(scene.active_interior().get_node_or_null("Fixtures").get_child_count()
			if scene.active_interior() != null and scene.active_interior().get_node_or_null("Fixtures") != null else 0)])
	get_tree().quit(0)


func _find_interior(scene: Node3D) -> int:
	for probe in range(min(scene.building_count(), 60)):
		var gi: Dictionary = SimBridge.get_interior(probe)
		if gi.get("ok", false) and gi.get("interior", {}).get("rooms", []).size() >= 2:
			return probe
	# fall back to any interior with rooms
	for probe in range(min(scene.building_count(), 60)):
		var gi: Dictionary = SimBridge.get_interior(probe)
		if gi.get("ok", false) and gi.get("interior", {}).get("rooms", []).size() > 0:
			return probe
	return -1


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
			c["citizen_id"] = i
			return c
	if arr.size() > 0:
		arr[0]["citizen_id"] = 0
		return arr[0]
	return {}
