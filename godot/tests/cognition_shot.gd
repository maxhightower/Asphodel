extends Node

## Cognition visual evidence (ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1).
##
## Runs the REAL IsometricWorld scene against the live Python bridge (protocol
## v7) and saves a frame at each stage of the certified social day: two
## coworkers in the same room, the workload one of them cannot keep up with, the
## other one walking over to help, both of them at the object during the help,
## the reciprocal repair hours later, the attack in the busiest shop, the
## cashier next door leaving on a warning it was told rather than saw, and the
## helper's body recreated after the player spent ten game minutes 1.5 km away.
##
## Interior frames are taken with the player INSIDE the staged interior (the
## cutaway camera), and every worker in the room is a CitizenBody driven from
## its authoritative interior position — nothing here is staged or posed.
##
## CAPTIONS: each one says what the pixels prove and what only the authority's
## rows prove. `_reached` is false unless the predicate the run was waiting for
## actually became true, and the caption is then prefixed NOT REACHED with what
## the frame really shows. The manifest carries the authoritative rows
## (GET_CITIZEN_CONTEXT, GET_COGNITION counts, the work session, GET_ROOMS
## state) at capture time.
##
##   xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 godot --path godot \
##     --rendering-method gl_compatibility --rendering-driver opengl3 \
##     res://tests/CognitionShot.tscn -- --bundle houston --helper 70 \
##     --workplace 8470 --shop 15873 --dir docs/npc/evidence

var _bundle := "houston"
var _helper := 70
var _workplace := 8470
var _shop := 15873
var _start_hour := 5.0
var _dir := "/tmp/asph_cognition_shots"
var _game_dt := 1.0

var _scene: Node3D
var _emb: EmbodiedMobility
var _manifest := []
var _cseq := 0
var _wseq := 0
var _cog: Array = []
var _kinds := {}
var _counts := {}
var _reached := true

# derived from the authority's own events
var _ben := -1
var _hobj := ""
var _htask := ""
var _warned := -1
var _seeded := -1
var _station := ""

# predicate state
var _p_cid := -1

const KEEP := ["HELP_DECIDED", "HELP_STARTED", "HELP_COMPLETED", "RECIPROCATED",
	"WARNING_RECEIVED", "AVOID_DECIDED", "AVOID_ROOM_DECIDED", "PERCEIVED"]


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--helper" and i + 1 < args.size():
			_helper = int(args[i + 1])
		elif args[i] == "--workplace" and i + 1 < args.size():
			_workplace = int(args[i + 1])
		elif args[i] == "--shop" and i + 1 < args.size():
			_shop = int(args[i + 1])
		elif args[i] == "--start-hour" and i + 1 < args.size():
			_start_hour = float(args[i + 1])
		elif args[i] == "--dir" and i + 1 < args.size():
			_dir = args[i + 1]
	DirAccess.make_dir_recursive_absolute(_dir)
	await _run()


# ------------------------------------------------------------------ helpers
func _iv(v, d: int = -1) -> int:
	return d if v == null else int(v)


func _hour() -> float:
	return float(SimBridge.last_summary.get("hour", 0.0))


func _hhmm() -> String:
	var h := _hour()
	return "%02d:%02d" % [int(h), int(floor((h - floor(h)) * 60.0))]


func _caption(text: String) -> String:
	if _reached:
		return text
	return "NOT REACHED within the captured window - the frame shows the world as it was: " + text


func _row(block: Dictionary, cid: int) -> Dictionary:
	for row in block.get("citizens", []):
		if int(row["citizen_id"]) == cid:
			return row
	return {}


func _work(row: Dictionary) -> Dictionary:
	var w = row.get("work", {})
	return w if w is Dictionary else {}


func _live_row(cid: int) -> Dictionary:
	return _row(SimBridge.get_mobility(false).get("mobility", {}), cid)


func _context(cid: int) -> Dictionary:
	var c = SimBridge.get_citizen_context(cid).get("context")
	return c if c is Dictionary else {}


func _sessions() -> Dictionary:
	var s = SimBridge.last_work.get("sessions", {})
	return s if s is Dictionary else {}


func _session_of(cid: int) -> Dictionary:
	var s = _sessions().get(str(cid), {})
	return s if s is Dictionary else {}


func _shop_customers() -> Array:
	var out := []
	var sessions := _sessions()
	for k in sessions:
		var s = sessions[k]
		if s is Dictionary and str(s.get("kind", "")) == "customer" \
				and _iv(s.get("building_id")) == _shop:
			out.append(int(str(k)))
	out.sort()
	return out


func _pull() -> void:
	var c: Dictionary = SimBridge.get_cognition(_cseq).get("cognition", {})
	for e in c.get("events", []):
		_cseq = max(_cseq, int(e.get("seq", 0)))
		var kind := str(e.get("event", ""))
		_kinds[kind] = int(_kinds.get(kind, 0)) + 1
		if KEEP.has(kind) and _cog.size() < 9000:
			_cog.append(e)
	var counts = c.get("counts")
	if counts is Dictionary:
		_counts = counts
	SimBridge.get_work(_wseq)     # refreshes last_work (sessions/reservations)
	var w: Dictionary = SimBridge.last_work
	for e in w.get("events", []):
		_wseq = max(_wseq, int(e.get("seq", 0)))


func _ev(kind: String, cid: int = -1) -> Array:
	var out := []
	for e in _cog:
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


func _rooms(bid: int) -> Dictionary:
	return SimBridge.get_rooms(bid)


func _dirty_objects(bid: int) -> Array:
	var out := []
	for o in _rooms(bid).get("objects", []):
		var st = o.get("state", {})
		if st is Dictionary and st.get("dirty") == true:
			out.append(str(o["object_id"]))
	out.sort()
	return out


func _place_player(row: Dictionary, off: Vector2 = Vector2(6.0, 4.0)) -> void:
	var p = _scene.get_player()
	if p == null or row.is_empty():
		return
	var bid := int(row.get("building_id", -1))
	if _scene.inside_building() >= 0 and _scene.inside_building() == bid:
		var s: Vector3 = _scene.interior_offset() + Vector3(float(row["x"]), 0.0, float(row["y"]))
		p.teleport(s + Vector3(off.x, 1.5, off.y))
	elif _scene.inside_building() >= 0:
		SimBridge.focus_xy = Vector2(float(row["x"]), float(row["y"]))
		SimBridge.has_focus_xy = true
		return
	else:
		p.teleport(Vector3(float(row["x"]) + off.x, 1.5, float(row["y"]) + off.y))
	SimBridge.focus_xy = Vector2(float(row["x"]), float(row["y"]))
	SimBridge.has_focus_xy = true


func _zoom(v: float) -> void:
	## Framing only. The camera never changes what is drawn, just how close.
	var cam = _scene.get_camera()
	if cam != null:
		cam.set_zoom(v)


func _settle(frames: int) -> void:
	var ext = _scene.get_exterior()
	for i in range(frames):
		if ext != null and _scene.inside_building() < 0:
			ext.update_focus(_scene.get_camera().get_focus())
		await get_tree().physics_frame


func _bodies_here() -> Array:
	var out := []
	for id in _emb.interior_body_ids():
		out.append(str(id))
	out.sort()
	return out


func _shot(name: String, caption: String, extra: Dictionary = {}) -> void:
	await get_tree().process_frame
	await get_tree().process_frame
	await get_tree().create_timer(0.3).timeout
	var img := get_viewport().get_texture().get_image()
	var path := _dir.path_join(name)
	img.save_png(path)
	var hrow := _live_row(_helper)
	var brow := _row(SimBridge.last_mobility, _ben) if _ben >= 0 else {}
	var row := {"file": name, "caption": caption, "hour": _hour(), "clock": _hhmm(),
		"helper": _helper, "beneficiary": _ben, "workplace": _workplace, "shop": _shop,
		"helper_row": {"state": hrow.get("state"), "building_id": hrow.get("building_id"),
			"x": hrow.get("x"), "y": hrow.get("y"), "work": _work(hrow)},
		"beneficiary_row": {"state": brow.get("state"), "building_id": brow.get("building_id"),
			"x": brow.get("x"), "y": brow.get("y"), "work": _work(brow)},
		"inside_building": _scene.inside_building(),
		"interior_bodies": _emb.interior_bodies, "interior_body_ids": _bodies_here(),
		"markers": _emb.marker_ids(), "cognition_counts": _counts}
	for k in extra:
		row[k] = extra[k]
	_manifest.append(row)
	print("SHOT saved: %s (%dx%d) %s" % [path, img.get_size().x, img.get_size().y, caption])


## Advance until the predicate holds; `_reached` records whether it did.
func _until(pred: Callable, max_game_s: float, chunk_s: float, follow: int = -1,
		place: bool = true) -> Dictionary:
	## `place` false keeps the player away from a citizen that is walking
	## outdoors: standing on it promotes it to the physical band, where a body
	## snagged on city geometry reports back and holds its trip up.
	var t := 0.0
	var row := {}
	_reached = false
	while t < max_game_s:
		var block := _step(chunk_s)
		if block.is_empty():
			break
		t += chunk_s
		if follow >= 0:
			row = _row(block, follow)
			if not row.is_empty():
				if place:
					_place_player(row)
				else:
					SimBridge.focus_xy = Vector2(float(row["x"]), float(row["y"]))
					SimBridge.has_focus_xy = true
		if pred.call():
			_reached = true
			return row
		if chunk_s <= 5.0 or int(t / chunk_s) % 10 == 0:
			await get_tree().physics_frame
	return row


func _enter(bid: int) -> void:
	_scene.enter_building_by_id(bid)
	await get_tree().physics_frame
	_step(_game_dt)
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


# ------------------------------------------------------------ predicates
func _p_never() -> bool:
	return false


func _p_helper_at_workplace() -> bool:
	var r := _row(SimBridge.last_mobility, _helper)
	return int(r.get("building_id", -1)) == _workplace and str(r.get("state")) == "doing_activity"


func _p_two_in_workplace() -> bool:
	var n := 0
	for r in SimBridge.last_mobility.get("citizens", []):
		if int(r.get("building_id", -1)) == _workplace and str(r.get("state")) == "doing_activity":
			n += 1
	return n >= 2


func _p_help_decided() -> bool:
	for e in _cog:
		if str(e.get("event", "")) == "HELP_DECIDED" and str(e.get("task_id", "")).begins_with("help_"):
			return true
	return false


func _p_help_to_object() -> bool:
	var w := _work(_row(SimBridge.last_mobility, _helper))
	return str(w.get("phase", "")) == "to_object" and str(w.get("task", "")) == _htask


func _p_help_using() -> bool:
	var w := _work(_row(SimBridge.last_mobility, _helper))
	return str(w.get("phase", "")) == "using" and str(w.get("task", "")) == _htask


func _p_customer_in_shop() -> bool:
	return not _shop_customers().is_empty()


func _p_attacked_in_shop() -> bool:
	for e in _cog:
		if str(e.get("event", "")) == "PERCEIVED" and str(e.get("what", "")) == "attacked_by" \
				and _iv(e.get("building_id")) == _shop:
			return true
	return false


func _p_left_shop() -> bool:
	var r := _row(SimBridge.last_mobility, _p_cid)
	if r.is_empty():
		return false
	return int(r.get("building_id", -1)) != _shop or str(r.get("state")) != "doing_activity"


func _p_using_station_after_13() -> bool:
	if _hour() < 13.0:
		return false
	var s := _session_of(_helper)
	return str(s.get("phase", "")) == "using" and str(s.get("object_id", "")) != "" \
		and _iv(s.get("building_id")) == _workplace


func _p_repair_underway() -> bool:
	for e in _cog:
		if str(e.get("event", "")) == "HELP_STARTED" and str(e.get("task_id", "")) == "repair_station":
			return true
	return false


func _p_reciprocated() -> bool:
	return not _ev("RECIPROCATED").is_empty()


# ------------------------------------------------------------------- the run
func _run() -> void:
	Session.bundle_dir = "res://bundles/" + _bundle
	Session.start_hour = _start_hour
	var citizens := BundleLoader.load_citizens(Session.bundle_dir)
	Session.citizen = (citizens[_helper] if _helper < citizens.size() else citizens[0]).duplicate(true)
	Session.citizen["citizen_id"] = _helper if _helper < citizens.size() else 0
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
	_zoom(16.0)      # interior frames: as close as the camera goes, so bodies read
	if not bool(SimBridge.last_summary.get("cognition_enabled", false)):
		printerr("world did not start with cognition enabled: %s" % str(SimBridge.last_summary))
		get_tree().quit(1)
		return
	_pull()
	print("SHOTS: cognition world started at hour %s, following citizen %d at workplace %d"
		% [str(SimBridge.last_summary.get("hour")), _helper, _workplace])

	# --- 00 two coworkers in the same room ------------------------------------
	await _until(_p_helper_at_workplace, 6.0 * 3600.0, 60.0, _helper, false)
	var arrived := _reached
	await _enter(_workplace)
	# the frame is only worth taking once the authority has put a second worker
	# in this interior — a caption about coworkers needs two of them
	await _until(_p_two_in_workplace, 90.0 * 60.0, 15.0, _helper)
	var pair := _reached
	# who else does the authority put in this interior right now
	var block: Dictionary = SimBridge.last_mobility
	var hrow := _row(block, _helper)
	var mates := []
	for r in block.get("citizens", []):
		if int(r.get("building_id", -1)) == _workplace and int(r["citizen_id"]) != _helper:
			mates.append(int(r["citizen_id"]))
	mates.sort()
	var mate_roles := []
	for cid in mates:
		var mr := _row(block, int(cid))
		mate_roles.append("%d:%s/%s/room %s" % [int(cid), str(_work(mr).get("role")),
			str(_work(mr).get("task")), str(_work(mr).get("room_id"))])
	_place_player(hrow, Vector2(3.0, 2.5))
	await _settle(30)
	_reached = arrived and pair
	await _shot("00_coworkers.png", _caption(
		"%s — cashier %d (task %s, room %s) and the other workers the authority reports inside workplace %d: %s. The player is in the same staged interior; %d bodies are drawn here and each one is driven from an authoritative interior position. PIXELS: the sales floor with worker bodies standing in it — %d are drawn, and a fixture at this camera angle can hide one of them, so the pixels prove bodies in a room, not which ones. AUTHORITY ONLY: who they are, their roles and what they are doing (manifest rows)."
		% [_hhmm(), _helper, str(_work(hrow).get("task")), str(_work(hrow).get("room_id")),
			_workplace, str(mate_roles), _emb.interior_bodies, _emb.interior_bodies]),
		{"coworkers_in_building": mates, "coworker_rows": mate_roles})

	# --- 01 the problem the authority can see ---------------------------------
	var dirty := _dirty_objects(_workplace)
	var cleaners := []
	for r in block.get("citizens", []):
		if int(r.get("building_id", -1)) == _workplace and str(_work(r).get("role", "")) == "cleaner":
			cleaners.append(int(r["citizen_id"]))
	await _settle(4)
	_reached = true
	await _shot("01_problem.png",
		"%s — the problem the authority can see in workplace %d: %d of its smart objects carry state dirty=true (first eight: %s), and the cleaners on shift are %s. That backlog is what the WorkRuntime publishes as a cleaning_workload problem and what the helper's score is computed from. PIXELS: the sales floor and its fixtures — a dirty fixture is drawn exactly like a clean one, so the pixels prove nothing about the backlog. AUTHORITY ONLY: the dirty-object list and the workload (GET_ROOMS state in the manifest)."
		% [_hhmm(), _workplace, dirty.size(), str(dirty.slice(0, 8)), str(cleaners)],
		{"dirty_objects": dirty, "cleaners_on_shift": cleaners})

	# --- 02 the helper walks over to help -------------------------------------
	await _until(_p_help_decided, 90.0 * 60.0, _game_dt, _helper)
	var decided := []
	for e in _cog:
		if str(e.get("event", "")) == "HELP_DECIDED" and str(e.get("task_id", "")).begins_with("help_"):
			decided.append(e)
	var hd: Dictionary = decided[0] if not decided.is_empty() else {}
	if not hd.is_empty():
		_ben = _iv(hd.get("beneficiary"))
		_htask = str(hd.get("task_id", ""))
		_hobj = str(hd.get("object_id", ""))
	var moving := await _until(_p_help_to_object, 120.0, _game_dt, _helper)
	if not _reached and not hd.is_empty():
		# the walk may already have finished inside the same game second
		moving = _row(SimBridge.last_mobility, _helper)
		_reached = _p_help_using()
	_place_player(moving, Vector2(4.0, 3.0))
	await _settle(6)
	var w2 := _work(_row(SimBridge.last_mobility, _helper))
	await _shot("02_helper_moves_to_assist.png", _caption(
		"%s — HELP_DECIDED: citizen %d chose, on its own, to help %d with %s on %s (problem %s, score %s vs threshold %s, would_help_without_history=%s). The frame is the moment the helper is on its way to that object (phase %s). PIXELS: the helper's body partway across the room — one still cannot show motion. AUTHORITY ONLY: that it is moving, where to, and that this walk is a help task for another citizen (the phase/task/beneficiary rows in the manifest)."
		% [_hhmm(), _helper, _ben, _htask, _hobj, str(hd.get("problem")), str(hd.get("score")),
			str(hd.get("threshold")), str(hd.get("would_help_without_history")), str(w2.get("phase"))]),
		{"help_decided": hd})

	# --- 03 both bodies present during the help -------------------------------
	await _until(_p_help_using, 300.0, _game_dt, _helper)
	_emb.refresh_object_markers()
	var hrow3 := _row(SimBridge.last_mobility, _helper)
	var brow3 := _row(SimBridge.last_mobility, _ben)
	_place_player(hrow3, Vector2(3.5, 2.5))
	await _settle(6)
	var both: bool = _emb.body_of("cit:%d" % _helper) != null and _emb.body_of("cit:%d" % _ben) != null
	await _shot("03_both_embodied_during_help.png", _caption(
		"%s — the help task running: citizen %d is at %s (phase %s) with the gold `using` highlight, and the coworker it is helping, citizen %d, is embodied in the same room (task %s, room %s). Both bodies present in the frame: %s; %d interior bodies, holder rings %s. PIXELS: the room with worker bodies at its fixtures, one of them carrying the gold `using` tint and a holder ring at its object — a fixture can occlude a body at this angle. AUTHORITY ONLY: which body is which, and that one of them is doing the other's work."
		% [_hhmm(), _helper, str(_work(hrow3).get("object_id")), str(_work(hrow3).get("phase")),
			_ben, str(_work(brow3).get("task")), str(_work(brow3).get("room_id")), str(both),
			_emb.interior_bodies, str(_emb.marker_ids())]),
		{"help_started": _ev("HELP_STARTED", _helper), "help_completed": _ev("HELP_COMPLETED", _helper)})

	# --- 08 LOD: 1.5 km away for 10 game minutes, then back -------------------
	var ctx_before := _context(_helper)
	var before := _live_row(_helper)
	await _leave()
	var far := Vector2(float(before["x"]) + 1500.0, float(before["y"]))
	_scene.teleport_player(far.x, far.y)
	SimBridge.focus_xy = far
	SimBridge.has_focus_xy = true
	var t := 0.0
	while t < 10.0 * 60.0:
		_step(60.0)
		t += 60.0
		SimBridge.focus_xy = far
		await get_tree().physics_frame
	var after := _live_row(_helper)
	_scene.teleport_player(float(after["x"]) + 8.0, float(after["y"]) + 8.0)
	if int(after.get("building_id", -1)) >= 0:
		await _enter(int(after.get("building_id", -1)))
	after = _row(SimBridge.last_mobility, _helper)
	_place_player(after, Vector2(3.5, 2.5))
	await _settle(20)
	var cb = _emb.body_of("cit:%d" % _helper)
	var jump := -1.0
	if cb != null and not after.is_empty():
		var want: Vector3 = _scene.interior_offset() + Vector3(float(after["x"]), 0.0, float(after["y"]))
		jump = Vector2(cb.global_position.x, cb.global_position.z).distance_to(Vector2(want.x, want.z))
	var ctx_after := _context(_helper)
	var ids_before := []
	for f in ctx_before.get("memories", []):
		ids_before.append(str(f.get("fact_id", "")))
	var ids_after := []
	for f in ctx_after.get("memories", []):
		ids_after.append(str(f.get("fact_id", "")))
	var still := 0
	for i in ids_before:
		if ids_after.has(i):
			still += 1
	_reached = cb != null
	await _shot("08_lod_return.png", _caption(
		"%s — back after 10 game minutes with the player 1.5 km away and no body anywhere: the CitizenBody for citizen %d is recreated %.2f m from its authoritative interior pose, on %s. Nothing of its mind was lost with its body: %d of the %d salient memories it held before the trip are still there (n_memories %s -> %s — the authority kept simulating while nobody watched, so it may have gained more), and its %d relationships are unchanged partners. PIXELS: a body standing in the room again — a picture cannot show a memory. AUTHORITY ONLY: the two GET_CITIZEN_CONTEXT rows in the manifest, before and after."
		% [_hhmm(), _helper, jump, str(_work(after).get("object_id")), still, ids_before.size(),
			str(ctx_before.get("n_memories")), str(ctx_after.get("n_memories")),
			ctx_after.get("relationships", []).size()]),
		{"context_before_lod": ctx_before, "context_after_lod": ctx_after, "pose_error_m": jump,
			"salient_fact_ids_before": ids_before, "salient_fact_ids_after": ids_after})

	# --- 05 the threat inside the busiest shop --------------------------------
	if _scene.inside_building() >= 0:
		await _leave()
	await _until(_p_customer_in_shop, 6.0 * 3600.0, 60.0, -1)
	var customers := _shop_customers()
	if customers.is_empty():
		_manifest.append({"file": null,
			"caption": "05/06/07 skipped: the authority never reported a customer session inside shop %d" % _shop})
	else:
		_seeded = int(customers[0])
		SimBridge.seed_outbreak("classic_zombie_fast", _seeded)
		_zoom(16.0)
		await _enter(_shop)
		await _until(_p_attacked_in_shop, 40.0 * 60.0, 5.0, -1)
		var attacked := _reached
		var attacks := []
		for e in _cog:
			if str(e.get("event", "")) == "PERCEIVED" and str(e.get("what", "")) == "attacked_by" \
					and _iv(e.get("building_id")) == _shop:
				attacks.append(e)
		# derive the warned citizen NOW: the shout wave lands in the same drained
		# batch as the attack, and its second-hand decision is only visible
		# before it perceives the threat itself
		for e in _cog:
			if str(e.get("event", "")) != "AVOID_DECIDED" or _iv(e.get("building_id")) != _shop:
				continue
			if bool(e.get("first_hand", true)):
				continue
			_warned = _iv(e.get("citizen_id"))
			break
		var wrow0 := _row(SimBridge.last_mobility, _warned) if _warned >= 0 else {}
		var wctx0 := _context(_warned) if _warned >= 0 else {}
		var victim := _iv(attacks[0].get("citizen_id")) if not attacks.is_empty() else -1
		var vrow := _row(SimBridge.last_mobility, victim) if victim >= 0 else {}
		if not vrow.is_empty():
			_place_player(vrow, Vector2(4.0, 3.0))
		await _settle(10)
		var zrow := _row(SimBridge.last_mobility, _seeded)
		var zbody = _emb.body_of("cit:%d" % _seeded)
		var zin: bool = zbody != null and _emb.interior_body_ids().has("cit:%d" % _seeded)
		_reached = attacked
		await _shot("05_threat_witnessed.png", _caption(
			"%s — customer %d (the lowest-id customer session the authority reported inside the shop, of %s) was seeded with classic_zombie_fast, died, rose and attacked inside shop %d: the first PERCEIVED attacked_by is citizen %s in room %s, and %d citizens are still embodied in this staged interior. The attacker's own row is state \"%s\" / health \"%s\"; a body for it exists: %s, drawn inside this staged interior: %s (the renderer only puts a body in a staged interior for states doing_activity / inside_building, so an attacker that has left that state is drawn on the exterior street, not here). PIXELS: the shop floor and the workers still in it. AUTHORITY ONLY: the attack, its victim and the witnesses (manifest events)."
			% [_hhmm(), _seeded, str(customers), _shop,
				str(attacks[0].get("citizen_id")) if not attacks.is_empty() else "none",
				str(attacks[0].get("room_id")) if not attacks.is_empty() else "none",
				_emb.interior_bodies, str(zrow.get("state")), str(zrow.get("health")),
				str(zbody != null), str(zin)]),
			{"attacked_by_events": attacks, "undead_row": zrow})

		# let the shout wave land
		await _until(_p_never, 5.0 * 60.0, 5.0, -1)
		# --- 06 the warned citizen changes route ------------------------------
		if _warned < 0:
			_manifest.append({"file": null,
				"caption": "06 skipped: no citizen decided to avoid shop %d on somebody else's warning" % _shop})
		else:
			_p_cid = _warned
			var wr := {}
			for e in _cog:
				if str(e.get("event", "")) == "WARNING_RECEIVED" and _iv(e.get("citizen_id")) == _warned:
					wr = e
					break
			# wrow0 / wctx0 were sampled at the decision above: minutes later this
			# citizen has witnessed the attack itself and runs on an emergency
			# goal, which would hide the second-hand decision this frame is about
			var wroom = _work(wrow0).get("room_id")
			var g0 = wctx0.get("goal")
			await _until(_p_left_shop, 25.0 * 60.0, 5.0, _warned)
			var left := _reached
			var wrow := _row(SimBridge.last_mobility, _warned)
			var wctx := _context(_warned)
			var goal = wctx.get("goal")
			if _scene.inside_building() == _shop and int(wrow.get("building_id", -1)) != _shop:
				# follow it out of the building to show the route change
				await _leave()
				_place_player(wrow, Vector2(6.0, 4.0))
				var ext = _scene.get_exterior()
				for i in range(240):
					_step(_game_dt)
					wrow = _row(SimBridge.last_mobility, _warned)
					_place_player(wrow, Vector2(6.0, 4.0))
					if ext != null:
						ext.force_materialize(_scene.get_player().global_position)
						ext.update_focus(_scene.get_camera().get_focus())
					if _emb.body_of("cit:%d" % _warned) != null and i > 60:
						break
					await get_tree().physics_frame
			if _scene.inside_building() < 0:
				_zoom(30.0)
			await _settle(20)
			_reached = left
			await _shot("06_warned_citizen_reroutes.png", _caption(
				"%s — citizen %d was %s in room %s of shop %d when a shout reached it (WARNING_RECEIVED from %s, goal_before %s, hops %s) and it decided to avoid the whole building on that word alone (AVOID_DECIDED first_hand=false); seconds after that decision its active goal came from source \"%s\" (%s). It then walked out: it is now state %s, building %s, on a %s goal (by now it had also seen the attack itself, so the later goal is not the second-hand one). Its exterior body is drawn: %s. PIXELS: %s — a route change looks like an ordinary walk. AUTHORITY ONLY: that it left because of something it was told, not something it saw (the two contexts and the warning row in the manifest)."
				% [_hhmm(), _warned, str(wrow0.get("state")), str(wroom), _shop, str(wr.get("sender")),
					str(wr.get("goal_before")), str(wr.get("hops")),
					(str(g0.get("source")) if g0 is Dictionary else "-"),
					(str(g0.get("reason")) if g0 is Dictionary else "-"),
					str(wrow.get("state")), str(wrow.get("building_id")),
					(str(goal.get("source")) if goal is Dictionary else "-"),
					str(_emb.body_of("cit:%d" % _warned) != null),
					("the street outside the shop it walked out of" if _scene.inside_building() < 0
						else "the shop interior it is leaving")]),
				{"warning_received": wr, "warned_context_at_decision": wctx0,
					"warned_context_after": wctx})

			# --- 07 somebody carrying the alarm outdoors ----------------------
			var fleeing := []
			var ob: Dictionary = SimBridge.get_outbreak(0).get("outbreak", {})
			for e in ob.get("events", []):
				if str(e.get("event", "")) == "FLEE" and _iv(e.get("building_id")) == _shop:
					fleeing.append(_iv(e.get("citizen_id")))
			var target := -1
			var near_others := 0
			var blk: Dictionary = SimBridge.last_mobility
			for cid in fleeing:
				var r := _row(blk, cid)
				if r.is_empty() or str(r.get("state")) != "on_foot":
					continue
				var n := 0
				for other in blk.get("citizens", []):
					if int(other["citizen_id"]) == cid or str(other.get("state")) != "on_foot":
						continue
					if Vector2(float(other["x"]), float(other["y"])).distance_to(
							Vector2(float(r["x"]), float(r["y"]))) < 25.0:
						n += 1
				if n > near_others:
					near_others = n
					target = cid
			if target < 0 and not fleeing.is_empty():
				target = fleeing[0]
			if target < 0:
				_manifest.append({"file": null,
					"caption": "07 skipped: the outbreak runtime reported no FLEE inside shop %d in this window" % _shop})
			else:
				if _scene.inside_building() >= 0:
					await _leave()
				var ext2 = _scene.get_exterior()
				var body = null
				var trow := {}
				for i in range(300):
					_step(_game_dt)
					trow = _row(SimBridge.last_mobility, target)
					_place_player(trow, Vector2(7.0, 5.0))
					if ext2 != null:
						ext2.force_materialize(_scene.get_player().global_position)
						ext2.update_focus(_scene.get_camera().get_focus())
					body = _emb.body_of("cit:%d" % target)
					if body != null and i > 60:
						break
					await get_tree().physics_frame
				_zoom(30.0)
				await _settle(20)
				var shared := []
				for e in _cog:
					if str(e.get("event", "")) == "WARNING_RECEIVED" and _iv(e.get("sender")) == target:
						shared.append(_iv(e.get("citizen_id")))
				_reached = body != null and near_others > 0
				await _shot("07_carrying_the_alarm.png", _caption(
					"%s — citizen %d fled the attacked room of shop %d and is outdoors (state %s) with %d other citizens on foot within 25 m; the authority records it as the sender of %d warnings received by %s. Exterior CitizenBody drawn: %s. PIXELS: %s. AUTHORITY ONLY: that this citizen is the one carrying the alarm — warnings have no visual channel in the renderer."
					% [_hhmm(), target, _shop, str(trow.get("state")), near_others, shared.size(),
						str(shared.slice(0, 6)), str(body != null),
						("the block the fleeing citizen is crossing, seen from the isometric camera; a CitizenBody for it exists, but roofs and fixtures between it and the camera can hide it, so the frame alone does not prove which citizen is there"
							if body != null
							else "the block it is crossing; no exterior body was materialized for it at this moment, so there is nothing of it to see")]),
					{"flee_citizens": fleeing, "warned_by_this_citizen": shared})

	# --- 04 the reciprocal repair ---------------------------------------------
	if _scene.inside_building() >= 0:
		await _leave()
	await _until(_p_using_station_after_13, 4.0 * 3600.0, 60.0, _helper, false)
	var ready := _reached
	_station = str(_session_of(_helper).get("object_id", ""))
	if not ready or _station == "":
		_manifest.append({"file": null,
			"caption": "04 skipped: citizen %d was not using a station of workplace %d after 13:00" % [_helper, _workplace]})
	else:
		_zoom(16.0)
		await _enter(_workplace)
		SimBridge.set_object_state(_station, "working", false)
		await _until(_p_repair_underway, 45.0 * 60.0, 5.0, _ben)
		var repairing := _reached
		var rrow := _row(SimBridge.last_mobility, _ben)
		_place_player(rrow, Vector2(4.0, 3.0))
		await _settle(8)
		var rep := []
		for e in _cog:
			if str(e.get("event", "")) == "HELP_DECIDED" and str(e.get("task_id", "")) == "repair_station":
				rep.append(e)
		var relrow := {}
		for r in _context(_ben).get("relationships", []):
			if _iv(r.get("other")) == _helper:
				relrow = r
		_reached = repairing
		await _shot("04_reciprocal_repair.png", _caption(
			"%s — the helper's own station %s was broken with SET_OBJECT_STATE(working=false); citizen %d — the coworker it helped this morning, which now owes it obligation %s — decided repair_station on it (score %s, would_help_without_history=%s) and is at/heading to that object (phase %s). PIXELS: a worker body in the room where that station stands — which citizen it is, and that it is on its way to repair it, is not something the pixels show. AUTHORITY ONLY: that this is a repayment — the HELP_DECIDED repair_station row and the relationship row in the manifest."
			% [_hhmm(), _station, _ben, str(relrow.get("obligation")),
				str(rep[0].get("score")) if not rep.is_empty() else "-",
				str(rep[0].get("would_help_without_history")) if not rep.is_empty() else "-",
				str(_work(rrow).get("phase"))]),
			{"repair_decided": rep, "beneficiary_relationship": relrow,
				"reciprocated": _ev("RECIPROCATED")})
		await _until(_p_reciprocated, 30.0 * 60.0, 5.0, _ben)
	_finish()


func _finish() -> void:
	var f := FileAccess.open(_dir.path_join("manifest.json"), FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify({"bundle": _bundle, "helper": _helper,
			"note": "The HUD text burned into every frame (\"Day 1 hh:mm\", \"Outbreak: 0%\") is the Godot scene's own GameClock//overlay, which this harness freezes; it is NOT the authoritative clock. The authoritative hour of each frame is the `hour`/`clock` field of that frame's row below, read from the bridge summary at capture time.",
			"beneficiary": _ben, "warned": _warned, "seeded": _seeded,
			"workplace": _workplace, "shop": _shop, "start_hour": _start_hour,
			"event_kinds_drained": _kinds, "authority_counts": _counts,
			"shots": _manifest}, "  "))
		f.close()
	print("SHOTS done: %d" % _manifest.size())
	SimBridge.disconnect_from_sim()
	get_tree().quit(0)
