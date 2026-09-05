extends Node

## Work visual evidence (ASPHODEL_SMART_OBJECTS_WORK_V1 §19).
##
## Runs the REAL IsometricWorld scene against the live Python bridge and saves a
## frame at each stage of one worker's shift: arriving at the workplace, walking
## to a station, using it, a service interaction, a task switch, contention when
## the station is broken through SET_OBJECT_STATE, the body recreated after LOD
## promotion, the end of the shift and the walk out. Interior frames are taken
## with the player INSIDE the staged interior (the cutaway camera), and every
## worker in the room is a CitizenBody driven from its authoritative interior
## position — nothing here is staged or posed.
##
## A caption never claims a state the window did not reach: `_reached` is false
## unless the predicate the run was waiting for actually became true, and the
## caption is then prefixed as NOT REACHED with what the frame really shows.
##
##   xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 godot --path godot \
##     --rendering-method gl_compatibility --rendering-driver opengl3 \
##     res://tests/WorkShot.tscn -- --bundle houston --citizen 68 \
##     --building 12013 --dir docs/work/evidence

var _bundle := "houston"
var _cid := 68
var _bid := 12013
var _dir := "/tmp/asph_work_shots"
var _game_dt := 1.0
var _scene: Node3D
var _emb: EmbodiedMobility
var _manifest := []
var _seq := 0
var _events: Array = []
var _reached := true


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--citizen" and i + 1 < args.size():
			_cid = int(args[i + 1])
		elif args[i] == "--building" and i + 1 < args.size():
			_bid = int(args[i + 1])
		elif args[i] == "--dir" and i + 1 < args.size():
			_dir = args[i + 1]
	DirAccess.make_dir_recursive_absolute(_dir)
	await _run()


# ------------------------------------------------------------------ helpers
## Null-safe int: an authoritative event field can be present and null.
func _iv(v, d: int = -1) -> int:
	return d if v == null else int(v)


func _caption(text: String) -> String:
	if _reached:
		return text
	return "NOT REACHED within the captured window - frame shows the worker as it was: " + text


func _row(block: Dictionary) -> Dictionary:
	for row in block.get("citizens", []):
		if int(row["citizen_id"]) == _cid:
			return row
	return {}


func _work(row: Dictionary) -> Dictionary:
	var w = row.get("work", {})
	return w if w is Dictionary else {}


func _live_row() -> Dictionary:
	return _row(SimBridge.get_mobility(false).get("mobility", {}))


func _pull() -> Array:
	## The event log is a ring on the Python side: drain it with since_seq every
	## step or events are lost before they are read.
	var w: Dictionary = SimBridge.get_work(_seq).get("work", {})
	var mine := []
	for e in w.get("events", []):
		_seq = max(_seq, int(e.get("seq", 0)))
		if _iv(e.get("citizen_id")) == _cid or _iv(e.get("building_id")) == _bid:
			_events.append(e)
			mine.append(e)
	return mine


func _events_of(kind: String, cid: int = -1) -> Array:
	var out := []
	for e in _events:
		if str(e.get("event", "")) != kind:
			continue
		if cid >= 0 and _iv(e.get("citizen_id")) != cid:
			continue
		out.append(e)
	return out


func _step(dt: float = -1.0) -> Dictionary:
	var d := _game_dt if dt <= 0.0 else dt
	var r: Dictionary = SimBridge.advance_time(d, "mobility")
	if r.get("ok", false) != true:
		return {}
	var block: Dictionary = r.get("mobility", {})
	_emb.apply(block, d)
	_pull()
	return block


func _place_player(row: Dictionary, off: Vector2 = Vector2(6.0, 4.0)) -> void:
	var p = _scene.get_player()
	if p == null or row.is_empty():
		return
	if _scene.inside_building() == _bid and int(row.get("building_id", -1)) == _bid:
		# inside the staged interior: stand beside the worker's authoritative
		# interior position, transformed by the scene's own stage offset.
		var s: Vector3 = _scene.interior_offset() + Vector3(float(row["x"]), 0.0, float(row["y"]))
		p.teleport(s + Vector3(off.x, 1.5, off.y))
	elif _scene.inside_building() >= 0:
		# the citizen is no longer in this interior: do not drag the player out
		# of the room by teleporting to a raw exterior coordinate.
		SimBridge.focus_xy = Vector2(float(row["x"]), float(row["y"]))
		SimBridge.has_focus_xy = true
		return
	else:
		p.teleport(Vector3(float(row["x"]) + off.x, 1.5, float(row["y"]) + off.y))
	SimBridge.focus_xy = Vector2(float(row["x"]), float(row["y"]))
	SimBridge.has_focus_xy = true


func _settle(frames: int) -> void:
	var ext = _scene.get_exterior()
	for i in range(frames):
		if ext != null and _scene.inside_building() < 0:
			ext.update_focus(_scene.get_camera().get_focus())
		await get_tree().physics_frame


func _shot(name: String, caption: String) -> void:
	await get_tree().process_frame
	await get_tree().process_frame
	await get_tree().create_timer(0.3).timeout
	var img := get_viewport().get_texture().get_image()
	var path := _dir.path_join(name)
	img.save_png(path)
	var row := _live_row()
	var w := _work(row)
	var rooms: Dictionary = SimBridge.last_rooms
	_manifest.append({"file": name, "caption": caption,
		"hour": SimBridge.last_summary.get("hour"), "citizen_id": _cid, "building_id": _bid,
		"state": row.get("state"), "x": row.get("x"), "y": row.get("y"),
		"work": w, "inside_building": _scene.inside_building(),
		"interior_bodies": _emb.interior_bodies, "markers": _emb.marker_ids(),
		"workplace_status": rooms.get("status", {})})
	print("SHOT saved: %s (%dx%d) %s" % [path, img.get_size().x, img.get_size().y, caption])


func _skip(name: String, why: String) -> void:
	_manifest.append({"file": null, "caption": "%s: %s" % [name, why]})
	print("SHOT skipped: %s (%s)" % [name, why])


## Coarse advance through stretches with nothing to see; sets _reached.
func _coarse_until(pred: Callable, max_game_s: float, chunk_s: float = 60.0,
		place: bool = true) -> Dictionary:
	## `place` false keeps the player away from the followed citizen. That
	## matters outdoors: standing on a commuting citizen promotes it to the
	## physical band, and a Godot body that snags on city geometry reports back
	## and holds its trip up — which would delay the very arrival we are waiting
	## for. Indoors there is no such reconciliation, so shots follow closely.
	var t := 0.0
	var row := {}
	_reached = false
	while t < max_game_s:
		var block := _step(chunk_s)
		if block.is_empty():
			break
		t += chunk_s
		row = _row(block)
		if row.is_empty():
			await get_tree().physics_frame
			continue
		if place:
			_place_player(row)
		else:
			SimBridge.focus_xy = Vector2(float(row["x"]), float(row["y"]))
			SimBridge.has_focus_xy = true
		if pred.call(row):
			_reached = true
			return row
		if int(t / chunk_s) % 10 == 0:
			await get_tree().physics_frame
	return row


## Fine advance (one game second per physics frame) while something moves.
func _fine_until(pred: Callable, max_frames: int) -> Dictionary:
	var row := {}
	_reached = false
	for i in range(max_frames):
		var block := _step()
		if block.is_empty():
			break
		row = _row(block)
		if row.is_empty():
			await get_tree().physics_frame
			continue
		if i % 30 == 0:
			_place_player(row)
		if pred.call(row):
			_reached = true
			return row
		await get_tree().physics_frame
	return row


func _enter() -> void:
	_scene.enter_building_by_id(_bid)
	await get_tree().physics_frame
	_step(1.0)
	_emb.refresh_object_markers()
	await get_tree().physics_frame


func _leave() -> void:
	var interior = _scene.active_interior()
	if interior != null and is_instance_valid(interior):
		var marker: Node3D = interior.get_node_or_null("ExitMarker")
		if marker != null:
			_scene.get_player().teleport(marker.global_position + Vector3(0, 1.5, 0))
			await get_tree().physics_frame
	_scene.leave_current_building()
	await get_tree().physics_frame


func _station_of(row: Dictionary) -> String:
	return str(_work(row).get("object_id", ""))


# ------------------------------------------------------------------- the run
func _run() -> void:
	Session.bundle_dir = "res://bundles/" + _bundle
	var citizens := BundleLoader.load_citizens(Session.bundle_dir)
	Session.citizen = (citizens[_cid] if _cid < citizens.size() else citizens[0]).duplicate(true)
	Session.citizen["citizen_id"] = _cid if _cid < citizens.size() else 0
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
	cam.set_zoom(24.0)
	# The scene issues the one START_WORLD of this session (the bridge refuses a
	# second one), with the player embodying `--citizen` and work on by default.
	var started: Dictionary = SimBridge.last_summary
	if not (SimBridge.mobility_enabled and SimBridge.work_enabled):
		printerr("world did not start with work enabled: %s" % str(started))
		get_tree().quit(1)
		return
	_pull()
	print("SHOTS: work world started at hour %s, following citizen %d at building %d"
		% [str(started.get("hour")), _cid, _bid])

	# --- 00 arrival: the worker is inside its workplace, the player joins it ---
	# Whole game minutes while the worker is still at home, then 5 s steps once
	# it is on the street, so the frame of it arriving and walking to its first
	# station is actually captured rather than stepped over.
	var entrance_xy: Array = SimBridge.get_rooms(_bid).get("entrance", [0.0, 0.0])
	var entrance := Vector2(float(entrance_xy[0]), float(entrance_xy[1]))
	await _coarse_until(func(r):
		return r.has("x") and str(r.get("state")) == "on_foot" \
			and Vector2(float(r["x"]), float(r["y"])).distance_to(entrance) < 600.0,
		11.0 * 3600.0, 60.0, false)
	var row := await _coarse_until(func(r):
		return int(r.get("building_id", -1)) == _bid and str(r.get("state")) == "doing_activity",
		3.0 * 3600.0, 5.0, false)
	var arrived := _reached
	await _enter()
	_step(1.0)
	row = _live_row()
	_place_player(row, Vector2(5.0, 4.0))
	await _settle(30)
	await _shot("00_arrival.png", _caption(
		"citizen %d (%s) inside workplace %d at hour %s: state %s, room %s (%s) — the player is in the same staged interior, %d worker bodies driven from authoritative interior positions"
		% [_cid, str(_work(row).get("role")), _bid, str(SimBridge.last_summary.get("hour")),
			str(row.get("state")), str(_work(row).get("room_id")), str(_work(row).get("zone")),
			_emb.interior_bodies]))
	if not arrived:
		_finish()
		return

	# --- 01 walking to a station (phase to_object) ----------------------------
	if str(_work(_live_row()).get("phase", "")) != "to_object":
		row = await _coarse_until(func(r):
			return str(_work(r).get("phase", "")) == "to_object", 90.0 * 60.0, 5.0)
	else:
		row = _live_row()
		_reached = true
	_place_player(row, Vector2(4.0, 3.0))
	await _settle(6)
	await _shot("01_walk_to_station.png", _caption(
		"phase to_object: citizen %d walking across %s to %s for task %s (interior locomotion is authoritative Python; the body follows it)"
		% [_cid, str(_work(row).get("zone")), str(_work(row).get("object_id")),
			str(_work(row).get("task"))]))

	# --- 02 using the station -------------------------------------------------
	row = await _fine_until(func(r): return str(_work(r).get("phase", "")) == "using", 2400)
	_emb.refresh_object_markers()
	_place_player(row, Vector2(3.5, 2.5))
	await _settle(6)
	var oid := _station_of(row)
	var rooms: Dictionary = SimBridge.get_rooms(_bid)
	var holders := []
	for o in rooms.get("objects", []):
		if str(o["object_id"]) == oid:
			holders = o.get("holders", [])
	await _shot("02_using_station.png", _caption(
		"phase using: citizen %d at %s (task %s); GET_ROOMS holders of that object = %s; %d holder rings drawn at stations in use"
		% [_cid, oid, str(_work(row).get("task")), str(holders), _emb.marker_ids().size()]))

	# --- 03 a service interaction (a customer actually served) ----------------
	var task_before := str(_work(row).get("task", ""))
	row = await _coarse_until(func(_r):
		return not _events_of("SERVED").is_empty(), 3.0 * 3600.0, 20.0)
	var served := _events_of("SERVED")
	_place_player(row, Vector2(3.5, 2.5))
	await _settle(6)
	if not served.is_empty():
		var last_served: Dictionary = served[served.size() - 1]
		await _shot("03_service_interaction.png",
			"SERVED in workplace %d at hour %s: cashier %s served customer %s at station %s (%d served here so far; the followed worker %d is %s at %s)"
			% [_bid, str(SimBridge.last_summary.get("hour")), str(last_served.get("citizen_id")),
				str(last_served.get("customer_id")), str(last_served.get("object_id")),
				served.size(), _cid, str(_work(row).get("phase")), str(_work(row).get("object_id"))])
	else:
		var st: Dictionary = SimBridge.get_rooms(_bid).get("status", {})
		await _shot("03_service_interaction.png",
			"NOT REACHED: no SERVED event in building %d in the captured window; the frame shows worker %d at its station (phase %s, task %s) with %s customers queued in the workplace"
			% [_bid, _cid, str(_work(row).get("phase")), str(_work(row).get("task")),
				str(st.get("customers_queued"))])

	# --- 04 a task switch (the job grammar picks the next task) ---------------
	row = await _fine_until(func(r):
		var t := str(_work(r).get("task", ""))
		return t != "" and t != task_before, 3600)
	_emb.refresh_object_markers()
	_place_player(row, Vector2(4.0, 3.0))
	await _settle(6)
	if _reached:
		await _shot("04_task_switch.png",
			"task switch: citizen %d moved from task %s to task %s (object %s, phase %s) — the task order is the authority's job grammar, not the renderer's"
			% [_cid, task_before, str(_work(row).get("task")), str(_work(row).get("object_id")),
				str(_work(row).get("phase"))])
	else:
		await _shot("04_task_switch.png",
			"NOT REACHED: the job grammar kept issuing task %s to citizen %d for the whole captured hour, so no switch to a different task occurred; the frame shows it on %s, phase %s"
			% [task_before, _cid, str(_work(row).get("object_id")), str(_work(row).get("phase"))])

	# --- 05 contention: the station is broken, the worker substitutes ---------
	row = _live_row()
	var broken := _station_of(row)
	if broken != "":
		SimBridge.set_object_state(broken, "working", false)
		row = await _fine_until(func(r):
			var o := str(_work(r).get("object_id", ""))
			return (o != "" and o != broken) or str(_work(r).get("phase", "")) == "waiting", 600)
		_emb.refresh_object_markers()
		_place_player(row, Vector2(4.0, 3.0))
		await _settle(6)
		await _shot("05_contention.png", _caption(
			"station %s set working=false: citizen %d was evicted (OBJECT_UNAVAILABLE x%d) and is now on %s, phase %s — substitution is the authority's, the renderer only shows where the holder rings moved"
			% [broken, _cid, _events_of("OBJECT_UNAVAILABLE", _cid).size(),
				str(_work(row).get("object_id")), str(_work(row).get("phase"))]))
		SimBridge.set_object_state(broken, "working", true)
	else:
		_skip("05_contention.png", "the worker held no station to break at this point")

	# --- 08 LOD: 1.5 km away and back; the body is recreated ------------------
	var before := _live_row()
	await _leave()
	if before.is_empty():
		before = {"x": 0.0, "y": 0.0}
	var far := Vector2(float(before["x"]) + 1500.0, float(before["y"]))
	_scene.teleport_player(far.x, far.y)
	SimBridge.focus_xy = far
	var t := 0.0
	while t < 10.0 * 60.0:
		_step(60.0)
		t += 60.0
		SimBridge.focus_xy = far
		await get_tree().physics_frame
	var after := _live_row()
	_scene.teleport_player(float(after["x"]) + 8.0, float(after["y"]) + 8.0)
	await _enter()
	after = _live_row()
	_place_player(after, Vector2(3.5, 2.5))
	await _settle(20)
	var cb = _emb.body_of("cit:%d" % _cid)
	var want: Vector3 = _scene.interior_offset() + Vector3(float(after["x"]), 0.0, float(after["y"]))
	var jump := 0.0
	if cb != null:
		jump = Vector2(cb.global_position.x, cb.global_position.z).distance_to(Vector2(want.x, want.z))
	_reached = cb != null
	await _shot("08_after_promotion.png", _caption(
		"back after 10 game minutes with the player 1.5 km away and no body: the CitizenBody for citizen %d is recreated at the authoritative interior pose (%.2f m from it), still on object %s task %s"
		% [_cid, jump, str(_work(after).get("object_id")), str(_work(after).get("task"))]))

	# --- 06 interruption: the end of the shift --------------------------------
	row = await _coarse_until(func(r):
		return _work(r).get("phase") == null or str(r.get("state")) != "doing_activity",
		12.0 * 3600.0, 20.0)
	if int(row.get("building_id", -1)) != _bid and _scene.inside_building() >= 0:
		await _leave()
	_place_player(row, Vector2(4.0, 3.0))
	await _settle(30)
	var clocked := _events_of("CLOCK_OUT", _cid)
	var interrupted := _events_of("WORK_INTERRUPTED", _cid)
	await _shot("06_interruption.png", _caption(
		"end of the session at hour %s: state %s, phase %s; CLOCK_OUT events for citizen %d = %d %s, WORK_INTERRUPTED = %d — every hold is released back to the ledger"
		% [str(SimBridge.last_summary.get("hour")), str(row.get("state")),
			str(_work(row).get("phase")), _cid, clocked.size(),
			(str(clocked[clocked.size() - 1].get("reason")) if not clocked.is_empty() else ""),
			interrupted.size()]))

	# --- 07 leaving: the citizen walks out, existing mobility takes over ------
	if _scene.inside_building() >= 0:
		await _leave()
	row = await _coarse_until(func(r):
		return str(r.get("state")) == "on_foot" and int(r.get("building_id", -1)) < 0,
		60.0 * 60.0, 20.0)
	var outside := _reached
	# give the exterior stream and the NEAR band time to promote a real body
	var ext = _scene.get_exterior()
	var body = null
	for i in range(360):
		_step()
		row = _live_row()
		_place_player(row, Vector2(6.0, 4.0))
		if ext != null:
			ext.force_materialize(_scene.get_player().global_position)
			ext.update_focus(_scene.get_camera().get_focus())
		body = _emb.body_of("cit:%d" % _cid)
		if body != null and i > 60:
			break
		await get_tree().physics_frame
	await _settle(20)
	_reached = outside
	await _shot("07_leaving.png", _caption(
		"citizen %d outside building %d on foot at hour %s (state %s, work phase %s), exterior CitizenBody drawn: %s — the shift is over and the ordinary mobility executor owns the citizen again"
		% [_cid, _bid, str(SimBridge.last_summary.get("hour")), str(row.get("state")),
			str(_work(row).get("phase")), str(body != null)]))
	_finish()


func _finish() -> void:
	var f := FileAccess.open(_dir.path_join("manifest.json"), FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify({"bundle": _bundle, "citizen_id": _cid,
			"building_id": _bid, "shots": _manifest}, "  "))
		f.close()
	print("SHOTS done: %d" % _manifest.size())
	SimBridge.disconnect_from_sim()
	get_tree().quit(0)
