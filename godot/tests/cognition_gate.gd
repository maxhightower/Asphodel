extends Node

## COGNITION GATE — NPC perception, memory, relationships and social decisions
## in the real city (ASPHODEL_NPC_COGNITION_SOCIAL_MEMORY_V1).
##
## Live Python bridge (protocol v7) + the REAL IsometricWorld scene + real Godot
## physics. Starts a Houston weekday at 05:00 and drives the certified scenario
## with the player standing inside the rooms where it happens:
##
##   * HELPING — a cashier decides, unprompted, to help a cleaner coworker
##     (HELP_DECIDED / HELP_STARTED / HELP_COMPLETED). The gate is inside the
##     staged interior of the workplace: both citizens have a CitizenBody at
##     their authoritative interior pose and the helper's body walks toward the
##     object the authority sent it to.
##   * RELATIONSHIP — after HELP_COMPLETED the beneficiary's relationship to the
##     helper carries obligation > 0 and more affinity than before (read from
##     GET_CITIZEN_CONTEXT; the gate never computes it).
##   * LOD — the player goes 1.5 km away for 10 game minutes and comes back:
##     bodies are destroyed and recreated, memories and relationships are not.
##   * THREAT — a customer of the busiest shop is seeded with a fast pathogen,
##     dies, rises and attacks. Witnesses in the attacked room flee; a cashier
##     in the next room is WARNED by shout and decides to avoid the room and the
##     building BEFORE it ever perceives the threat itself.
##   * RECIPROCITY — the helper's own station is broken with SET_OBJECT_STATE;
##     the cleaner it helped in the morning decides repair_station and
##     RECIPROCATED fires.
##   * SAVE/LOAD — the helper's whole context survives a round trip.
##
## Every check reads authoritative state (GET_COGNITION, GET_CITIZEN_CONTEXT,
## GET_WORK, GET_ROOMS, GET_OUTBREAK, the mobility block) plus bodies the scene
## did not place itself. THE GATE DECIDES NOTHING: it never picks a helper, a
## beneficiary, a warned citizen or a task — it reads them out of the
## authority's events. The only two things it asks for are the two external
## shocks the scenario needs (SEED_OUTBREAK on the lowest-id customer the
## authority reports inside the shop, SET_OBJECT_STATE on the station the
## authority says the helper is using).
##
##   godot --headless --path godot res://tests/CognitionGate.tscn -- \
##       --bundle houston --helper 70 --workplace 8470 --shop 15873 \
##       --trace /tmp/trace.json

var _bundle := "houston"
var _helper := 70                 # the citizen the player embodies and follows
var _workplace := 8470            # its retail workplace (the helping / reciprocity site)
var _shop := 15873                # the busiest shop (the threat site)
var _start_hour := 5.0
var _trace_path := "/tmp/asph_cognition_probe.json"
var _save_path := "/tmp/asph_cognition_gate_save.json"
var _game_dt := 1.0

var _fail := 0
var _log: Array[String] = []
var _rows: Array = []             # per-step authoritative rows of the followed citizens
var _cog: Array = []              # cognition events kept by this gate
var _kinds := {}                  # every cognition event kind seen -> count drained here
var _counts := {}                 # GET_COGNITION `counts`: the authority's persistent totals
var _cseq := 0
var _wseq := 0
var _work_events: Array = []
var _scene: Node3D
var _emb: EmbodiedMobility
var _stats := {}

# predicate state (named predicates instead of closures: GDScript lambdas may
# not span lines inside a call's argument list)
var _p_cid := -1
var _p_station := ""

## Kinds kept in full (the social spine of the milestone). Everything else is
## only counted, so the trace stays readable.
const KEEP := ["HELP_DECIDED", "HELP_STARTED", "HELP_COMPLETED", "RECIPROCATED",
	"WARNING_RECEIVED", "WARNING_SHARED", "AVOID_DECIDED", "AVOID_ROOM_DECIDED",
	"AVOID_ENDED", "PERCEIVED", "SOCIAL_ACTION"]
const MAX_KEPT := 9000
## Interior bodies follow the authoritative interior position with real physics
## at the WorkRuntime's walk speed; while a citizen is walking, its body is
## legitimately a stride or two behind the row of the second just advanced.
const LEASH_M := 5.0
const CONTEXT_KEYS := ["citizen_id", "location", "task", "goal", "needs", "health",
	"personality", "memories", "n_memories", "people_nearby", "relationships",
	"beliefs", "perceived_danger", "avoiding", "avoid_rooms_here", "recent_social"]


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
		elif args[i] == "--helper" and i + 1 < args.size():
			_helper = int(args[i + 1])
		elif args[i] == "--workplace" and i + 1 < args.size():
			_workplace = int(args[i + 1])
		elif args[i] == "--shop" and i + 1 < args.size():
			_shop = int(args[i + 1])
		elif args[i] == "--start-hour" and i + 1 < args.size():
			_start_hour = float(args[i + 1])
		elif args[i] == "--trace" and i + 1 < args.size():
			_trace_path = args[i + 1]
		elif args[i] == "--game-dt" and i + 1 < args.size():
			_game_dt = float(args[i + 1])
	await get_tree().physics_frame
	await _run()
	_finish()


# ------------------------------------------------------------------ helpers
## Null-safe int: authoritative event fields are routinely present and null
## (a building-less RECIPROCATED, a room-less warning), and int(null) aborts.
func _iv(v, d: int = -1) -> int:
	return d if v == null else int(v)


func _hour() -> float:
	return float(SimBridge.last_summary.get("hour", 0.0))


func _hhmm() -> String:
	var h := _hour()
	return "%02d:%02d" % [int(h), int(floor((h - floor(h)) * 60.0))]


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
	var r: Dictionary = SimBridge.get_citizen_context(cid)
	var c = r.get("context")
	return c if c is Dictionary else {}


func _relationship(ctx: Dictionary, other: int) -> Dictionary:
	for r in ctx.get("relationships", []):
		if _iv(r.get("other")) == other:
			return r
	return {}


func _fact_ids(ctx: Dictionary) -> Array:
	var out := []
	for f in ctx.get("memories", []):
		out.append(str(f.get("fact_id", "")))
	out.sort()
	return out


func _rel_digest(ctx: Dictionary) -> String:
	var out := []
	for r in ctx.get("relationships", []):
		out.append("%d:fam %s/aff %s/obl %s" % [_iv(r.get("other")), str(r.get("familiarity")),
			str(r.get("affinity")), str(r.get("obligation"))])
	out.sort()
	return str(out)


func _rel_partners(ctx: Dictionary) -> Array:
	var out := []
	for r in ctx.get("relationships", []):
		out.append(_iv(r.get("other")))
	out.sort()
	return out


func _familiarity_map(ctx: Dictionary) -> Dictionary:
	var out := {}
	for r in ctx.get("relationships", []):
		out[_iv(r.get("other"))] = float(r.get("familiarity", 0.0))
	return out


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


func _pull_cog() -> void:
	## Drain the cognition event log. The Python side keeps a 5000-row RING, so
	## every step drains with `since_seq` or events are lost before being read.
	var c: Dictionary = SimBridge.get_cognition(_cseq).get("cognition", {})
	for e in c.get("events", []):
		_cseq = max(_cseq, int(e.get("seq", 0)))
		var kind := str(e.get("event", ""))
		_kinds[kind] = int(_kinds.get(kind, 0)) + 1
		if KEEP.has(kind) and _cog.size() < MAX_KEPT:
			_cog.append(e)
	var counts = c.get("counts")
	if counts is Dictionary:
		_counts = counts


func _pull_work() -> void:
	## The work log too: OBJECT_UNAVAILABLE / STATE_CHANGE / CUSTOMER_ARRIVED are
	## what several cognition events are reactions to. This also refreshes
	## SimBridge.last_work, which is where the session views below read from.
	var w: Dictionary = SimBridge.get_work(_wseq).get("work", {})
	for e in w.get("events", []):
		_wseq = max(_wseq, int(e.get("seq", 0)))
		var bid := _iv(e.get("building_id"))
		if (bid == _workplace or bid == _shop) and _work_events.size() < MAX_KEPT:
			_work_events.append(e)


func _ev(kind: String, cid: int = -1) -> Array:
	var out := []
	for e in _cog:
		if str(e.get("event", "")) != kind:
			continue
		if cid >= 0 and _iv(e.get("citizen_id")) != cid:
			continue
		out.append(e)
	return out


func _first_seq(kind: String, cid: int) -> int:
	for e in _cog:
		if str(e.get("event", "")) == kind and _iv(e.get("citizen_id")) == cid:
			return int(e.get("seq", 0))
	return -1


func _record(block: Dictionary, tag: String, cids: Array) -> void:
	for cid in cids:
		var row := _row(block, int(cid))
		if row.is_empty():
			continue
		var w := _work(row)
		var out := {"t": float(block.get("t_s", 0.0)), "hour": _hour(), "tag": tag,
			"citizen_id": int(cid), "state": row.get("state"), "ax": row.get("x"),
			"ay": row.get("y"), "building_id": row.get("building_id"),
			"phase": w.get("phase"), "object_id": w.get("object_id"), "task": w.get("task"),
			"room_id": w.get("room_id"), "help_for": w.get("help_for")}
		var cb = _emb.body_of("cit:%d" % int(cid))
		if cb != null:
			out["bx"] = cb.global_position.x
			out["bz"] = cb.global_position.z
			out["interior_body"] = _emb.interior_body_ids().has("cit:%d" % int(cid))
		_rows.append(out)


## Where an authoritative interior point must render inside the staged interior
## (the ONLY transform: the scene's own stage offset).
func _staged(x: float, y: float) -> Vector3:
	return _scene.interior_offset() + Vector3(x, _emb.body_height, y)


func _body_gap(cid: int, row: Dictionary) -> float:
	var cb = _emb.body_of("cit:%d" % cid)
	if cb == null or row.is_empty():
		return -1.0
	var want := _staged(float(row["x"]), float(row["y"]))
	return Vector2(cb.global_position.x, cb.global_position.z).distance_to(Vector2(want.x, want.z))


func _object_row(bid: int, oid: String) -> Dictionary:
	for o in SimBridge.get_rooms(bid).get("objects", []):
		if str(o["object_id"]) == oid:
			return o
	return {}


func _sessions() -> Dictionary:
	var s = SimBridge.last_work.get("sessions", {})
	return s if s is Dictionary else {}


func _session_of(cid: int) -> Dictionary:
	var s = _sessions().get(str(cid), {})
	return s if s is Dictionary else {}


func _shop_customers() -> Array:
	## Every citizen the authority reports as a CUSTOMER session inside the shop,
	## lowest id first. The gate picks none of them — it reads the list.
	var out := []
	var sessions := _sessions()
	for k in sessions:
		var s = sessions[k]
		if s is Dictionary and str(s.get("kind", "")) == "customer" \
				and _iv(s.get("building_id")) == _shop:
			out.append(int(str(k)))
	out.sort()
	return out


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


## Advance until `pred` says so or the budget runs out. Every step drains both
## event logs, so no event is missed whatever the chunk size: the Python clock
## runs its own 1 s substeps regardless of how big a chunk is asked for.
func _until(pred: Callable, max_game_s: float, chunk_s: float, tag: String,
		follow: Array) -> bool:
	var t := 0.0
	var i := 0
	while t < max_game_s:
		var block := _step(chunk_s)
		if block.is_empty():
			break
		t += chunk_s
		i += 1
		if not follow.is_empty():
			_focus(_row(block, int(follow[0])))
		_pull_cog()
		_pull_work()
		if chunk_s <= 5.0 or i % 4 == 0:
			_record(block, tag, follow)
		if pred.call():
			return true
		await get_tree().physics_frame
	return false


# ------------------------------------------------------------ predicates
func _p_never() -> bool:
	return false


func _p_helper_at_workplace() -> bool:
	var r := _row(SimBridge.last_mobility, _helper)
	return int(r.get("building_id", -1)) == _workplace and str(r.get("state")) == "doing_activity"


func _p_help_decided() -> bool:
	for e in _cog:
		if str(e.get("event", "")) == "HELP_DECIDED" and str(e.get("task_id", "")).begins_with("help_"):
			return true
	return false


func _p_customer_in_shop() -> bool:
	return not _shop_customers().is_empty()


func _p_attacked_in_shop() -> bool:
	for e in _cog:
		if str(e.get("event", "")) == "PERCEIVED" and str(e.get("what", "")) == "attacked_by" \
				and _iv(e.get("building_id")) == _shop:
			return true
	return false


func _p_left_shop() -> bool:
	var r := _live_row(_p_cid)
	return int(r.get("building_id", -1)) != _shop or str(r.get("state")) != "doing_activity"


func _p_using_station_after_13() -> bool:
	if _hour() < 13.0:
		return false
	var s := _session_of(_helper)
	return str(s.get("phase", "")) == "using" and str(s.get("object_id", "")) != "" \
		and _iv(s.get("building_id")) == _workplace


func _p_reciprocated() -> bool:
	return not _ev("RECIPROCATED").is_empty()


func _p_back_on_station() -> bool:
	return str(_session_of(_p_cid).get("object_id", "")) == _p_station


# ------------------------------------------------------------------ the gate
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
	if not SimBridge.is_connected_to_sim():
		_ok("bridge_connected", false, "start python -m asphodel.bridge.server first")
		return
	_emb = _scene.get_embodied()
	if _emb == null:
		_ok("embodied_mobility_present", false, "the scene has no EmbodiedMobility node")
		return
	_emb.time_scale = 1.0 / max(get_physics_process_delta_time(), 0.001) * _game_dt
	GameClock.time_scale = 0.0     # this gate is the only driver of the clock

	# --- (a) protocol v7 + a world with cognition ----------------------------
	var started: Dictionary = SimBridge.last_summary
	var pv := int(started.get("protocol_version", -1))
	_ok("protocol_v7", pv == 7 and SimBridge.PROTOCOL_VERSION == 7,
		"START_WORLD reply protocol_version=%d, SimBridge speaks v%d (GET_COGNITION / GET_CITIZEN_CONTEXT)"
		% [pv, SimBridge.PROTOCOL_VERSION])
	var cog_on: bool = bool(started.get("cognition_enabled", false))
	_ok("world_started_with_cognition", cog_on and SimBridge.mobility_enabled and SimBridge.work_enabled,
		"START_WORLD by the scene at hour %s: cognition_enabled=%s mobility=%s work=%s, player_citizen=%s"
		% [str(started.get("hour")), str(cog_on), str(SimBridge.mobility_enabled),
			str(SimBridge.work_enabled), str(started.get("player_citizen"))])
	if not cog_on:
		return

	# --- (b) GET_CITIZEN_CONTEXT / GET_COGNITION shape ------------------------
	var ctx0 := _context(_helper)
	var missing := []
	for k in CONTEXT_KEYS:
		if not ctx0.has(k):
			missing.append(k)
	_ok("citizen_context_keys_present", missing.is_empty() and _iv(ctx0.get("citizen_id")) == _helper,
		"GET_CITIZEN_CONTEXT(%d) -> %d keys, missing %s; location=%s task=%s n_memories=%s relationships=%d"
		% [_helper, ctx0.size(), str(missing), str(ctx0.get("location")), str(ctx0.get("task")),
			str(ctx0.get("n_memories")), ctx0.get("relationships", []).size()])
	var snap0: Dictionary = SimBridge.get_cognition(0).get("cognition", {})
	_ok("cognition_snapshot_shape",
		snap0.has("events") and snap0.has("counts") and snap0.has("avoiding")
			and snap0.has("n_citizens_with_memory"),
		"GET_COGNITION v%s: %d citizens with memory, %d facts, %d relationships, event_seq=%s"
		% [str(snap0.get("version")), _iv(snap0.get("n_citizens_with_memory")),
			_iv(snap0.get("n_facts")), _iv(snap0.get("n_relationships")), str(snap0.get("event_seq"))])
	_pull_cog()
	_pull_work()

	# --- (c) the helper reaches its workplace; the player joins it -----------
	var at_work := await _until(_p_helper_at_workplace, 6.0 * 3600.0, 60.0, "commute", [_helper])
	var hrow := _row(SimBridge.last_mobility, _helper)
	_ok("helper_at_workplace", at_work,
		"citizen %d is %s in building %s at %s (role %s, task %s)"
		% [_helper, str(hrow.get("state")), str(hrow.get("building_id")), _hhmm(),
			str(_work(hrow).get("role")), str(_work(hrow).get("task"))])
	if not at_work:
		return
	await _enter(_workplace)

	# --- (d) the helping decision (HELP_DECIDED / STARTED / COMPLETED) -------
	# 1 s steps with the player inside the room, so the walk to the object the
	# helper was sent to is watched rather than stepped over.
	var got_help := await _until(_p_help_decided, 90.0 * 60.0, _game_dt, "await_help", [_helper])
	var decided := []
	for e in _cog:
		if str(e.get("event", "")) == "HELP_DECIDED" and str(e.get("task_id", "")).begins_with("help_"):
			decided.append(e)
	if decided.is_empty():
		_ok("help_decided", false,
			"no HELP_DECIDED with a help_* task in 90 game minutes from %s (kinds drained: %s)"
			% [_hhmm(), str(_kinds)])
		return
	var hd: Dictionary = decided[0]
	var helper := _iv(hd.get("citizen_id"))
	var ben := _iv(hd.get("beneficiary"))
	var hbid := _iv(hd.get("building_id"))
	var htask := str(hd.get("task_id", ""))
	var hobj := str(hd.get("object_id", ""))
	_ok("help_decided", got_help,
		"HELP_DECIDED at %s: citizen %d decided to help %d (%s / problem %s) on %s in building %d — score %s vs threshold %s, would_help_without_history=%s"
		% [_hhmm(), helper, ben, htask, str(hd.get("problem")), hobj, hbid,
			str(hd.get("score")), str(hd.get("threshold")), str(hd.get("would_help_without_history"))])
	# the relationship of the beneficiary toward the helper BEFORE the help lands
	var rel_before := _relationship(_context(ben), helper)
	var aff_before := float(rel_before.get("affinity", 0.0))
	var obl_before := float(rel_before.get("obligation", 0.0))

	# the player must be inside the building the authority chose
	if _scene.inside_building() != hbid:
		await _leave()
		await _enter(hbid)
	_step(_game_dt)
	_pull_cog()
	_pull_work()

	# --- (e) both citizens embodied in the staged interior -------------------
	var block: Dictionary = SimBridge.last_mobility
	var hrow2 := _row(block, helper)
	var brow := _row(block, ben)
	var hid := "cit:%d" % helper
	var bkey := "cit:%d" % ben
	var h_inside: bool = _emb.body_of(hid) != null and _emb.interior_body_ids().has(hid)
	var b_inside: bool = _emb.body_of(bkey) != null and _emb.interior_body_ids().has(bkey)
	# The bodies have been following the authority with real physics since the
	# player entered, so they are legitimately a stride behind the row of the
	# game second just advanced (LEASH_M). The strict "materialized exactly at
	# the authoritative pose" claim is made where it belongs: on the LOD
	# promotion below, where the body is created from the block it is measured
	# against (<= 0.5 m).
	_ok("helper_body_in_staged_interior", h_inside and _body_gap(helper, hrow2) <= LEASH_M,
		"CitizenBody %s inside interior %d at %s, %.2f m (leash %.1f m) from interior_offset + the authoritative (%s, %s); %d interior bodies"
		% [hid, _scene.inside_building(),
			str(_emb.body_of(hid).global_position) if h_inside else "none",
			_body_gap(helper, hrow2), LEASH_M, str(hrow2.get("x")), str(hrow2.get("y")),
			_emb.interior_bodies])
	_ok("beneficiary_body_in_same_interior", b_inside and _body_gap(ben, brow) <= LEASH_M,
		"the coworker being helped (citizen %d, task %s, room %s) has a body %.2f m (leash %.1f m) from its authoritative interior pose in the SAME staged interior"
		% [ben, str(_work(brow).get("task")), str(_work(brow).get("room_id")),
			_body_gap(ben, brow), LEASH_M])

	# --- (f) the helper's body walks toward the object it was sent to --------
	var orow := _object_row(hbid, hobj)
	var have_obj: bool = not orow.is_empty()
	var otarget := Vector2.ZERO
	if have_obj:
		otarget = Vector2(float(orow["x"]), float(orow["y"]))
	var d_start := -1.0
	var d_min := 1.0e9
	var walked := 0.0
	var to_object_frames := 0
	var help_for_seen := -1
	var last_pos := Vector3.ZERO
	var cb0 = _emb.body_of(hid)
	if cb0 != null:
		last_pos = cb0.global_position
	for i in range(900):
		var b2 := _step(_game_dt)
		if b2.is_empty():
			break
		_pull_cog()
		_pull_work()
		_record(b2, "helping", [helper, ben])
		var r2 := _row(b2, helper)
		_focus(r2)
		var w2 := _work(r2)
		var cb = _emb.body_of(hid)
		if cb != null:
			walked += Vector2(cb.global_position.x, cb.global_position.z).distance_to(
				Vector2(last_pos.x, last_pos.z))
			last_pos = cb.global_position
			if have_obj and str(w2.get("task", "")) == htask:
				var want := _staged(otarget.x, otarget.y)
				var d := Vector2(cb.global_position.x, cb.global_position.z).distance_to(
					Vector2(want.x, want.z))
				if d_start < 0.0:
					d_start = d
				d_min = min(d_min, d)
		if str(w2.get("phase", "")) == "to_object" and str(w2.get("task", "")) == htask:
			to_object_frames += 1
		# help_for lives on the WorkRuntime SESSION (GET_WORK), not on the
		# mobility row's `work` block — the renderer cannot tell a help task
		# from an ordinary one out of the movement block alone.
		if _iv(_session_of(helper).get("help_for")) >= 0:
			help_for_seen = _iv(_session_of(helper).get("help_for"))
		if not _ev("HELP_COMPLETED", helper).is_empty():
			break
		await get_tree().physics_frame
	_pull_cog()
	var started_evs := _ev("HELP_STARTED", helper)
	var done_evs := _ev("HELP_COMPLETED", helper)
	_ok("help_started_and_completed", not started_evs.is_empty() and not done_evs.is_empty(),
		"HELP_STARTED=%d HELP_COMPLETED=%d for citizen %d (task %s on %s); while the task ran the GET_WORK session carried help_for=%d (the mobility row's work block does not carry help_for at all: %s)"
		% [started_evs.size(), done_evs.size(), helper, htask, hobj, help_for_seen,
			str(_work(_row(SimBridge.last_mobility, helper)).has("help_for"))])
	if have_obj and d_start >= 0.0:
		_ok("helper_body_moved_toward_the_object", d_start - d_min >= 1.0,
			"the CitizenBody closed %.2f m on %s (%.2f m -> %.2f m; authoritative object position (%.1f, %.1f)) and walked %.1f m inside the staged interior over %d to_object frames"
			% [d_start - d_min, hobj, d_start, d_min, otarget.x, otarget.y, walked, to_object_frames])
	else:
		_info("helper_body_moved_toward_the_object",
			"the help object %s was not in GET_ROOMS(%d), or no body existed while the task ran; the body walked %.1f m — reported, not claimed"
			% [hobj, hbid, walked])

	# --- (g) the relationship the help created -------------------------------
	var rel_after := _relationship(_context(ben), helper)
	var aff_after := float(rel_after.get("affinity", 0.0))
	var obl_after := float(rel_after.get("obligation", 0.0))
	_ok("beneficiary_owes_the_helper", obl_after > 0.0 and aff_after > aff_before,
		"GET_CITIZEN_CONTEXT(%d) relationship -> %d after HELP_COMPLETED: obligation %.4f (was %.4f), affinity %.4f (was %.4f), trust %s, familiarity %s, origin %s"
		% [ben, helper, obl_after, obl_before, aff_after, aff_before, str(rel_after.get("trust")),
			str(rel_after.get("familiarity")), str(rel_after.get("origin"))])

	# --- (h) LOD: 1.5 km away for 10 game minutes, then back -----------------
	var ctx_before := _context(helper)
	var rels_before := _rel_digest(ctx_before)
	var facts_before := _fact_ids(ctx_before)
	var n_before := _iv(ctx_before.get("n_memories"), 0)
	var here := _live_row(helper)
	await _leave()
	var far := Vector2(float(here["x"]) + 1500.0, float(here["y"]))
	_scene.teleport_player(far.x, far.y)
	SimBridge.focus_xy = far
	SimBridge.has_focus_xy = true
	var far_t := 0.0
	while far_t < 10.0 * 60.0:
		var b3 := _step(60.0)
		if b3.is_empty():
			break
		far_t += 60.0
		SimBridge.focus_xy = far
		_pull_cog()
		_pull_work()
		_record(b3, "far", [helper])
		await get_tree().physics_frame
	var body_far = _emb.body_of(hid)
	_ok("no_body_while_far", body_far == null and _emb.interior_bodies == 0,
		"player 1.5 km away for 10 game minutes with the interior left: no CitizenBody for citizen %d, %d interior bodies, %d demotions so far"
		% [helper, _emb.interior_bodies, _emb.demotions])
	var back := _live_row(helper)
	_scene.teleport_player(float(back["x"]) + 8.0, float(back["y"]) + 8.0)
	SimBridge.focus_xy = Vector2(float(back["x"]), float(back["y"]))
	var back_bid := int(back.get("building_id", -1))
	if back_bid >= 0:
		await _enter(back_bid)
	_step(_game_dt)
	_pull_cog()
	var ctx_after := _context(helper)
	var n_after := _iv(ctx_after.get("n_memories"), 0)
	var facts_after := _fact_ids(ctx_after)
	var kept := 0
	for f in facts_before:
		if facts_after.has(f):
			kept += 1
	var rels_after := _rel_digest(ctx_after)
	# The authority keeps running while nobody is watching, so a relationship
	# may legitimately have GROWN over those 10 game minutes; what must not
	# happen is that a partner is lost or a tie is reset by the demotion.
	var fam_before := _familiarity_map(ctx_before)
	var fam_after := _familiarity_map(ctx_after)
	var lost := []
	var regressed := []
	for other in fam_before:
		if not fam_after.has(other):
			lost.append(other)
		elif float(fam_after[other]) < float(fam_before[other]) - 1e-6:
			regressed.append(other)
	_ok("lod_roundtrip_preserves_cognition",
		n_after >= n_before and kept == facts_before.size() and lost.is_empty() and regressed.is_empty(),
		"citizen %d across demotion+promotion: n_memories %d -> %d, %d/%d salient fact ids still present, %d relationships kept (lost %s, weakened %s); before %s after %s"
		% [helper, n_before, n_after, kept, facts_before.size(), _rel_partners(ctx_before).size(),
			str(lost), str(regressed), rels_before, rels_after])
	var promoted_row := _row(SimBridge.last_mobility, helper)
	var gap := _body_gap(helper, promoted_row)
	if _scene.inside_building() >= 0:
		_ok("body_recreated_at_authoritative_pose",
			_emb.body_of(hid) != null and gap >= 0.0 and gap <= 0.5,
			"the CitizenBody for citizen %d is recreated %.3f m from its authoritative interior pose after the round trip (%d promotions)"
			% [helper, gap, _emb.promotions])
	else:
		_info("body_recreated_at_authoritative_pose",
			"citizen %d was not inside a building on return (state %s, building %s) — no interior body to re-create"
			% [helper, str(promoted_row.get("state")), str(promoted_row.get("building_id"))])

	# --- (i) THREAT: seed the first customer the authority puts in the shop --
	if _scene.inside_building() >= 0:
		await _leave()
	var seeded := -1
	var saw_customer := await _until(_p_customer_in_shop, 6.0 * 3600.0, 60.0, "await_customers", [])
	var customers := _shop_customers()
	if not (saw_customer and not customers.is_empty()):
		_ok("threat_seeded_on_a_shop_customer", false,
			"no customer session at shop %d in the window (hour %s) — nothing to seed" % [_shop, _hhmm()])
		return
	seeded = int(customers[0])
	var sr: Dictionary = SimBridge.seed_outbreak("classic_zombie_fast", seeded)
	_ok("threat_seeded_on_a_shop_customer", sr.get("ok", false),
		"at %s the authority reports customer sessions %s inside shop %d; SEED_OUTBREAK(classic_zombie_fast, %d) accepted=%s"
		% [_hhmm(), str(customers), _shop, seeded, str(sr.get("ok"))])
	await _enter(_shop)
	_step(_game_dt)
	# who the renderer has bodies for inside the shop BEFORE anything happens
	var bodies_before_attack := []
	for id in _emb.interior_body_ids():
		bodies_before_attack.append(str(id))
	bodies_before_attack.sort()
	var attacked := await _until(_p_attacked_in_shop, 40.0 * 60.0, 5.0, "await_attack", [seeded])
	var attacks := []
	for e in _cog:
		if str(e.get("event", "")) == "PERCEIVED" and str(e.get("what", "")) == "attacked_by" \
				and _iv(e.get("building_id")) == _shop:
			attacks.append(e)
	_ok("undead_attacks_inside_the_shop", attacked and not attacks.is_empty(),
		"at %s the risen citizen %d attacked inside shop %d: first PERCEIVED attacked_by is citizen %s in room %s (%d attacked_by rows)"
		% [_hhmm(), seeded, _shop,
			str(attacks[0].get("citizen_id")) if not attacks.is_empty() else "none",
			str(attacks[0].get("room_id")) if not attacks.is_empty() else "none", attacks.size()])
	# --- (j) the warned citizen: warned first, avoided BEFORE perceiving -----
	# Derived from the authority's own rows: a citizen that received a warning
	# while its goal was still the schedule, decided to avoid the building on
	# somebody else's word (first_hand false), and only afterwards perceived
	# anything itself. Sampled IMMEDIATELY — the attack and the shout wave land
	# in the same drained batch, and minutes later the same citizen has usually
	# witnessed the attack itself and is running on an emergency goal, which
	# would hide the second-hand decision this check is about.
	var warned := -1
	var wr := {}
	var av := {}
	for e in _cog:
		if str(e.get("event", "")) != "AVOID_DECIDED" or _iv(e.get("building_id")) != _shop:
			continue
		if bool(e.get("first_hand", true)):
			continue
		var cid := _iv(e.get("citizen_id"))
		var p_seq := _first_seq("PERCEIVED", cid)
		var w_seq := -1
		var w_row := {}
		for x in _cog:
			if str(x.get("event", "")) == "WARNING_RECEIVED" and _iv(x.get("citizen_id")) == cid:
				w_seq = int(x.get("seq", 0))
				w_row = x
				break
		if w_seq < 0 or w_seq >= int(e.get("seq", 0)):
			continue
		if p_seq >= 0 and p_seq < int(e.get("seq", 0)):
			continue
		warned = cid
		wr = w_row
		av = e
		break
	var wctx0 := {}
	var wrow_at_decision := {}
	if warned >= 0:
		wctx0 = _context(warned)
		wrow_at_decision = _row(SimBridge.last_mobility, warned)
	if warned < 0:
		_ok("warned_before_perceiving", false,
			"no citizen decided to avoid shop %d second-hand before perceiving the threat itself (AVOID_DECIDED rows drained: %d)"
			% [_shop, _ev("AVOID_DECIDED").size()])
	else:
		_p_cid = warned
		_ok("warned_before_perceiving", true,
			"citizen %d: WARNING_RECEIVED seq %s (sender %s, channel %s, goal_before %s, confidence %s, hops %s) -> AVOID_DECIDED seq %s (first_hand %s, danger %s, threshold %s, sources %s) -> its own first PERCEIVED seq %s"
			% [warned, str(wr.get("seq")), str(wr.get("sender")), str(wr.get("channel")),
				str(wr.get("goal_before")), str(wr.get("confidence")), str(wr.get("hops")),
				str(av.get("seq")), str(av.get("first_hand")), str(av.get("danger")),
				str(av.get("threshold")), str(av.get("sources")), str(_first_seq("PERCEIVED", warned))])
		var sched: bool = str(wr.get("goal_before", "")) == "schedule" and str(wr.get("channel", "")) == "shout"
		_ok("warning_interrupted_a_schedule_goal", sched,
			"the first warning that reached citizen %d arrived by %s while its active goal source was %s"
			% [warned, str(wr.get("channel")), str(wr.get("goal_before"))])
		var rooms_ev := _ev("AVOID_ROOM_DECIDED", warned)
		_ok("room_avoidance_decided", not rooms_ev.is_empty(),
			"AVOID_ROOM_DECIDED for citizen %d in building %s: rooms %s (it was in room %s), dangers %s"
			% [warned, str(rooms_ev[0].get("building_id")) if not rooms_ev.is_empty() else "-",
				str(rooms_ev[0].get("rooms")) if not rooms_ev.is_empty() else "-",
				str(rooms_ev[0].get("room_here")) if not rooms_ev.is_empty() else "-",
				str(rooms_ev[0].get("dangers")) if not rooms_ev.is_empty() else "-"])
		# the goal it is running on within seconds of the decision
		var g0 = wctx0.get("goal")
		var g0src := (str(g0.get("source", "")) if g0 is Dictionary else "")
		_ok("warned_citizen_acts_on_a_belief_goal", g0src == "belief",
			"seconds after AVOID_DECIDED, citizen %d is state %s in building %s and the goal driving it comes from source \"%s\" (%s); avoiding %s, avoid_rooms_here %s"
			% [warned, str(wrow_at_decision.get("state")), str(wrow_at_decision.get("building_id")),
				g0src, (str(g0.get("reason")) if g0 is Dictionary else "-"),
				str(wctx0.get("avoiding")), str(wctx0.get("avoid_rooms_here"))])
		# let the shout / call wave play out, then watch it walk
		await _until(_p_never, 3.0 * 60.0, 5.0, "threat", [warned])
		# --- (k) the warned citizen physically leaves ------------------------
		var wrow0 := wrow_at_decision
		var was_inside: bool = int(wrow0.get("building_id", -1)) == _shop
		var left := await _until(_p_left_shop, 25.0 * 60.0, 10.0, "warned_leaves", [warned])
		var wrow := _live_row(warned)
		var wctx := _context(warned)
		var goal = wctx.get("goal")
		var gsource := (str(goal.get("source", "")) if goal is Dictionary else "")
		var body_gone: bool = _emb.body_of("cit:%d" % warned) == null \
			or not _emb.interior_body_ids().has("cit:%d" % warned)
		_ok("warned_citizen_leaves_its_activity", left,
			"citizen %d (was %s in building %s) is now state %s in building %s at %s; its active goal source is %s (%s), avoiding %s; its body is gone from the staged shop interior: %s"
			% [warned, str(wrow0.get("state")), str(wrow0.get("building_id")), str(wrow.get("state")),
				str(wrow.get("building_id")), _hhmm(), gsource,
				(str(goal.get("reason")) if goal is Dictionary else "-"),
				str(wctx.get("avoiding")), str(body_gone)])
		_info("warned_citizen_goal_after_the_walk_out",
			"once outside, citizen %d is running on a %s goal (%s) — by then it had also perceived the threat itself, so this later goal is reported, not claimed as the second-hand decision"
			% [warned, gsource, str(wctx.get("avoiding"))])
		var had_body: bool = bodies_before_attack.has("cit:%d" % warned)
		_ok("warned_citizen_body_left_the_interior", had_body and body_gone,
			"citizen %d had a CitizenBody in the staged interior of shop %d before the attack (%s of %d bodies) and has none there now (%s); it was %s inside the shop when the gate sampled it at the decision"
			% [warned, _shop, str(had_body), bodies_before_attack.size(), str(body_gone),
				"still" if was_inside else "no longer"])
	# witnesses fleeing, and a warning that travelled by telephone
	var ob: Dictionary = SimBridge.get_outbreak(0).get("outbreak", {})
	var flees := 0
	for e in ob.get("events", []):
		if str(e.get("event", "")) == "FLEE" and _iv(e.get("building_id")) == _shop:
			flees += 1
	if flees > 0:
		_ok("witnesses_fled_the_attacked_room", true,
			"%d FLEE events inside shop %d (the outbreak runtime's own, read through GET_OUTBREAK)" % [flees, _shop])
	else:
		_info("witnesses_fled_the_attacked_room",
			"no FLEE event inside shop %d was drained in this window" % _shop)
	var calls := []
	for e in _cog:
		if str(e.get("event", "")) == "WARNING_RECEIVED" and str(e.get("channel", "")) == "call":
			calls.append(e)
	if not calls.is_empty():
		_ok("warning_carried_by_a_call", true,
			"%d WARNING_RECEIVED rows arrived by channel \"call\", e.g. citizen %s was called by %s (goal_before %s, hops %s) — somebody nowhere near the shop learned of it"
			% [calls.size(), str(calls[0].get("citizen_id")), str(calls[0].get("sender")),
				str(calls[0].get("goal_before")), str(calls[0].get("hops"))])
	else:
		_info("warning_carried_by_a_call", "no call-channel warning was drained in this window")

	# --- (l) RECIPROCITY: break the helper's own station ---------------------
	if _scene.inside_building() >= 0:
		await _leave()
	var ready_to_break := await _until(_p_using_station_after_13, 4.0 * 3600.0, 60.0, "await_13h", [helper])
	var sess := _session_of(helper)
	var station := str(sess.get("object_id", ""))
	if not ready_to_break or station == "":
		_ok("reciprocity_setup", false,
			"citizen %d was not using a station of workplace %d after 13:00 (hour %s, session %s) — the reciprocity shock has no target"
			% [helper, _workplace, _hhmm(), str(sess)])
	else:
		await _enter(_workplace)
		var br: Dictionary = SimBridge.set_object_state(station, "working", false)
		_ok("reciprocity_setup", br.get("ok", false),
			"at %s citizen %d was using its assigned station %s (task %s); SET_OBJECT_STATE(%s, working, false) accepted=%s"
			% [_hhmm(), helper, station, str(sess.get("task_id")), station, str(br.get("ok"))])
		var reciprocated := await _until(_p_reciprocated, 45.0 * 60.0, 5.0, "reciprocity", [ben, helper])
		var repairs := []
		for e in _cog:
			if str(e.get("event", "")) == "HELP_DECIDED" and str(e.get("task_id", "")) == "repair_station":
				repairs.append(e)
		_ok("repair_station_decided", not repairs.is_empty(),
			"HELP_DECIDED repair_station at %s: citizen %s decided to repair %s for %s (score %s, would_help_without_history=%s)"
			% [_hhmm(), str(repairs[0].get("citizen_id")) if not repairs.is_empty() else "none",
				str(repairs[0].get("object_id")) if not repairs.is_empty() else "-",
				str(repairs[0].get("beneficiary")) if not repairs.is_empty() else "-",
				str(repairs[0].get("score")) if not repairs.is_empty() else "-",
				str(repairs[0].get("would_help_without_history")) if not repairs.is_empty() else "-"])
		var rec := _ev("RECIPROCATED")
		_ok("reciprocated_fired", reciprocated and not rec.is_empty(),
			"RECIPROCATED at %s: citizen %s discharged its obligation to %s with task %s (%d rows)"
			% [_hhmm(), str(rec[0].get("citizen_id")) if not rec.is_empty() else "none",
				str(rec[0].get("beneficiary")) if not rec.is_empty() else "-",
				str(rec[0].get("task_id")) if not rec.is_empty() else "-", rec.size()])
		var fixed := _object_row(_workplace, station)
		var st = fixed.get("state", {})
		var working = st.get("working") if st is Dictionary else null
		_ok("station_working_again", working == true,
			"%s state after the repair: %s (holders %s)"
			% [station, str(st), str(fixed.get("holders"))])
		_p_cid = helper
		_p_station = station
		var returned := await _until(_p_back_on_station, 45.0 * 60.0, 10.0, "await_return", [helper])
		var s2 := _session_of(helper)
		if returned:
			_ok("helper_returns_to_the_repaired_station", true,
				"citizen %d is back on %s at %s (task %s, phase %s)"
				% [helper, station, _hhmm(), str(s2.get("task_id")), str(s2.get("phase"))])
		else:
			_info("helper_returns_to_the_repaired_station",
				"citizen %d had not returned to %s within 45 game minutes of the repair (it is on %s, task %s, phase %s at %s) — reported, not claimed"
				% [helper, station, str(s2.get("object_id")), str(s2.get("task_id")),
					str(s2.get("phase")), _hhmm()])
		var obl_end := float(_relationship(_context(ben), helper).get("obligation", -1.0))
		_info("obligation_after_reciprocation",
			"the obligation of citizen %d toward %d reads %.4f after RECIPROCATED (it was %.4f right after the morning help)"
			% [ben, helper, obl_end, obl_after])

	# --- (m) save / load keeps the context identical -------------------------
	var before_ctx := _context(helper)
	var sr2: Dictionary = SimBridge.save(_save_path)
	var lr: Dictionary = SimBridge.load(_save_path)
	var after_ctx := _context(helper)
	var same: bool = sr2.get("ok", false) and lr.get("ok", false) \
		and JSON.stringify(before_ctx) == JSON.stringify(after_ctx)
	_ok("saveload_context_identical", same,
		"SAVE+LOAD around citizen %d: n_memories %s -> %s, relationships %d -> %d, beliefs %d -> %d, whole GET_CITIZEN_CONTEXT identical=%s"
		% [helper, str(before_ctx.get("n_memories")), str(after_ctx.get("n_memories")),
			before_ctx.get("relationships", []).size(), after_ctx.get("relationships", []).size(),
			before_ctx.get("beliefs", []).size(), after_ctx.get("beliefs", []).size(),
			str(JSON.stringify(before_ctx) == JSON.stringify(after_ctx))])

	_stats = {"event_kinds": _kinds, "authority_counts": _counts, "helper": helper,
		"beneficiary": ben, "warned": warned, "seeded": seeded, "workplace": _workplace,
		"shop": _shop, "help_task": htask, "help_object": hobj,
		"interior_bodies": _emb.interior_bodies, "promotions": _emb.promotions,
		"demotions": _emb.demotions, "walked_m": walked, "hour_end": _hour()}
	SimBridge.disconnect_from_sim()


func _finish() -> void:
	var n := 0
	for l in _log:
		if l.begins_with("PASS") or l.begins_with("FAIL"):
			n += 1
	if n < 14:
		_ok("all_checks_ran", false, "only %d PASS/FAIL checks ran" % n)
	print("\n==== COGNITION GATE RESULTS (%s, helper %d, workplace %d, shop %d) ===="
		% [_bundle, _helper, _workplace, _shop])
	for l in _log:
		print(l)
	print("==== %s (%d failure(s)) ====" % ["PASS" if _fail == 0 else "FAIL", _fail])
	var f := FileAccess.open(_trace_path, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify({"version": 1, "bundle": _bundle, "helper": _helper,
			"workplace": _workplace, "shop": _shop, "start_hour": _start_hour,
			"game_dt": _game_dt, "results": _log, "stats": _stats,
			"cognition_events": _cog, "work_events": _work_events, "rows": _rows}))
		f.close()
		print("TRACE saved: %s (%d rows, %d cognition events)" % [_trace_path, _rows.size(), _cog.size()])
	get_tree().quit(1 if _fail > 0 else 0)
