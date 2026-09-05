extends Node

## WORK GATE — smart objects and work embodied in the real city
## (ASPHODEL_SMART_OBJECTS_WORK_V1 §S6–S23).
##
## Live Python bridge + the REAL IsometricWorld scene + real Godot physics.
## Starts a Houston weekday, follows one worker (default citizen 68, a cashier
## of retail building 12013 — a workplace errand-running citizens actually
## visit) with the player, and checks, in engine: the rooms
## and smart objects of the workplace with stable ids; the commute that ends
## with the worker inside its workplace; the player entering the SAME building
## and a CitizenBody for that worker existing INSIDE the staged interior; the
## worker walking to a station (phase to_object -> using) with the body
## visibly moving; the exclusive hold on the station it uses; a served customer
## when the run produces one; substitution when the station is broken through
## SET_OBJECT_STATE; an authoritative object STATE_CHANGE in the building; LOD
## demotion 1.5 km away with the authoritative session continuing, and
## promotion back at the authoritative interior pose; save/load mid-use; and
## the end of the shift (CLOCK_OUT, no holds left, the citizen walking out).
##
## Every check reads authoritative state through the bridge plus a body the
## scene did not place itself. Nothing here decides anything about work.
##
##   godot --headless --path godot res://tests/WorkGate.tscn -- \
##       --bundle houston --citizen 68 --building 12013 --trace /tmp/trace.json

var _bundle := "houston"
var _cid := 68
var _bid := 12013
var _trace_path := "/tmp/asph_work_probe.json"
var _save_path := "/tmp/asph_work_gate_save.json"
var _game_dt := 1.0
var _fail := 0
var _log: Array[String] = []
var _rows: Array = []
var _events: Array = []          # events of this citizen / this building only
var _kinds := {}                 # every event kind seen -> count drained by this gate
var _counts := {}                # GET_WORK `counts`: the authority's persistent per-kind totals
var _seq := 0
var _scene: Node3D
var _emb: EmbodiedMobility
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
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--citizen" and i + 1 < args.size():
			_cid = int(args[i + 1])
		elif args[i] == "--building" and i + 1 < args.size():
			_bid = int(args[i + 1])
		elif args[i] == "--trace" and i + 1 < args.size():
			_trace_path = args[i + 1]
		elif args[i] == "--game-dt" and i + 1 < args.size():
			_game_dt = float(args[i + 1])
	await get_tree().physics_frame
	await _run()
	_finish()


# ------------------------------------------------------------------ helpers
## Null-safe int: an authoritative event field can be present and null (a
## building-less CLOCK_OUT, a customer-less TASK_END), and int(null) is a
## runtime error that would abort the check that reads it.
func _iv(v, d: int = -1) -> int:
	return d if v == null else int(v)


func _ints(a) -> Array:
	var out := []
	if a is Array:
		for v in a:
			out.append(_iv(v))
	return out


func _row(block: Dictionary, cid: int = -1) -> Dictionary:
	var want := _cid if cid < 0 else cid
	for row in block.get("citizens", []):
		if int(row["citizen_id"]) == want:
			return row
	return {}


func _work(row: Dictionary) -> Dictionary:
	var w = row.get("work", {})
	return w if w is Dictionary else {}


func _live_row(cid: int = -1) -> Dictionary:
	return _row(SimBridge.get_mobility(false).get("mobility", {}), cid)


func _focus(row: Dictionary) -> void:
	if row.is_empty():
		return
	SimBridge.focus_xy = Vector2(float(row["x"]), float(row["y"]))
	SimBridge.has_focus_xy = true


func _step(dt: float = -1.0) -> Dictionary:
	var d := _game_dt if dt <= 0.0 else dt
	var r: Dictionary = SimBridge.advance_time(d, "mobility")
	if r.get("ok", false) != true:
		return {}
	var block: Dictionary = r.get("mobility", {})
	_emb.apply(block, d)
	return block


func _pull_events() -> Array:
	## Drain the work event log. The Python side keeps a 5000-row RING of events
	## (a whole city produces thousands a game minute), so every step must drain
	## with `since_seq` or events are lost before they are read. Only the events
	## of this citizen or this building are kept in the trace; every kind is
	## counted, and GET_WORK's persistent per-kind `counts` is recorded as well.
	var r: Dictionary = SimBridge.get_work(_seq)
	var w: Dictionary = r.get("work", {})
	var evs: Array = w.get("events", [])
	var mine := []
	for e in evs:
		_seq = max(_seq, int(e.get("seq", 0)))
		var kind := str(e.get("event", ""))
		_kinds[kind] = int(_kinds.get(kind, 0)) + 1
		if _iv(e.get("citizen_id")) == _cid or _iv(e.get("building_id")) == _bid:
			_events.append(e)
			mine.append(e)
	var counts = w.get("counts")
	if counts is Dictionary:
		_counts = counts
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


func _record(block: Dictionary, tag: String) -> void:
	var row := _row(block)
	if row.is_empty():
		return
	var w := _work(row)
	var out := {"t": float(block.get("t_s", 0.0)), "hour": SimBridge.last_summary.get("hour"),
		"tag": tag, "state": row.get("state"), "ax": row.get("x"), "ay": row.get("y"),
		"building_id": row.get("building_id"), "phase": w.get("phase"),
		"object_id": w.get("object_id"), "task": w.get("task"), "room_id": w.get("room_id"),
		"zone": w.get("zone"), "role": w.get("role"), "carrying": w.get("carrying")}
	var cb = _emb.body_of("cit:%d" % _cid)
	if cb != null:
		out["bx"] = cb.global_position.x
		out["by"] = cb.global_position.y
		out["bz"] = cb.global_position.z
		out["interior_body"] = _emb.interior_body_ids().has("cit:%d" % _cid)
	_rows.append(out)


## Where the authoritative interior point of `row` must render inside the
## staged interior (the ONLY transform: the scene's own stage offset).
func _staged(row: Dictionary) -> Vector3:
	return _scene.interior_offset() + Vector3(float(row["x"]), _emb.body_height, float(row["y"]))


func _jump(row: Dictionary) -> float:
	var cb = _emb.body_of("cit:%d" % _cid)
	if cb == null:
		return -1.0
	var want := _staged(row)
	return Vector2(cb.global_position.x, cb.global_position.z).distance_to(Vector2(want.x, want.z))


func _rooms() -> Dictionary:
	return SimBridge.get_rooms(_bid)


func _object_row(rooms: Dictionary, oid: String) -> Dictionary:
	for o in rooms.get("objects", []):
		if str(o["object_id"]) == oid:
			return o
	return {}


## Coarse advance (whole game minutes) through stretches the gate does not need
## to see frame by frame; Python still runs its 1 s substeps.
func _coarse_until(pred: Callable, max_game_s: float, chunk_s: float = 60.0) -> Dictionary:
	var t := 0.0
	var row := {}
	while t < max_game_s:
		var block := _step(chunk_s)
		if block.is_empty():
			break
		t += chunk_s
		row = _row(block)
		_focus(row)
		_pull_events()
		_record(block, "coarse")
		if pred.call(row):
			return row
		await get_tree().physics_frame
	return row


func _fine_until(pred: Callable, max_frames: int, tag: String) -> Dictionary:
	var row := {}
	for i in range(max_frames):
		var block := _step()
		if block.is_empty():
			break
		row = _row(block)
		_focus(row)
		_record(block, tag)
		_pull_events()
		if pred.call(row):
			_pull_events()
			return row
		await get_tree().physics_frame
	_pull_events()
	return row


func _enter(bid: int) -> void:
	_scene.enter_building_by_id(bid)
	await get_tree().physics_frame
	await get_tree().physics_frame


func _leave() -> void:
	# The scene refuses to leave away from the door (a real gameplay rule), so
	# walk the player to the authoritative exit marker first.
	var interior = _scene.active_interior()
	if interior != null and is_instance_valid(interior):
		var marker: Node3D = interior.get_node_or_null("ExitMarker")
		if marker != null:
			_scene.get_player().teleport(marker.global_position + Vector3(0, 1.5, 0))
			await get_tree().physics_frame
	_scene.leave_current_building()
	await get_tree().physics_frame


# ------------------------------------------------------------------ the gate
func _run() -> void:
	Session.bundle_dir = "res://bundles/" + _bundle
	var citizens := BundleLoader.load_citizens(Session.bundle_dir)
	Session.citizen = (citizens[_cid] if _cid < citizens.size() else citizens[0]).duplicate(true)
	Session.citizen["citizen_id"] = _cid if _cid < citizens.size() else 0
	_scene = preload("res://IsometricWorld.tscn").instantiate()
	add_child(_scene)
	for i in range(20):
		await get_tree().physics_frame
	if not SimBridge.is_connected_to_sim():
		_ok("bridge_connected", false, "start python -m asphodel.bridge.server first")
		return
	_emb = _scene.get_embodied()
	if _emb == null:
		_ok("embodied_mobility_present", false, "the scene has no EmbodiedMobility node")
		return
	_emb.time_scale = 1.0 / max(get_physics_process_delta_time(), 0.001) * _game_dt
	GameClock.time_scale = 0.0     # this gate is the only driver of the clock

	# --- (a) a world with work enabled ---------------------------------------
	# The scene itself issues the one START_WORLD of this session (the bridge
	# refuses a second one: "a world is already started"), with the player
	# embodying `--citizen` and the v6 default `work: true`.
	var started: Dictionary = SimBridge.last_summary
	_ok("world_started_with_work", SimBridge.mobility_enabled and SimBridge.work_enabled,
		"START_WORLD by the scene: mobility_enabled=%s work_enabled=%s, player_citizen=%s, hour=%s"
		% [str(SimBridge.mobility_enabled), str(SimBridge.work_enabled),
			str(started.get("player_citizen")), str(started.get("hour"))])
	if not SimBridge.work_enabled:
		return
	_pull_events()

	# --- (b) rooms + smart objects with stable ids ---------------------------
	var r1 := _rooms()
	var r2 := _rooms()
	var ids1 := []
	var ids2 := []
	for o in r1.get("objects", []):
		ids1.append(str(o["object_id"]))
	for o in r2.get("objects", []):
		ids2.append(str(o["object_id"]))
	var zones := []
	var kinds := []
	for rm in r1.get("rooms", []):
		zones.append(str(rm.get("zone", "")))
		kinds.append(str(rm.get("kind", "")))
	var ids_ok: bool = ids1.size() > 0 and ids1 == ids2
	var zones_ok: bool = r1.get("rooms", []).size() > 0 and not zones.has("")
	var prefix_ok := true
	for oid in ids1:
		if not oid.begins_with("so:%d:" % _bid):
			prefix_ok = false
	_ok("rooms_and_objects_stable", r1.get("ok", false) and ids_ok and zones_ok and prefix_ok,
		"%d rooms %s zones=%s, %d objects, ids identical across two GET_ROOMS=%s, entrance=%s"
		% [r1.get("rooms", []).size(), str(kinds), str(zones), ids1.size(), str(ids_ok),
			str(r1.get("entrance"))])

	# --- (c) the worker commutes and enters its workplace (S6) ---------------
	# Whole game minutes while the worker is still at home, then 5 s steps once
	# it is on the street: the walk from the entrance to its first station lasts
	# under a minute, and the gate must be inside the building to watch it.
	var entrance := Vector2(float(r1.get("entrance", [0, 0])[0]), float(r1.get("entrance", [0, 0])[1]))
	await _coarse_until(func(rr):
		return str(rr.get("state")) == "on_foot" \
			and Vector2(float(rr["x"]), float(rr["y"])).distance_to(entrance) < 600.0,
		11.0 * 3600.0, 60.0)
	var row := await _coarse_until(func(rr):
		return int(rr.get("building_id", -1)) == _bid and str(rr.get("state")) == "doing_activity",
		60.0 * 60.0, 5.0)
	var arrived: bool = int(row.get("building_id", -1)) == _bid and str(row.get("state")) == "doing_activity"
	_ok("worker_commuted_into_workplace", arrived,
		"citizen %d state=%s building=%s at hour %s, interior xy=(%s,%s) role=%s"
		% [_cid, str(row.get("state")), str(row.get("building_id")),
			str(SimBridge.last_summary.get("hour")), str(row.get("x")), str(row.get("y")),
			str(_work(row).get("role"))])
	if not arrived:
		return
	# the reported position is inside the building's own room footprint
	var inside_aabb := false
	for rm in r1.get("rooms", []):
		if float(row["x"]) >= float(rm["x0"]) - 0.5 and float(row["x"]) <= float(rm["x1"]) + 0.5 \
				and float(row["y"]) >= float(rm["y0"]) - 0.5 and float(row["y"]) <= float(rm["y1"]) + 0.5:
			inside_aabb = true
	_ok("interior_position_is_inside_the_footprint", inside_aabb,
		"authoritative interior position (%.2f, %.2f) lies in a room of building %d"
		% [float(row["x"]), float(row["y"]), _bid])

	# --- (d) the player enters the same building; the worker has a body ------
	await _enter(_bid)
	# Measure the pose against the SAME block the body was materialized from:
	# a game second later the authority has already walked on and the body is
	# legitimately a stride behind it (that lag is checked by the follow leash).
	var block: Dictionary = SimBridge.last_mobility
	row = _row(block)
	var cb = _emb.body_of("cit:%d" % _cid)
	var in_interior: bool = _scene.inside_building() == _bid and _scene.active_interior() != null
	var body_inside: bool = cb != null and _emb.interior_body_ids().has("cit:%d" % _cid)
	_ok("player_inside_building_worker_embodied", in_interior and body_inside,
		"inside_building()=%d, CitizenBody cit:%d at %s (staged interior offset %s), %d interior bodies"
		% [_scene.inside_building(), _cid, str(cb.global_position) if cb != null else "none",
			str(_scene.interior_offset()), _emb.interior_bodies])
	if not body_inside:
		return
	_ok("interior_body_at_authoritative_pose", _jump(row) <= 0.5,
		"materialized %.2f m from interior_offset + (row.x, row.y) of the block it was built from"
		% _jump(row))
	block = _step(1.0)
	row = _row(block)

	# --- (e) to_object -> using, and the body walks it (S7/S10/S23) ----------
	var walked := 0.0
	var last: Vector3 = cb.global_position
	var to_object_frames := 0
	var saw_to_object := str(_work(row).get("phase", "")) == "to_object"
	if not saw_to_object:
		# already at a station: wait (5 s of game time per step, so a walk that
		# lasts half a minute cannot slip past) for the next MOVE_TO_OBJECT.
		row = await _coarse_until(func(rr):
			return str(_work(rr).get("phase", "")) == "to_object", 90.0 * 60.0, 5.0)
		saw_to_object = str(_work(row).get("phase", "")) == "to_object"
	cb = _emb.body_of("cit:%d" % _cid)
	if cb != null:
		last = cb.global_position
	var walk_target := str(_work(row).get("object_id", ""))
	if saw_to_object:
		for i in range(1200):
			var b2 := _step()
			if b2.is_empty():
				break
			row = _row(b2)
			_focus(row)
			_record(b2, "to_object")
			_pull_events()
			cb = _emb.body_of("cit:%d" % _cid)
			if cb != null:
				walked += Vector2(cb.global_position.x, cb.global_position.z).distance_to(
					Vector2(last.x, last.z))
				last = cb.global_position
			to_object_frames += 1
			if str(_work(row).get("phase", "")) != "to_object":
				break
			await get_tree().physics_frame
		_pull_events()
	row = await _fine_until(func(rr): return str(_work(rr).get("phase", "")) == "using", 900, "await_using")
	var w := _work(row)
	var using: bool = str(w.get("phase", "")) == "using" and w.get("object_id") != null
	_ok("phase_to_object_then_using", saw_to_object and using,
		"to_object (target %s, %d frames) -> using object %s task %s in room %s zone %s"
		% [walk_target, to_object_frames, str(w.get("object_id")), str(w.get("task")),
			str(w.get("room_id")), str(w.get("zone"))])
	_ok("body_walked_inside_the_interior", walked >= 3.0,
		"CitizenBody cit:%d moved %.1f m inside the staged interior while phase was to_object"
		% [_cid, walked])
	var oid := str(w.get("object_id", ""))
	var task0 := str(w.get("task", ""))
	if oid == "":
		return

	# --- (f) the station is held exclusively by this worker (S8) -------------
	var holder_samples := 0
	var holder_ok := 0
	var foreign := []
	var last_holders := []
	for i in range(8):
		row = _row(SimBridge.last_mobility)
		if str(_work(row).get("phase", "")) != "using" or str(_work(row).get("object_id", "")) != oid:
			_step(2.0)
			_pull_events()
			await get_tree().physics_frame
			continue      # only claim exclusivity for samples the worker IS using it
		var o := _object_row(_rooms(), oid)
		last_holders = _ints(o.get("holders", []))
		holder_samples += 1
		if last_holders == [_cid]:
			holder_ok += 1
		for h in last_holders:
			if h != _cid:
				foreign.append(h)
		_step(2.0)
		_pull_events()
		_record(SimBridge.last_mobility, "hold")
		await get_tree().physics_frame
	_ok("station_held_exclusively", holder_samples > 0 and holder_ok == holder_samples and foreign.is_empty(),
		"%s holders == [%d] in %d/%d GET_ROOMS samples taken while the worker was using it (last %s); other holders seen: %s"
		% [oid, _cid, holder_ok, holder_samples, str(last_holders), str(foreign)])
	# markers: the used station is drawn
	_emb.refresh_object_markers()
	_ok("used_stations_marked", _emb.marker_ids().has(oid),
		"%d holder markers rendered in the staged interior, including %s"
		% [_emb.marker_ids().size(), oid])

	# --- (g) a served customer, if the run produces one ----------------------
	# Errand-running citizens arrive at a staffed shop on their own schedule; the
	# gate waits three game hours for one and reports exactly what happened.
	await _coarse_until(func(_rr):
		return not _events_of("SERVED", _cid).is_empty(), 3.0 * 3600.0, 30.0)
	var served_evs := _events_of("SERVED", _cid)
	var served_here := _building_events("SERVED")
	if not served_evs.is_empty():
		_ok("customer_served_by_worker", true,
			"SERVED: citizen %d served customer %s at %s (%d in total)"
			% [_cid, str(served_evs[0].get("customer_id")), str(served_evs[0].get("object_id")),
				served_evs.size()])
	else:
		_info("customer_served_by_worker",
			"no SERVED event for citizen %d in the 3 game-hour window (its CLOCK_OUT will report served=0) — not observed, so not claimed" % _cid)
	if not served_here.is_empty():
		_ok("customer_served_in_workplace", true,
			"%d SERVED events in building %d, e.g. cashier %s served customer %s at %s; CUSTOMER_ARRIVED=%d QUEUED=%d UNSERVED=%d"
			% [served_here.size(), _bid, str(served_here[0].get("citizen_id")),
				str(served_here[0].get("customer_id")), str(served_here[0].get("object_id")),
				_building_events("CUSTOMER_ARRIVED").size(), _building_events("CUSTOMER_QUEUED").size(),
				_building_events("CUSTOMER_UNSERVED").size()])
	else:
		_info("customer_served_in_workplace",
			"no customer was served in building %d within the window (CUSTOMER_ARRIVED=%d, QUEUED=%d, UNSERVED=%d, queued now=%s) — reported, not claimed"
			% [_bid, _building_events("CUSTOMER_ARRIVED").size(),
				_building_events("CUSTOMER_QUEUED").size(),
				_building_events("CUSTOMER_UNSERVED").size(),
				str(_rooms().get("status", {}).get("customers_queued"))])

	# --- (h) break the station -> substitution (S9) --------------------------
	row = _live_row()
	oid = str(_work(row).get("object_id", oid))
	var broke: Dictionary = SimBridge.set_object_state(oid, "working", false)
	var moved_on := false
	var new_oid := ""
	var new_phase := ""
	var t := 0.0
	while t < 60.0:
		var b3 := _step(5.0)
		if b3.is_empty():
			break
		t += 5.0
		row = _row(b3)
		_focus(row)
		_pull_events()
		_record(b3, "broken")
		new_oid = str(_work(row).get("object_id", ""))
		new_phase = str(_work(row).get("phase", ""))
		if (new_oid != oid and new_oid != "") or new_phase == "waiting":
			moved_on = true
			break
		await get_tree().physics_frame
	var broken_holders: Array = _object_row(_rooms(), oid).get("holders", [])
	_ok("broken_station_substituted", moved_on and broken_holders.is_empty(),
		"SET_OBJECT_STATE(%s, working, false) -> after %d game s citizen %d is on %s (phase %s); broken station holders=%s; OBJECT_UNAVAILABLE events=%d"
		% [oid, int(t), _cid, new_oid, new_phase, str(broken_holders),
			_events_of("OBJECT_UNAVAILABLE", _cid).size()])
	SimBridge.set_object_state(oid, "working", true)

	# --- (i) an authoritative object state change in this building (S11) -----
	var sc := _building_events("STATE_CHANGE")
	_ok("object_state_changed_in_building", not sc.is_empty(),
		"%d STATE_CHANGE events in building %d, e.g. %s" % [sc.size(), _bid,
			str(sc[0]) if not sc.is_empty() else "none"])

	# --- (k) save / load mid-use (S20) ---------------------------------------
	row = await _fine_until(func(rr): return str(_work(rr).get("phase", "")) == "using", 600, "await_using2")
	var before := _live_row()
	var rooms_before := _rooms()
	var holders_before := _holder_map(rooms_before)
	var sr: Dictionary = SimBridge.save(_save_path)
	var lr: Dictionary = SimBridge.load(_save_path)
	var after := _live_row()
	var holders_after := _holder_map(_rooms())
	var same: bool = sr.get("ok", false) and lr.get("ok", false) \
		and str(before.get("x")) == str(after.get("x")) and str(before.get("y")) == str(after.get("y")) \
		and str(_work(before).get("object_id")) == str(_work(after).get("object_id")) \
		and str(_work(before).get("task")) == str(_work(after).get("task")) \
		and str(holders_before) == str(holders_after)
	_ok("saveload_mid_use_identical", same,
		"xy (%s,%s)->(%s,%s), object %s->%s, task %s->%s, %d held objects identical=%s"
		% [str(before.get("x")), str(before.get("y")), str(after.get("x")), str(after.get("y")),
			str(_work(before).get("object_id")), str(_work(after).get("object_id")),
			str(_work(before).get("task")), str(_work(after).get("task")),
			holders_before.size(), str(str(holders_before) == str(holders_after))])

	# --- (j) LOD: leave, go 1.5 km away, come back (S18/S19) -----------------
	var lod_row := _live_row()
	var lod_obj := str(_work(lod_row).get("object_id", ""))
	var lod_task := str(_work(lod_row).get("task", ""))
	var workers := _workers_of_building()
	await _leave()
	var far := Vector2(float(lod_row["x"]) + 1500.0, float(lod_row["y"]))
	_scene.teleport_player(far.x, far.y)
	SimBridge.focus_xy = far
	SimBridge.has_focus_xy = true
	var t2 := 0.0
	while t2 < 20.0 * 60.0:
		var b4 := _step(60.0)
		if b4.is_empty():
			break
		t2 += 60.0
		SimBridge.focus_xy = far
		_pull_events()
		_record(b4, "far")
		await get_tree().physics_frame
	var far_bodies := []
	for cid in workers:
		if _emb.body_of("cit:%d" % cid) != null:
			far_bodies.append(cid)
	var sessions: Dictionary = SimBridge.get_work(0).get("work", {}).get("sessions", {})
	var sess: Dictionary = sessions.get(str(_cid), {})
	var sess_live: bool = not sess.is_empty() and int(sess.get("building_id", -1)) == _bid
	_ok("no_bodies_while_far", far_bodies.is_empty() and _emb.interior_bodies == 0,
		"player 1.5 km away, interior left: no CitizenBody for any of the %d workers of building %d (%s)"
		% [workers.size(), _bid, str(workers)])
	_ok("session_continues_while_far", sess_live,
		"GET_WORK session for %d still in building %s: object %s (was %s), task %s (was %s), phase %s"
		% [_cid, str(sess.get("building_id")), str(sess.get("object_id")), lod_obj,
			str(sess.get("task_id")), lod_task, str(sess.get("phase"))])
	var same_obj: bool = str(sess.get("object_id")) == lod_obj and str(sess.get("task_id")) == lod_task
	if same_obj:
		_ok("session_object_and_task_unchanged_while_far", true,
			"object %s and task %s unchanged over 20 game minutes with no body" % [lod_obj, lod_task])
	else:
		_info("session_object_and_task_unchanged_while_far",
			"the worker moved on to object %s task %s while unobserved (was %s / %s) — the authority kept running, so this is reported, not claimed as continuity"
			% [str(sess.get("object_id")), str(sess.get("task_id")), lod_obj, lod_task])
	# come back and re-enter
	var back := _live_row()
	_scene.teleport_player(float(back["x"]) + 8.0, float(back["y"]) + 8.0)
	SimBridge.focus_xy = Vector2(float(back["x"]), float(back["y"]))
	await _enter(_bid)
	block = _step(1.0)
	row = _row(block)
	var jump := _jump(row)
	var promoted: bool = _emb.body_of("cit:%d" % _cid) != null
	_ok("promoted_back_at_authoritative_pose", promoted and jump >= 0.0 and jump <= 0.5,
		"body recreated inside the interior %.3f m from the authoritative pose; object %s (session object %s)"
		% [jump, str(_work(row).get("object_id")), str(sess.get("object_id"))])

	# --- (l) end of shift: CLOCK_OUT, holds released, walks out (S14/S16) ----
	var ended := await _coarse_until(func(rr):
		return _work(rr).get("phase") == null or str(rr.get("state")) != "doing_activity",
		12.0 * 3600.0, 120.0)
	_pull_events()
	var clocked := _events_of("CLOCK_OUT", _cid)
	var interrupted := _events_of("WORK_INTERRUPTED", _cid)
	_ok("shift_ended_with_clock_out", not clocked.is_empty() or not interrupted.is_empty(),
		"hour=%s state=%s phase=%s; CLOCK_OUT=%d %s WORK_INTERRUPTED=%d"
		% [str(SimBridge.last_summary.get("hour")), str(ended.get("state")),
			str(_work(ended).get("phase")), clocked.size(),
			str(clocked[0]) if not clocked.is_empty() else "", interrupted.size()])
	var held_by_worker := []
	var ledger: Dictionary = SimBridge.get_work(0).get("work", {}).get("reservations", {})
	var holders_map = ledger.get("holders", ledger)
	if holders_map is Dictionary:
		for k in holders_map:
			for h in _ints(holders_map[k]):
				if h == _cid:
					held_by_worker.append(k)
	_ok("no_reservations_left_for_worker", held_by_worker.is_empty(),
		"the reservation ledger holds nothing for citizen %d after the shift (%s)"
		% [_cid, str(held_by_worker)])
	var left := await _coarse_until(func(rr):
		return str(rr.get("state")) == "on_foot" and int(rr.get("building_id", -1)) < 0,
		45.0 * 60.0, 30.0)
	_ok("worker_leaves_on_foot", str(left.get("state")) == "on_foot" and int(left.get("building_id", -1)) < 0,
		"citizen %d is %s outside (building %s) at hour %s — existing mobility took over"
		% [_cid, str(left.get("state")), str(left.get("building_id")),
			str(SimBridge.last_summary.get("hour"))])

	_stats = {"event_kinds": _kinds, "authority_counts": _counts, "interior_bodies": _emb.interior_bodies, "promotions": _emb.promotions,
		"demotions": _emb.demotions, "reports": _emb.reports_sent,
		"markers": _emb.marker_ids().size(), "walked_m": walked,
		"workers": workers, "task0": task0}
	SimBridge.disconnect_from_sim()


func _holder_map(rooms: Dictionary) -> Dictionary:
	var out := {}
	for o in rooms.get("objects", []):
		var h: Array = o.get("holders", [])
		if not h.is_empty():
			out[str(o["object_id"])] = h
	return out


func _building_events(kind: String) -> Array:
	var out := []
	for e in _events:
		if str(e.get("event", "")) == kind and _iv(e.get("building_id")) == _bid:
			out.append(e)
	return out


func _workers_of_building() -> Array:
	## Every citizen the authority reports as employed at this workplace.
	var out := []
	for row in SimBridge.get_mobility(false).get("mobility", {}).get("citizens", []):
		var w = row.get("work", {})
		if w is Dictionary and _iv(w.get("workplace_id")) == _bid:
			out.append(int(row["citizen_id"]))
	return out


func _finish() -> void:
	var n := 0
	for l in _log:
		if l.begins_with("PASS") or l.begins_with("FAIL"):
			n += 1
	if n < 14:
		_ok("all_checks_ran", false, "only %d checks ran" % n)
	print("\n==== WORK GATE RESULTS (%s, citizen %d, building %d) ====" % [_bundle, _cid, _bid])
	for l in _log:
		print(l)
	print("==== %s (%d failure(s)) ====" % ["PASS" if _fail == 0 else "FAIL", _fail])
	var f := FileAccess.open(_trace_path, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify({"version": 1, "bundle": _bundle, "citizen_id": _cid,
			"building_id": _bid, "game_dt": _game_dt, "results": _log, "stats": _stats,
			"events": _events, "rows": _rows}))
		f.close()
		print("TRACE saved: %s (%d rows, %d events)" % [_trace_path, _rows.size(), _events.size()])
	get_tree().quit(1 if _fail > 0 else 0)
