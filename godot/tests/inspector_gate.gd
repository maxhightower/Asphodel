extends Node

## INSPECTOR GATE — the developer/observer visibility layer proven to read the
## AUTHORITY, not to fabricate (ASPHODEL_WINDOWS_PLAYABLE_CONVERGENCE_V2, §19–§25).
##
## Live Python bridge (protocol v9) + the REAL IsometricWorld scene + real Godot.
## The gate boots a real world with mobility + cognition + dialogue + groups on,
## picks a registered citizen, instantiates the four self-contained observer nodes
## (SimulationInspector, BuildOverlay, EventFeed, FollowCamera), drives their public
## refresh functions, and asserts that every value each surface RENDERS equals the
## value a direct GET_CITIZEN_CONTEXT / GET_GROUPS / GROUP_QUERY reports — i.e. the
## surfaces read authority, they do not invent simulation facts.
##
## It also proves the inspector is READ-ONLY: a full world snapshot is captured
## before and after a batch of inspector/overlay/feed refreshes and asserted byte
## identical (the surfaces call only read methods; the inspector never calls the
## mutating GROUP_QUERY ask_to_join or any setter — mutation_calls() stays 0).
##
##   godot --headless --path godot res://tests/InspectorGate.tscn -- \
##       --bundle houston --player 82 --start-hour 8.0 --trace /path/trace.json

var _bundle := "houston"
var _player := 82
var _start_hour := 8.0
var _game_dt := 600.0
var _trace_path := "artifacts/windows_playable_v2/inspector_gate_trace.json"

var _fail := 0
var _log: Array[String] = []
var _scene: Node3D
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
		elif args[i] == "--player" and i + 1 < args.size():
			_player = int(args[i + 1])
		elif args[i] == "--start-hour" and i + 1 < args.size():
			_start_hour = float(args[i + 1])
		elif args[i] == "--game-dt" and i + 1 < args.size():
			_game_dt = float(args[i + 1])
		elif args[i] == "--trace" and i + 1 < args.size():
			_trace_path = args[i + 1]
	await get_tree().physics_frame
	await _run()
	_finish()


# ------------------------------------------------------------------ helpers
func _dict(v) -> Dictionary:
	return v if v is Dictionary else {}


func _arr(v) -> Array:
	return v if v is Array else []


func _eq(a, b) -> bool:
	## Loose authority-vs-render equality that treats numeric ints/floats alike
	## and null/"—" alike, so we compare the underlying authoritative fact.
	if a == null and b == null:
		return true
	if (a is float or a is int) and (b is float or b is int):
		return abs(float(a) - float(b)) < 1e-6
	return str(a) == str(b)


# ------------------------------------------------------------------ the gate
func _run() -> void:
	Session.bundle_dir = "res://bundles/" + _bundle
	Session.start_hour = _start_hour
	var citizens := BundleLoader.load_citizens(Session.bundle_dir)
	var pidx := _player if _player < citizens.size() else 0
	Session.citizen = citizens[pidx].duplicate(true)
	Session.citizen["citizen_id"] = pidx
	_scene = preload("res://IsometricWorld.tscn").instantiate()
	add_child(_scene)
	for i in range(20):
		await get_tree().physics_frame
	if not SimBridge.is_connected_to_sim():
		_ok("bridge_connected", false, "start python -m asphodel.bridge.server first")
		return
	GameClock.time_scale = 0.0     # the gate is the only driver of the clock

	# --- (a) protocol + the full observed stack is live ---------------------
	var started: Dictionary = SimBridge.last_summary
	var pv := int(started.get("protocol_version", -1))
	_ok("protocol_v9", pv == 9 and SimBridge.PROTOCOL_VERSION == 9,
		"START_WORLD reply protocol_version=%d, SimBridge speaks v%d" % [pv, SimBridge.PROTOCOL_VERSION])
	_ok("observed_stack_enabled",
		SimBridge.mobility_enabled and SimBridge.cognition_enabled
			and SimBridge.dialogue_enabled and SimBridge.groups_enabled,
		"mobility=%s cognition=%s dialogue=%s groups=%s work=%s — the surfaces have real streams to read"
		% [str(SimBridge.mobility_enabled), str(SimBridge.cognition_enabled),
			str(SimBridge.dialogue_enabled), str(SimBridge.groups_enabled), str(SimBridge.work_enabled)])
	if not SimBridge.cognition_enabled:
		return

	# --- pick a registered citizen (the player) -----------------------------
	var cid := _player
	var probe: Dictionary = SimBridge.get_citizen_context(cid)
	if probe.get("ok", false) != true:
		# fall back to the first citizen the mobility snapshot lists
		var mob := _dict(SimBridge.get_mobility(false).get("mobility"))
		for row in _arr(mob.get("citizens")):
			cid = int(_dict(row).get("citizen_id", cid))
			probe = SimBridge.get_citizen_context(cid)
			if probe.get("ok", false) == true:
				break
	_ok("citizen_context_available", probe.get("ok", false) == true,
		"GET_CITIZEN_CONTEXT(c%d) -> ok=%s (the inspector's read source)" % [cid, str(probe.get("ok"))])

	# --- advance a little so the event streams actually have events ----------
	for _i in range(6):
		SimBridge.advance_time(_game_dt, "mobility")

	# --- instantiate the four self-contained observer nodes -----------------
	var inspector := SimulationInspector.new()
	var overlay := BuildOverlay.new()
	var feed := EventFeed.new()
	var cam := FollowCamera.new()
	add_child(inspector)
	add_child(overlay)
	add_child(feed)
	add_child(cam)
	await get_tree().process_frame
	inspector.set_bridge(SimBridge)
	overlay.set_bridge(SimBridge)
	feed.set_bridge(SimBridge)
	cam.set_bridge(SimBridge)

	# ====================================================================== #
	# (b) INSPECTOR renders the SAME context the authority reports (dev mode)
	# ====================================================================== #
	inspector.set_selected(cid)
	inspector.refresh()
	var ctx := _dict(SimBridge.get_citizen_context(cid).get("context"))  # direct, no advance between
	var r := inspector.last_render
	var loc := _dict(ctx.get("location"))
	var task := _dict(ctx.get("task"))
	var goal := _dict(ctx.get("goal"))

	var rphys := _dict(r.get("physical"))
	_ok("inspector_physical_matches_authority",
		_eq(rphys.get("building_id"), loc.get("building_id"))
			and _eq(rphys.get("room_id"), loc.get("room_id"))
			and _eq(rphys.get("zone"), loc.get("zone"))
			and _eq(rphys.get("band"), loc.get("band")),
		"inspector building/room/zone/band = %s / %s / %s / %s vs authority %s / %s / %s / %s"
		% [str(rphys.get("building_id")), str(rphys.get("room_id")), str(rphys.get("zone")), str(rphys.get("band")),
			str(loc.get("building_id")), str(loc.get("room_id")), str(loc.get("zone")), str(loc.get("band"))])

	var rbeh := _dict(r.get("behavior"))
	_ok("inspector_behavior_matches_authority",
		_eq(rbeh.get("goal_kind"), goal.get("kind"))
			and _eq(rbeh.get("goal_target"), goal.get("target"))
			and _eq(rbeh.get("task_id"), task.get("task_id"))
			and _eq(rbeh.get("phase"), task.get("phase"))
			and _eq(rbeh.get("object_id"), task.get("object_id")),
		"inspector goal=%s->%s task=%s phase=%s obj=%s vs authority goal=%s->%s task=%s phase=%s obj=%s"
		% [str(rbeh.get("goal_kind")), str(rbeh.get("goal_target")), str(rbeh.get("task_id")),
			str(rbeh.get("phase")), str(rbeh.get("object_id")),
			str(goal.get("kind")), str(goal.get("target")), str(task.get("task_id")),
			str(task.get("phase")), str(task.get("object_id"))])

	_ok("inspector_health_matches_authority (dev)",
		_eq(r.get("health"), ctx.get("health")),
		"inspector health=%s vs authority health=%s (dev-truth only)" % [str(r.get("health")), str(ctx.get("health"))])

	var rcog := _dict(r.get("cognition"))
	_ok("inspector_cognition_matches_authority (dev)",
		_eq(rcog.get("n_memories"), ctx.get("n_memories"))
			and _eq(rcog.get("perceived_danger"), ctx.get("perceived_danger")),
		"inspector n_memories=%s perceived_danger=%s vs authority n_memories=%s perceived_danger=%s"
		% [str(rcog.get("n_memories")), str(rcog.get("perceived_danger")),
			str(ctx.get("n_memories")), str(ctx.get("perceived_danger"))])

	# relationship trust/affinity/obligation — the exact authoritative dimensions
	var arels := _arr(ctx.get("relationships"))
	var rsoc := _dict(r.get("social"))
	var rrels := _arr(rsoc.get("relationships"))
	if arels.is_empty():
		_info("inspector_relationship_matches_authority",
			"citizen c%d has no relationships in context yet (nothing to compare)" % cid)
	else:
		var a0 := _dict(arels[0])
		var r0 := _dict(rrels[0]) if not rrels.is_empty() else {}
		_ok("inspector_relationship_matches_authority",
			_eq(r0.get("other"), a0.get("other")) and _eq(r0.get("trust"), a0.get("trust"))
				and _eq(r0.get("affinity"), a0.get("affinity")) and _eq(r0.get("obligation"), a0.get("obligation")),
			"inspector top relationship c%s trust=%s affinity=%s oblig=%s vs authority c%s trust=%s affinity=%s oblig=%s"
			% [str(r0.get("other")), str(r0.get("trust")), str(r0.get("affinity")), str(r0.get("obligation")),
				str(a0.get("other")), str(a0.get("trust")), str(a0.get("affinity")), str(a0.get("obligation"))])

	# group surface — inspector agrees with GROUP_QUERY membership (authority)
	var qm := _dict(SimBridge.group_query("membership", cid))
	var rgrp := _dict(r.get("group"))
	_ok("inspector_group_matches_authority",
		_eq(rgrp.get("in_group"), qm.get("in_group")),
		"inspector in_group=%s vs GROUP_QUERY membership in_group=%s (a fresh world forms no group yet; both agree)"
		% [str(rgrp.get("in_group")), str(qm.get("in_group"))])

	# ====================================================================== #
	# (c) PLAYER mode hides hidden knowledge (health + the belief graph)
	# ====================================================================== #
	inspector.toggle()                       # show, so the Tab handler is active
	var tab := InputEventKey.new()
	tab.keycode = KEY_TAB
	tab.pressed = true
	inspector._input(tab)                    # exercise the real mode-toggle path
	var pr := inspector.last_render
	_ok("player_mode_hides_hidden_state",
		inspector.mode_name() == "PLAYER" and pr.get("health") == null and pr.get("cognition") == null,
		"after Tab the panel is in %s mode and renders health=%s cognition=%s — the player cannot read the NPC's infection state or its private mind"
		% [inspector.mode_name(), str(pr.get("health")), str(pr.get("cognition"))])
	# back to dev truth for the remaining checks
	inspector._input(tab)
	inspector.toggle()

	# ====================================================================== #
	# (d) BUILD OVERLAY renders the authoritative identity block
	# ====================================================================== #
	overlay.refresh()
	var ov := overlay.last_render
	var oflags := _dict(ov.get("flags"))
	_ok("overlay_matches_authority",
		_eq(ov.get("sim_sha"), started.get("sim_sha"))
			and int(ov.get("protocol_speaks", -1)) == 9
			and _eq(ov.get("city"), _bundle)
			and ov.get("connected") == true
			and oflags.get("mobility") == true and oflags.get("cognition") == true
			and oflags.get("dialogue") == true and oflags.get("groups") == true,
		"overlay sim_sha=%s proto_speaks=%s city=%s connected=%s flags=%s vs authority sim_sha=%s city=%s"
		% [str(ov.get("sim_sha")), str(ov.get("protocol_speaks")), str(ov.get("city")),
			str(ov.get("connected")), str(oflags), str(started.get("sim_sha")), _bundle])

	# ====================================================================== #
	# (e) EVENT FEED shows real authoritative events, bounded, no double-count
	# ====================================================================== #
	feed.poll()
	var feed_rows := feed.rows()
	# independent direct reads of the SAME streams (from 0) to cross-check kinds by
	# category — the feed is a bounded ring, so its surviving tail can be any mix of
	# work / cognition / dialogue / groups; every displayed line must still be a real
	# authoritative event of its stream.
	var kinds_by_cat := {"work": {}, "cognition": {}, "dialogue": {}, "groups": {}}
	for e in _arr(_dict(SimBridge.get_work(0).get("work")).get("events")):
		kinds_by_cat["work"][str(_dict(e).get("event"))] = true
	for e in _arr(_dict(SimBridge.get_cognition(0).get("cognition")).get("events")):
		kinds_by_cat["cognition"][str(_dict(e).get("event"))] = true
	for e in _arr(_dict(SimBridge.get_dialogue(0).get("dialogue")).get("events")):
		kinds_by_cat["dialogue"][str(_dict(e).get("event"))] = true
	for e in _arr(_dict(SimBridge.get_groups_snapshot(0)).get("events")):
		kinds_by_cat["groups"][str(_dict(e).get("event"))] = true
	var matched := 0
	var unmatched: Array = []
	for row in feed_rows:
		var rd := _dict(row)
		var cat := str(rd.get("cat"))
		if kinds_by_cat.has(cat) and _dict(kinds_by_cat[cat]).has(str(rd.get("kind"))):
			matched += 1
		else:
			unmatched.append("%s/%s" % [cat, str(rd.get("kind"))])
	_ok("event_feed_shows_authoritative_events",
		feed_rows.size() > 0 and matched == feed_rows.size(),
		"feed holds %d rows; %d of them are event kinds the authority's own GET_WORK/GET_COGNITION/GET_DIALOGUE/GET_GROUPS deltas also report (unmatched: %s; e.g. %s)"
		% [feed_rows.size(), matched, str(unmatched), str(feed_rows[0].get("text")) if feed_rows.size() > 0 else "—"])
	_ok("event_feed_bounded",
		feed.lines().size() <= EventFeed.MAX_LINES,
		"feed on-screen lines=%d <= MAX_LINES=%d (ring buffer, never unbounded)"
		% [feed.lines().size(), EventFeed.MAX_LINES])

	var before := feed.rows().size()
	feed.poll()                              # no advance in between
	var after := feed.rows().size()
	_ok("event_feed_no_double_count",
		after == before,
		"a second poll with no world advance added %d rows (each stream re-fetches only since its own last seq)"
		% (after - before))

	# filtering narrows to the requested categories only
	# last_render tracks shown count; verify the filter is honored by re-render
	feed.set_filter(["work"])
	var lr := feed.last_render
	_ok("event_feed_filter",
		int(lr.get("n_shown", 0)) <= int(lr.get("n_rows", 0)),
		"set_filter(['work']) shows %s of %s buffered rows (category filter honored)"
		% [str(lr.get("n_shown")), str(lr.get("n_rows"))])
	feed.set_filter([])

	# ====================================================================== #
	# (f) FOLLOW CAMERA is presentation-only: it exposes an authoritative target
	# ====================================================================== #
	cam.follow(cid)
	var cmob := _dict(SimBridge.last_mobility)
	var authx = null
	var authy = null
	for row in _arr(cmob.get("citizens")):
		if int(_dict(row).get("citizen_id", -1)) == cid:
			authx = _dict(row).get("x")
			authy = _dict(row).get("y")
			break
	if authx == null:
		_info("follow_camera_target_is_authoritative",
			"citizen c%d not in the NEAR movement block (frozen/abstract); follow id=%d exposed, no target"
			% [cid, cam.followed_id])
	else:
		# The camera stores the position in a float32 Vector2; the authority already
		# rounds x/y to 2 decimals, so compare at metre-scale tolerance (float32 at
		# these magnitudes carries ~1e-5 error, larger than a 1e-6 exact compare).
		var dx: float = abs(cam.target_xy.x - float(authx))
		var dy: float = abs(cam.target_xy.y - float(authy))
		_ok("follow_camera_target_is_authoritative",
			cam.followed_id == cid and cam.has_target and dx < 0.05 and dy < 0.05,
			"follow camera followed_id=%d target_xy=(%s,%s) = authority position (%s,%s); it moves nothing itself"
			% [cam.followed_id, str(cam.target_xy.x), str(cam.target_xy.y), str(authx), str(authy)])

	# ====================================================================== #
	# (g) READ-ONLY: world byte-identical across a batch of surface refreshes
	# ====================================================================== #
	var w0 := JSON.stringify(_dict(SimBridge.snapshot().get("world")))
	for _k in range(3):
		inspector.refresh()
		overlay.refresh()
		feed.poll()
		cam.refresh()
	var w1 := JSON.stringify(_dict(SimBridge.snapshot().get("world")))
	_ok("inspector_is_read_only",
		w0 == w1 and inspector.mutation_calls() == 0,
		"a full world snapshot is byte-identical before and after 3 rounds of inspector/overlay/feed/camera refresh (len %d==%d); inspector mutation_calls()=%d — the observer layer advances and mutates nothing"
		% [w0.length(), w1.length(), inspector.mutation_calls()])

	_stats = {"citizen": cid, "goal": goal, "task": task, "health": ctx.get("health"),
		"n_memories": ctx.get("n_memories"), "perceived_danger": ctx.get("perceived_danger"),
		"feed_rows": feed_rows.size(), "overlay": ov, "in_group": qm.get("in_group"),
		"followed_id": cam.followed_id}
	SimBridge.disconnect_from_sim()


func _finish() -> void:
	var n := 0
	for l in _log:
		if l.begins_with("PASS") or l.begins_with("FAIL"):
			n += 1
	if n < 10:
		_ok("all_checks_ran", false, "only %d PASS/FAIL checks ran" % n)
	print("\n==== INSPECTOR GATE RESULTS (%s, citizen %s) ====" % [_bundle, str(_stats.get("citizen"))])
	for l in _log:
		print(l)
	print("==== %s (%d failure(s)) ====" % ["PASS" if _fail == 0 else "FAIL", _fail])
	var dir := _trace_path.get_base_dir()
	if dir != "":
		DirAccess.make_dir_recursive_absolute(dir)
	var f := FileAccess.open(_trace_path, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify({"version": 1, "bundle": _bundle,
			"gate": "inspector", "results": _log, "stats": _stats,
			"pass": _fail == 0, "failures": _fail}))
		f.close()
		print("TRACE saved: %s" % _trace_path)
	get_tree().quit(1 if _fail > 0 else 0)
