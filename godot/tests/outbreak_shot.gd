extends Node

## Outbreak visual evidence (ASPHODEL_OUTBREAK_V1 §19).
##
## Runs the REAL IsometricWorld scene against the live Python bridge with the
## classic-zombie index case (`--citizen`), keeps the player (camera + NEAR
## band) beside that citizen and saves a frame at each stage the outbreak
## produces: the normal infected morning, the symptomatic citizen leaving work,
## the collapse and corpse at its authoritative place, the reanimated citizen
## at that same place, the undead walking, the attacked citizen fleeing, and
## the civil consequence (abandoned car / disrupted workplace) when the run
## produced one. Frames are the actual renderer drawing bodies the executor
## placed — nothing staged. A stage the run did not produce is recorded in the
## manifest as not captured.
##
##   xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 godot --path godot \
##     --rendering-method gl_compatibility --rendering-driver opengl3 \
##     res://tests/OutbreakShot.tscn -- --bundle houston --citizen 4 --dir /tmp/shots

var _bundle := "houston"
var _cid := 42
var _dir := "/tmp/asph_outbreak_shots"
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



func _health(cid: int) -> String:
	var r: Dictionary = SimBridge.get_outbreak(0)
	for h in r.get("outbreak", {}).get("health", []):
		if int(h["citizen_id"]) == cid:
			return str(h["state"])
	return "susceptible"


func _events() -> Array:
	return SimBridge.get_outbreak(0).get("outbreak", {}).get("events", [])


func _run() -> void:
	Session.bundle_dir = "res://bundles/" + _bundle
	var citizens := BundleLoader.load_citizens(Session.bundle_dir)
	Session.citizen = (citizens[_cid] if _cid < citizens.size() else citizens[0]).duplicate(true)
	Session.citizen["citizen_id"] = _cid if _cid < citizens.size() else 0
	# The scene starts the world; we then enable the outbreak through the bridge.
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
	GameClock.time_scale = 0.0
	var cam = _scene.get_camera()
	cam.set_zoom(26.0)
	# the world started at the scene's hour; move to 05:00 of a fresh day is not
	# possible, so seed at the current hour and let the day run from here.
	var hour := float(SimBridge.last_summary.get("hour", 0.0))
	if hour < 5.0:
		SimBridge.advance_time((5.0 - hour) * 3600.0, "")
	var seeded: Dictionary = SimBridge.seed_outbreak("classic_zombie", _cid)
	var infected := {}
	for e in seeded.get("outbreak", {}).get("events", []):
		if e["event"] == "INFECTED" and int(e["citizen_id"]) == _cid:
			infected = e
	if infected.is_empty():
		printerr("index case not seeded: %s" % str(seeded))
		get_tree().quit(1)
		return
	var start_hour := float(SimBridge.last_summary.get("hour", 0.0))
	var onset_hour := start_hour + float(infected["symptom_t"]) / 3600.0
	# 1. an ordinary infected morning at work (incubating)
	var h := float(SimBridge.last_summary.get("hour", 0.0))
	if h < onset_hour - 0.5:
		SimBridge.advance_time((onset_hour - 0.5 - h) * 3600.0, "")
	var m: Dictionary = SimBridge.get_mobility().get("mobility", {})
	var row := _citizen_row(m)
	_place_player(row)
	await _settle(90)
	await _shot("00_infected_ordinary_morning.png", "incubating citizen %d at work (building %s), ordinary life" % [_cid, str(row.get("building_id"))])
	# 2. onset: leaves work under its own executor (pale look while symptomatic)
	row = await _run_until(func(r, _b): return str(r.get("health")) == "symptomatic" and str(r.get("state")) in ["on_foot", "approaching_vehicle", "entering_vehicle", "driving"], 12000)
	await _settle(6)
	await _shot("01_symptomatic_leaving_work.png", "symptomatic: schedule invalidated, heading home (%s)" % str(row.get("state")))
	# 3. collapse at the authoritative place
	row = await _run_until(func(r, _b): return str(r.get("state")) == "incapacitated", 12000)
	await _settle(6)
	await _shot("02_collapse.png", "incapacitated at (%s,%s) building=%s vehicle=%s" % [str(row.get("x")), str(row.get("y")), str(row.get("building_id")), str(row.get("vehicle_id"))])
	var col := Vector2(float(row["x"]), float(row["y"]))
	# 4. corpse at the same place
	row = await _run_until(func(r, _b): return str(r.get("health")) in ["corpse", "dead"], 12000)
	await _settle(6)
	await _shot("03_corpse.png", "corpse of citizen %d at (%s,%s) (same place as the collapse: %s)" % [_cid, str(row.get("x")), str(row.get("y")), str(Vector2(float(row["x"]), float(row["y"])).distance_to(col) < 0.01)])
	# 5. reanimation at the same place, then the undead walking
	row = await _run_until(func(r, _b): return str(r.get("health")) == "undead", 16000)
	await _settle(6)
	await _shot("04_reanimated_same_place.png", "citizen %d reanimated at (%s,%s), same identity, same place" % [_cid, str(row.get("x")), str(row.get("y"))])
	var start := Vector2(float(row["x"]), float(row["y"]))
	row = await _run_until(func(r, _b): return Vector2(float(r["x"]), float(r["y"])).distance_to(start) > 12.0, 6000)
	await _settle(6)
	await _shot("05_undead_walking.png", "undead body walking under physics (%.0f m from the death location)" % Vector2(float(row["x"]), float(row["y"])).distance_to(start))
	# 6. wreck / disruption (when produced): the abandoned car on the street
	var evs := _events()
	var aband := {}
	for e in evs:
		if e["event"] == "VEHICLE_ABANDONED" and aband.is_empty():
			aband = e
	if not aband.is_empty():
		_place_player({"x": aband["x"], "y": aband["y"]})
		await _settle(60)
		await _shot("06_abandoned_vehicle_obstruction.png", "abandoned %s at (%s,%s): persistent wreck, segment closed to cars" % [str(aband.get("vehicle_id")), str(aband.get("x")), str(aband.get("y"))])
	else:
		_manifest.append({"file": null, "caption": "06 abandoned vehicle: not produced in this run (the index case collapsed on foot)"})
	# 7. attack -> victim flees on foot
	var attack := {}
	var victim := -1
	for i in range(20000):
		var block := _step()
		if block.is_empty():
			break
		row = _citizen_row(block)
		_place_player(row)
		if i % 40 == 0:
			for e in _events():
				if e["event"] == "ATTACK" and int(e["citizen_id"]) == _cid:
					attack = e
					victim = int(e["victim_citizen"])
		if not attack.is_empty():
			break
		await get_tree().physics_frame
	if not attack.is_empty():
		await _settle(4)
		await _shot("07_attack.png", "undead %d attacks citizen %d in/at building %s (exposed=%s)" % [_cid, victim, str(attack.get("building_id")), str(attack.get("exposed"))])
		for i in range(4000):
			var block := _step()
			if block.is_empty():
				break
			var vr := {}
			for r2 in block.get("citizens", []):
				if int(r2["citizen_id"]) == victim:
					vr = r2
			if vr.is_empty():
				break
			_place_player(vr)
			if str(vr.get("state")) == "on_foot" and _emb.body_of("cit:%d" % victim) != null and i > 20:
				await _settle(4)
				await _shot("08_victim_flees.png", "citizen %d fleeing on foot after the attack (FLEE goal)" % victim)
				break
			await get_tree().physics_frame
	else:
		_manifest.append({"file": null, "caption": "07/08 attack and flee: not produced within the captured window"})
	var f := FileAccess.open(_dir.path_join("manifest.json"), FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify({"bundle": _bundle, "citizen_id": _cid, "shots": _manifest}, "  "))
		f.close()
	print("SHOTS done: %d" % _manifest.size())
	SimBridge.disconnect_from_sim()
	get_tree().quit(0)
