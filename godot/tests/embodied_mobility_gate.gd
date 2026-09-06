extends Node3D

## EMBODIED MOBILITY GATE — one citizen, one car, one real day, in-engine.
##
## Runs against the LIVE Python bridge (python -m asphodel.bridge.server) with
## real Godot physics: the authoritative MobilityRuntime executes citizen
## `--citizen`'s itinerary while this scene realises the NEAR band as
## CitizenBody / VehicleBody (EmbodiedMobility) inside the streamed compiled
## city (ExteriorWorld building colliders + ground), reports the physical
## result back, and checks every stage of the day. Nothing is teleported: every
## PASS below is a body that physically got somewhere, or an authoritative
## state that changed because it did.
##
##   godot --headless --path godot res://tests/EmbodiedMobilityGate.tscn -- \
##       --bundle houston --citizen 4 --trace /tmp/godot_probe_trace.json
##
## Exit code 0 = PASS. A probe trace (per game-second rows) is written to --trace.

const ExteriorWorld = preload("res://scripts/exterior_world.gd")

var _bundle := "houston"
var _cid := 4
var _trace_path := "/tmp/asph_embodied_probe.json"
var _save_path := OS.get_user_data_dir().path_join("asph_embodied_gate_save.json")
var _port := 8765
var _game_dt := 0.25            # game seconds per physics frame (4x real time)
var _fail := 0
var _log: Array[String] = []
var _rows: Array = []
var _emb: EmbodiedMobility
var _ext: ExteriorWorld
var _blocker: VehicleBody = null
var _stats := {}


func _ok(name: String, cond: bool, detail: String = "") -> void:
	_log.append("%s  %s  %s" % ["PASS" if cond else "FAIL", name, detail])
	print(_log[-1])
	if not cond:
		_fail += 1


func _info(name: String, detail: String) -> void:
	_log.append("INFO  %s  %s" % [name, detail])
	print(_log[-1])


func _ready() -> void:
	_parse_args()
	await get_tree().physics_frame
	await _run()
	_finish()


func _parse_args() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--citizen" and i + 1 < args.size():
			_cid = int(args[i + 1])
		elif args[i] == "--trace" and i + 1 < args.size():
			_trace_path = args[i + 1]
		elif args[i] == "--save" and i + 1 < args.size():
			_save_path = args[i + 1]
		elif args[i] == "--port" and i + 1 < args.size():
			_port = int(args[i + 1])
		elif args[i] == "--game-dt" and i + 1 < args.size():
			_game_dt = float(args[i + 1])


# ------------------------------------------------------------------ world
func _floor() -> void:
	var f := StaticBody3D.new()
	f.name = "Ground"
	f.collision_layer = CollisionLayers.WORLD_STATIC
	f.collision_mask = 0
	var cs := CollisionShape3D.new()
	var b := BoxShape3D.new()
	b.size = Vector3(12000, 1, 12000)
	cs.shape = b
	f.add_child(cs)
	add_child(f)
	f.global_position = Vector3(0, -0.5, 0)


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


func _focus_on(row: Dictionary) -> void:
	SimBridge.focus_xy = Vector2(float(row["x"]), float(row["y"]))
	SimBridge.has_focus_xy = true


func _step(seconds: float) -> Dictionary:
	## One authoritative time step + body realisation. Returns the block.
	var r: Dictionary = SimBridge.advance_time(seconds, "mobility")
	if r.get("ok", false) != true:
		return {}
	var block: Dictionary = r.get("mobility", {})
	_emb.apply(block, seconds)
	return block


func _record(block: Dictionary, tag: String) -> void:
	var row := _citizen_row(block)
	if row.is_empty():
		return
	var out := {"t": float(block.get("t_s", 0.0)), "tag": tag, "state": row.get("state"),
		"step": row.get("step"), "ax": row.get("x"), "ay": row.get("y"),
		"speed": row.get("speed"), "band": row.get("band"), "blocked": row.get("blocked"),
		"building_id": row.get("building_id"), "vehicle_id": row.get("vehicle_id")}
	var cb = _emb.body_of("cit:%d" % _cid)
	if cb != null:
		out["bx"] = cb.global_position.x
		out["bz"] = cb.global_position.z
		out["by"] = cb.global_position.y
		out["b_blocked"] = cb.is_blocked()
	var vid = row.get("vehicle_id")
	if vid != null:
		var vr := _vehicle_row(block, str(vid))
		out["vax"] = vr.get("x")
		out["vay"] = vr.get("y")
		out["vspeed"] = vr.get("speed")
		var vb = _emb.body_of(str(vid))
		if vb != null:
			out["vbx"] = vb.global_position.x
			out["vbz"] = vb.global_position.z
			out["v_blocked"] = vb.is_blocked()
			out["impacts"] = vb.impacts
	_rows.append(out)


func _lag(row: Dictionary, body: Node3D) -> float:
	return Vector2(float(row["x"]), float(row["y"])).distance_to(
		Vector2(body.global_position.x, body.global_position.z))


# ------------------------------------------------------------------ phases
func _run() -> void:
	_floor()
	_emb = EmbodiedMobility.new()
	_emb.time_scale = 1.0 / max(get_physics_process_delta_time(), 0.001) * _game_dt
	add_child(_emb)
	var dir := "res://bundles/" + _bundle
	_ext = ExteriorWorld.new()
	add_child(_ext)
	var have_ext := _ext.setup(dir)
	_info("exterior", "compiled world streamed: %s" % str(have_ext))

	if not SimBridge.connect_to_sim("127.0.0.1", _port):
		_ok("bridge_connected", false, "start python -m asphodel.bridge.server first")
		return
	var started: Dictionary = SimBridge.start_world(_bundle, {"seed": 0})
	_ok("world_started_with_mobility", started.get("ok", false) and bool(started.get("mobility_enabled", false)),
		str(started.get("mobility_enabled")))
	if not SimBridge.mobility_enabled:
		return

	# --- 0. find the citizen and its car at 00:00 ---------------------------
	var m: Dictionary = SimBridge.get_mobility().get("mobility", {})
	var row := _citizen_row(m)
	_ok("citizen_registered", not row.is_empty(), "citizen %d state=%s bid=%s" % [_cid, row.get("state"), str(row.get("building_id"))])
	if row.is_empty():
		return
	var home_bid := int(row["building_id"])
	_focus_on(row)
	var hour := float(SimBridge.last_summary.get("hour", 0.0))
	# Fast-forward (authoritatively, no bodies) to just before the commute.
	var target_hour := 7.45
	if hour < target_hour:
		SimBridge.advance_time((target_hour - hour) * 3600.0, "")
	m = SimBridge.get_mobility().get("mobility", {})
	row = _citizen_row(m)
	_ok("still_home_before_commute", row.get("state") in ["doing_activity", "inside_building"] and int(row["building_id"]) == home_bid,
		"07:27 state=%s bid=%s" % [str(row.get("state")), str(row.get("building_id"))])
	_focus_on(row)
	if have_ext:
		_ext.force_materialize(Vector3(float(row["x"]), 0.0, float(row["y"])))
		for i in range(30):
			_ext.update_focus(Vector3(float(row["x"]), 0.0, float(row["y"])))
			await get_tree().process_frame

	# --- 1. leave home -> walk to the car -----------------------------------
	var saw_on_foot := false
	var npc_layer_ok := true
	var walk_body_dist := 0.0
	var walk_frames := 0
	var walk_ok_frames := 0
	var last_b := Vector3.ZERO
	var entered_car := false
	var veh_id := ""
	for i in range(4000):
		var block := _step(_game_dt)
		if block.is_empty():
			break
		row = _citizen_row(block)
		_focus_on(row)
		if have_ext:
			_ext.update_focus(Vector3(float(row["x"]), 0.0, float(row["y"])))
		_record(block, "morning_walk")
		var st: String = str(row.get("state"))
		var cb = _emb.body_of("cit:%d" % _cid)
		if st in ["on_foot", "approaching_vehicle"]:
			saw_on_foot = true
			if cb != null:
				walk_frames += 1
				if cb.collision_layer != CollisionLayers.NPC or not (cb is CitizenBody):
					npc_layer_ok = false
				if _lag(row, cb) <= cb.follow_leash + 0.5:
					walk_ok_frames += 1
				if last_b != Vector3.ZERO:
					walk_body_dist += Vector2(cb.global_position.x, cb.global_position.z).distance_to(Vector2(last_b.x, last_b.z))
				last_b = cb.global_position
		if st in ["in_vehicle", "driving"]:
			entered_car = true
			veh_id = str(row.get("vehicle_id"))
			break
		await get_tree().physics_frame
	_ok("left_home_on_foot", saw_on_foot, "citizen body appeared outside building %d" % home_bid)
	_ok("citizen_body_is_physical_npc", walk_frames > 0 and npc_layer_ok,
		"CitizenBody on CollisionLayers.NPC for %d frames" % walk_frames)
	_ok("walked_to_car_physically", walk_body_dist >= 20.0 and walk_ok_frames >= int(walk_frames * 0.9),
		"body walked %.1f m; within leash %d/%d frames" % [walk_body_dist, walk_ok_frames, walk_frames])
	_ok("entered_vehicle", entered_car, "vehicle %s" % veh_id)
	if not entered_car:
		return
	_stats["walk_m_body"] = walk_body_dist

	# --- 2. drive: physical VehicleBody follows the canonical road route -----
	var vb = _emb.body_of(veh_id)
	_ok("vehicle_body_exists_on_entry", vb != null and vb is VehicleBody,
		"VehicleBody %s layer=%d" % [veh_id, (vb.collision_layer if vb != null else -1)])
	_ok("no_citizen_body_while_in_car", _emb.body_of("cit:%d" % _cid) == null, "one body per identity")
	var drive_body_dist := 0.0
	var drive_frames := 0
	var drive_ok_frames := 0
	var last_v := Vector3.ZERO
	var max_lag := 0.0
	var parked := false
	var blocker_placed := false
	var blocker_stop_seen := false
	var auth_hold_seen := false
	var blocker_t := 0.0
	var pos_at_block := Vector2.ZERO
	var frames_since_block := 0
	var saved_mid_drive := false
	var saveload_ok := false
	var impacts := 0
	for i in range(8000):
		var block := _step(_game_dt)
		if block.is_empty():
			break
		row = _citizen_row(block)
		_focus_on(row)
		if have_ext:
			_ext.update_focus(Vector3(float(row["x"]), 0.0, float(row["y"])))
		_record(block, "drive")
		var st: String = str(row.get("state"))
		vb = _emb.body_of(veh_id)
		var vr := _vehicle_row(block, veh_id)
		if st == "driving" and vb != null:
			drive_frames += 1
			var lag := _lag(vr, vb)
			max_lag = max(max_lag, lag)
			# The authority integrates in 1 s substeps, so it jumps by up to one
			# second of travel ahead of the body; the body must close that within
			# the leash before the next jump.
			if lag <= vb.follow_leash + 1.0 + float(vr.get("speed", 0.0)):
				drive_ok_frames += 1
			if last_v != Vector3.ZERO:
				drive_body_dist += Vector2(vb.global_position.x, vb.global_position.z).distance_to(Vector2(last_v.x, last_v.z))
			last_v = vb.global_position
			impacts = vb.impacts
			# Traffic interaction: once well into the drive, park a solid car
			# 25 m ahead ON the route; the physical car must stop behind it and
			# the authority must hold (blocked report), then resume when cleared.
			var prog := float(row.get("progress", 0.0))
			if not blocker_placed and prog > 0.35 and float(vr.get("speed", 0.0)) > 6.0:
				var route: Array = block.get("routes", {}).get("cit:%d" % _cid, [])
				var ahead := _point_ahead(route, 30.0)
				if ahead != Vector2.INF:
					_blocker = VehicleBody.new()
					_blocker.semantic_id = "blocker"
					_blocker.position = Vector3(ahead.x, 0.7, ahead.y)
					var h := _heading_ahead(route, 30.0)
					add_child(_blocker)
					_blocker.set_parked(Vector3(ahead.x, 0.7, ahead.y), h)
					blocker_placed = true
					blocker_t = float(block.get("t_s", 0.0))
					pos_at_block = Vector2(float(vr["x"]), float(vr["y"]))
			if blocker_placed and _blocker != null:
				frames_since_block += 1
				if vb.is_blocked() or bool(row.get("blocked", false)):
					blocker_stop_seen = true
				# authority holds: authoritative position stays within a few
				# metres of where the body was held for >= 8 game seconds
				if frames_since_block > int(8.0 / _game_dt):
					var a := Vector2(float(vr["x"]), float(vr["y"]))
					if a.distance_to(Vector2(vb.global_position.x, vb.global_position.z)) <= vb.follow_leash + 1.0:
						auth_hold_seen = true
				if frames_since_block > int(20.0 / _game_dt):
					_blocker.queue_free()
					_blocker = null
			# save/load mid-drive: identical mobility rows after LOAD
			if not saved_mid_drive and prog > 0.6 and _blocker == null and blocker_placed:
				saved_mid_drive = true
				var before := row.duplicate(true)
				var vbefore := vr.duplicate(true)
				var sr: Dictionary = SimBridge.save(_save_path)
				var lr: Dictionary = SimBridge.load(_save_path)
				var after_block: Dictionary = SimBridge.get_mobility().get("mobility", {})
				var after := _citizen_row(after_block)
				var vafter := _vehicle_row(after_block, veh_id)
				saveload_ok = sr.get("ok", false) and lr.get("ok", false) and _rows_equal(before, after) and _rows_equal(vbefore, vafter)
				_ok("saveload_mid_drive_identical", saveload_ok,
					"citizen row equal=%s vehicle row equal=%s" % [str(_rows_equal(before, after)), str(_rows_equal(vbefore, vafter))])
		if st == "parked" or st == "exiting_vehicle" or (st == "on_foot" and drive_frames > 0):
			parked = true
			break
		await get_tree().physics_frame
	_stats["drive_m_body"] = drive_body_dist
	_stats["drive_max_lag"] = max_lag
	_stats["impacts"] = impacts
	_ok("physical_driving_followed_route", drive_frames > 0 and drive_body_dist >= 2500.0 and drive_ok_frames >= int(drive_frames * 0.9),
		"body drove %.0f m; within leash %d/%d frames; max lag %.1f m; impacts %d" % [drive_body_dist, drive_ok_frames, drive_frames, max_lag, impacts])
	_ok("traffic_vehicle_ahead_stopped_body", blocker_placed and blocker_stop_seen,
		"blocker placed=%s stop seen=%s" % [str(blocker_placed), str(blocker_stop_seen)])
	_ok("authority_held_by_physics_while_blocked", auth_hold_seen, "authoritative car waited for the physical car")
	_ok("parked_at_destination", parked, "state=%s" % str(row.get("state")))
	if not parked:
		return
	var vrow := _vehicle_row(SimBridge.last_mobility, veh_id)
	_ok("vehicle_identity_preserved", str(vrow.get("vehicle_id", "")) == veh_id and str(vrow.get("owner", "")) == str(_cid),
		"vehicle %s owner %s parked=%s" % [veh_id, str(vrow.get("owner")), str(vrow.get("parked"))])

	# --- 3. exit, walk into work, be inside -----------------------------------
	var saw_exit_body := false
	var inside_work := false
	var work_bid := -1
	for i in range(3000):
		var block := _step(_game_dt)
		if block.is_empty():
			break
		row = _citizen_row(block)
		_focus_on(row)
		if have_ext:
			_ext.update_focus(Vector3(float(row["x"]), 0.0, float(row["y"])))
		_record(block, "walk_in")
		var st: String = str(row.get("state"))
		if st == "on_foot" and _emb.body_of("cit:%d" % _cid) != null:
			saw_exit_body = true
		if st in ["inside_building", "doing_activity"]:
			inside_work = true
			work_bid = int(row["building_id"])
			break
		await get_tree().physics_frame
	_ok("exited_vehicle_on_foot", saw_exit_body, "citizen body beside the car")
	_ok("entered_work_building", inside_work and work_bid >= 0 and work_bid != home_bid, "building %d" % work_bid)
	_ok("no_bodies_inside", _emb.body_of("cit:%d" % _cid) == null, "citizen body freed inside the building")
	if inside_work:
		var gi: Dictionary = SimBridge.get_interior(work_bid)
		var occ: Array = gi.get("interior", {}).get("occupants", [])
		var found := false
		for o in occ:
			if int(o.get("citizen_id", -1)) == _cid:
				found = true
		_ok("interior_occupant_because_arrived", gi.get("ok", false) and found,
			"GET_INTERIOR(%d) occupants include citizen %d: %s" % [work_bid, _cid, str(found)])
		# The activity begins because the citizen arrived: at 08:00 the row says work.
		var hnow := float(SimBridge.last_summary.get("hour", 0.0))
		if hnow < 8.02:
			SimBridge.advance_time((8.02 - hnow) * 3600.0, "")
		var r8 := _citizen_row(SimBridge.get_mobility().get("mobility", {}))
		_ok("scheduled_duty_after_arrival", str(r8.get("activity")) == "work" and str(r8.get("state")) == "doing_activity",
			"08:01 activity=%s state=%s" % [str(r8.get("activity")), str(r8.get("state"))])

	# --- 4. LOD promotion / demotion on the return trip -----------------------
	var hnow2 := float(SimBridge.last_summary.get("hour", 0.0))
	if hnow2 < 15.97:
		SimBridge.advance_time((15.97 - hnow2) * 3600.0, "")
	m = SimBridge.get_mobility().get("mobility", {})
	row = _citizen_row(m)
	_focus_on(row)
	var demoted := false
	var promoted_back := false
	var moved_while_far := 0.0
	var jump_on_promote := 0.0
	var phase := 0
	var far_start := Vector2.ZERO
	var frames_far := 0
	var returned_home := false
	for i in range(12000):
		var block := _step(_game_dt)
		if block.is_empty():
			break
		row = _citizen_row(block)
		var st: String = str(row.get("state"))
		var id := "cit:%d" % _cid
		var vid2 := str(row.get("vehicle_id")) if row.get("vehicle_id") != null else ""
		if phase == 0:
			_focus_on(row)
			if st == "driving" and float(row.get("progress", 0.0)) > 0.2:
				# player walks away: focus 1.5 km off
				SimBridge.focus_xy = Vector2(float(row["x"]) + 1500.0, float(row["y"]))
				far_start = Vector2(float(row["x"]), float(row["y"]))
				phase = 1
		elif phase == 1:
			frames_far += 1
			if _emb.body_of(id) == null and (vid2 == "" or _emb.body_of(vid2) == null):
				demoted = true
			if frames_far > int(20.0 / _game_dt):
				moved_while_far = far_start.distance_to(Vector2(float(row["x"]), float(row["y"])))
				_focus_on(row)
				phase = 2
		elif phase == 2:
			_focus_on(row)
			var b = _emb.body_of(vid2) if vid2 != "" else _emb.body_of(id)
			if b != null:
				promoted_back = true
				var ar := Vector2(float(row["x"]), float(row["y"]))
				if vid2 != "":
					var vr2 := _vehicle_row(block, vid2)
					ar = Vector2(float(vr2["x"]), float(vr2["y"]))
				jump_on_promote = ar.distance_to(Vector2(b.global_position.x, b.global_position.z))
				phase = 3
		else:
			_focus_on(row)
		if have_ext:
			_ext.update_focus(Vector3(float(row["x"]), 0.0, float(row["y"])))
		_record(block, "return")
		if phase >= 1 and st in ["inside_building", "doing_activity"] and int(row["building_id"]) == home_bid:
			returned_home = true
			break
		await get_tree().physics_frame
	_ok("lod_demoted_when_player_left", demoted, "bodies freed with focus 1.5 km away")
	_ok("trip_progressed_abstractly_while_far", moved_while_far > 50.0, "authoritative position moved %.0f m while no body existed" % moved_while_far)
	_ok("lod_promoted_back_same_identity", promoted_back and jump_on_promote <= 5.0,
		"body recreated at authoritative pose (jump %.2f m)" % jump_on_promote)
	_ok("returned_home", returned_home, "state=%s bid=%s" % [str(row.get("state")), str(row.get("building_id"))])
	_stats["promotions"] = _emb.promotions
	_stats["demotions"] = _emb.demotions
	_stats["reports_sent"] = _emb.reports_sent
	_stats["reports_applied"] = _emb.reports_applied
	SimBridge.disconnect_from_sim()


func _rows_equal(a: Dictionary, b: Dictionary) -> bool:
	for k in ["x", "y", "state", "step_index", "vehicle_id", "building_id", "progress", "activity", "parked", "driver", "fidelity"]:
		if a.has(k) or b.has(k):
			if str(a.get(k)) != str(b.get(k)):
				return false
	return true


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


func _heading_ahead(route: Array, dist: float) -> float:
	var acc := 0.0
	for i in range(1, route.size()):
		var a := Vector2(float(route[i - 1][0]), float(route[i - 1][1]))
		var b := Vector2(float(route[i][0]), float(route[i][1]))
		var l := a.distance_to(b)
		if acc + l >= dist:
			return atan2(b.y - a.y, b.x - a.x)
		acc += l
	return 0.0


func _finish() -> void:
	var n_checks := 0
	for l in _log:
		if l.begins_with("PASS") or l.begins_with("FAIL"):
			n_checks += 1
	if n_checks < 20:
		_ok("all_checks_ran", false, "only %d checks ran (script error or early abort)" % n_checks)
	print("\n==== EMBODIED MOBILITY GATE RESULTS (%s, citizen %d) ====" % [_bundle, _cid])
	for l in _log:
		print(l)
	print("==== %s (%d failure(s)) ====" % ["PASS" if _fail == 0 else "FAIL", _fail])
	var f := FileAccess.open(_trace_path, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify({"version": 1, "bundle": _bundle, "citizen_id": _cid,
			"game_dt": _game_dt, "results": _log, "stats": _stats, "rows": _rows}))
		f.close()
		print("TRACE saved: %s (%d rows)" % [_trace_path, _rows.size()])
	get_tree().quit(1 if _fail > 0 else 0)
