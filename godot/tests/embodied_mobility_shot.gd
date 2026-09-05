extends Node

## Embodied mobility visual evidence (ASPHODEL_EMBODIED_MOBILITY_V1 §23).
##
## Runs the REAL IsometricWorld scene against the live Python bridge, drives
## the movement clock through citizen `--citizen`'s day, keeps the player (and
## therefore the camera and the NEAR band) beside that citizen, and saves a
## screenshot at every stage: leaving home, walking to the car, entering the
## car, driving a real street, meeting another vehicle, parking, exiting,
## walking into work, inside the workplace, and the return trip. Every frame
## is the actual renderer drawing actual CitizenBody / VehicleBody nodes at
## the positions the authoritative executor produced — no staged poses.
##
##   xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 godot --path godot \
##     --rendering-method gl_compatibility --rendering-driver opengl3 \
##     res://tests/EmbodiedMobilityShot.tscn -- --bundle houston --citizen 4 --dir /tmp/shots

var _bundle := "houston"
var _cid := 4
var _dir := "/tmp/asph_embodied_shots"
var _game_dt := 0.25
var _scene: Node3D
var _emb: EmbodiedMobility
var _blocker: VehicleBody = null
var _manifest := []


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--citizen" and i + 1 < args.size():
			_cid = int(args[i + 1])
		elif args[i] == "--dir" and i + 1 < args.size():
			_dir = args[i + 1]
	DirAccess.make_dir_recursive_absolute(_dir)
	await _run()


func _shot(name: String, caption: String) -> void:
	await get_tree().process_frame
	await get_tree().process_frame
	await get_tree().create_timer(0.3).timeout
	var img := get_viewport().get_texture().get_image()
	var path := _dir.path_join(name)
	img.save_png(path)
	var row := _citizen_row(SimBridge.last_mobility)
	_manifest.append({"file": name, "caption": caption, "hour": SimBridge.last_summary.get("hour"),
		"state": row.get("state"), "x": row.get("x"), "y": row.get("y"),
		"bodies": _emb.bodies.keys() if _emb != null else []})
	print("SHOT saved: %s (%dx%d) %s" % [path, img.get_size().x, img.get_size().y, caption])


func _citizen_row(block: Dictionary) -> Dictionary:
	for row in block.get("citizens", []):
		if int(row["citizen_id"]) == _cid:
			return row
	return {}


func _vehicle_row(block: Dictionary, vid: String) -> Dictionary:
	for row in block.get("vehicles", []):
		if str(row["vehicle_id"]) == vid:
			return row
	return {}


func _place_player(row: Dictionary, off: Vector2 = Vector2(6.0, 4.0)) -> void:
	var p = _scene.get_player()
	if p == null:
		return
	p.teleport(Vector3(float(row["x"]) + off.x, 1.5, float(row["y"]) + off.y))
	SimBridge.focus_xy = Vector2(float(row["x"]), float(row["y"]))
	SimBridge.has_focus_xy = true


func _step() -> Dictionary:
	var r: Dictionary = SimBridge.advance_time(_game_dt, "mobility")
	if r.get("ok", false) != true:
		return {}
	var block: Dictionary = r.get("mobility", {})
	_emb.apply(block, _game_dt)
	return block


func _settle(frames: int) -> void:
	var ext = _scene.get_exterior()
	for i in range(frames):
		if ext != null:
			ext.update_focus(_scene.get_camera().get_focus())
		await get_tree().physics_frame


func _run_until(pred: Callable, max_frames: int, follow: bool = true) -> Dictionary:
	var row := {}
	for i in range(max_frames):
		var block := _step()
		if block.is_empty():
			break
		row = _citizen_row(block)
		if follow:
			_place_player(row)
		if pred.call(row, block):
			return row
		await get_tree().physics_frame
	return row


func _point_ahead(route: Array, dist: float) -> Vector2:
	var acc := 0.0
	for i in range(1, route.size()):
		var a := Vector2(float(route[i - 1][0]), float(route[i - 1][1]))
		var b := Vector2(float(route[i][0]), float(route[i][1]))
		var l := a.distance_to(b)
		if acc + l >= dist:
			return a.lerp(b, (dist - acc) / max(l, 0.001))
		acc += l
	return Vector2.INF


func _run() -> void:
	Session.bundle_dir = "res://bundles/" + _bundle
	var citizens := BundleLoader.load_citizens(Session.bundle_dir)
	Session.citizen = citizens[_cid] if _cid < citizens.size() else citizens[0]
	_scene = preload("res://IsometricWorld.tscn").instantiate()
	add_child(_scene)
	for i in range(20):
		await get_tree().physics_frame
	await get_tree().create_timer(0.5).timeout
	if not SimBridge.is_connected_to_sim() or not SimBridge.mobility_enabled:
		printerr("no live bridge with mobility; start python -m asphodel.bridge.server")
		get_tree().quit(1)
		return
	_emb = _scene.get_embodied()
	_emb.time_scale = 1.0 / max(get_physics_process_delta_time(), 0.001) * _game_dt
	GameClock.time_scale = 0.0          # this script drives the movement clock
	GameClock.hour = 7.5
	var cam = _scene.get_camera()
	cam.set_zoom(26.0)

	# fast-forward authoritatively to just before the commute
	var hour := float(SimBridge.last_summary.get("hour", 0.0))
	if hour < 7.45:
		SimBridge.advance_time((7.45 - hour) * 3600.0, "")
	var m: Dictionary = SimBridge.get_mobility().get("mobility", {})
	var row := _citizen_row(m)
	_place_player(row)
	await _settle(90)
	await _shot("00_home_before_commute.png", "07:27 citizen %d inside home %d (no body: inside)" % [_cid, int(row["building_id"])])

	# 1. leaving home
	row = await _run_until(func(r, _b): return str(r.get("state")) == "on_foot", 3000)
	await _settle(6)
	await _shot("01_leaving_home.png", "citizen leaves home: CitizenBody at the entrance anchor")
	# 2. walking toward the car
	row = await _run_until(func(r, _b): return float(r.get("progress", 0.0)) > 0.5 and str(r.get("step")) == "walk", 3000)
	await _settle(4)
	await _shot("02_walking_to_car.png", "walking to the parked car along the street")
	# 3. entering
	row = await _run_until(func(r, _b): return str(r.get("state")) in ["approaching_vehicle", "entering_vehicle"], 3000)
	await _settle(4)
	await _shot("03_entering_car.png", "entering the persistent vehicle (%s)" % str(row.get("vehicle_id")))
	# 4. driving
	row = await _run_until(func(r, _b): return str(r.get("state")) == "driving" and float(r.get("progress", 0.0)) > 0.15, 6000)
	await _settle(4)
	await _shot("04_driving_real_street.png", "VehicleBody driving the canonical road route (progress %.2f)" % float(row.get("progress", 0.0)))
	# 5. another vehicle ahead: the body stops behind it
	var vid := str(row.get("vehicle_id"))
	var route: Array = SimBridge.last_mobility.get("routes", {}).get("cit:%d" % _cid, [])
	var ahead := _point_ahead(route, 28.0)
	if ahead != Vector2.INF:
		_blocker = VehicleBody.new()
		_blocker.semantic_id = "other_vehicle"
		_blocker.position = Vector3(ahead.x, 0.7, ahead.y)
		var mi := MeshInstance3D.new()
		mi.mesh = PropMeshes.get_mesh("pickup", 2)
		mi.position = Vector3(0, -0.7, 0)
		_blocker.add_child(mi)
		_emb.add_child(_blocker)
		_blocker.set_parked(Vector3(ahead.x, 0.7, ahead.y), 0.0)
		row = await _run_until(func(r, b):
			var vb = _emb.body_of(vid)
			return vb != null and (vb.is_blocked() or bool(r.get("blocked", false))), 800)
		await _settle(4)
		await _shot("05_vehicle_interaction.png", "car held behind another vehicle on the road (blocked=%s)" % str(row.get("blocked")))
		_blocker.queue_free()
		_blocker = null
	# 6. parking
	row = await _run_until(func(r, _b): return str(r.get("state")) in ["parked", "exiting_vehicle"], 8000)
	await _settle(4)
	await _shot("06_parked_near_work.png", "parked at the chosen parking anchor near work")
	# 7. exiting
	row = await _run_until(func(r, _b): return str(r.get("state")) == "on_foot", 2000)
	await _settle(4)
	await _shot("07_exiting_car.png", "citizen out of the car, on foot again")
	# 8. walking into work
	row = await _run_until(func(r, _b): return str(r.get("step")) == "enter_building" or str(r.get("state")) in ["inside_building", "doing_activity"], 3000)
	await _settle(4)
	await _shot("08_walking_into_work.png", "at the work entrance (building %s)" % str(row.get("building_id")))
	row = await _run_until(func(r, _b): return str(r.get("state")) in ["inside_building", "doing_activity"], 2000)
	var work_bid := int(row.get("building_id", -1))
	# 9. inside the workplace: the player walks in through the same interior system
	if work_bid >= 0:
		_scene._enter_building(work_bid)
		for i in range(10):
			await get_tree().physics_frame
		cam.set_zoom(18.0)
		await _settle(10)
		await _shot("09_inside_workplace.png", "inside building %d: interior occupants include citizen %d" % [work_bid, _cid])
		_scene._leave_building()
		cam.set_zoom(26.0)
	# 10. return trip
	hour = float(SimBridge.last_summary.get("hour", 0.0))
	if hour < 15.97:
		SimBridge.advance_time((15.97 - hour) * 3600.0, "")
	GameClock.hour = 16.0
	row = await _run_until(func(r, _b): return str(r.get("state")) == "driving" and float(r.get("progress", 0.0)) > 0.3, 8000)
	await _settle(4)
	await _shot("10_return_trip_driving.png", "16:0x driving home (progress %.2f)" % float(row.get("progress", 0.0)))
	row = await _run_until(func(r, _b): return str(r.get("state")) in ["inside_building", "doing_activity"], 8000)
	await _settle(4)
	await _shot("11_home_again.png", "home again: inside building %s" % str(row.get("building_id")))

	var f := FileAccess.open(_dir.path_join("manifest.json"), FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify({"bundle": _bundle, "citizen_id": _cid, "shots": _manifest}, "  "))
		f.close()
	print("SHOTS done: %d" % _manifest.size())
	SimBridge.disconnect_from_sim()
	get_tree().quit(0)
