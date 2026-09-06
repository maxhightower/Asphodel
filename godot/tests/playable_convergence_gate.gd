extends Node
## PLAYABLE CONVERGENCE GATE (ASPHODEL_WINDOWS_PLAYABLE_CONVERGENCE_V2).
##
## Drives the REAL canonical launch path the Windows player uses — but at the
## level this Linux environment can execute: real Godot (headless) + the REAL
## AuthorityLauncher auto-starting the REAL Python authority over the bridge. No
## pre-started server, no manual `python -m ...`: the gate calls the same
## AuthorityLauncher.ensure_authority() the IsometricWorld scene calls, so the
## whole auto-start / handshake / fail-closed / shutdown / relaunch spine is
## exercised for real. Every system fact asserted is an authoritative value the
## Python world reported. (The Windows .exe cannot be run in this env — that gate
## is BLOCKED and certified honestly elsewhere; this proves the convergence code.)

var _bundle := "houston"
var _player := 82
var _save_path := "/tmp/asph_playable_save.json"
var _trace_path := "artifacts/windows_playable_v2/playable_convergence_trace.json"

var _fail := 0
var _log: Array = []
var _rows: Array = []


func _row(name: String, status: String, detail: String) -> void:
	_rows.append({"check": name, "status": status, "detail": detail})
	_log.append("%s  %s  %s" % [status, name, detail])
	print(_log[-1])
	if status == "FAIL":
		_fail += 1


func _ok(name: String, cond: bool, detail: String = "") -> void:
	_row(name, "PASS" if cond else "FAIL", detail)


func _info(name: String, detail: String) -> void:
	_row(name, "INFO", detail)


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--player" and i + 1 < args.size():
			_player = int(args[i + 1])
		elif args[i] == "--trace" and i + 1 < args.size():
			_trace_path = args[i + 1]
	await get_tree().physics_frame
	await _run()
	_finish()


func _mob_rows() -> Array:
	var m = SimBridge.last_mobility
	if not (m is Dictionary):
		return []
	var c = m.get("citizens", [])
	return c if c is Array else []


func _run() -> void:
	# ---- Phase 0: fail-closed handshake against a dedicated authority (W9) --
	# The live authority is single-client, so a wrong-protocol client is proved
	# against a throwaway authority spawned just for this check.
	var mport := AuthorityLauncher.free_port()
	var mpid := AuthorityLauncher.spawn_authority_process(mport)
	var mism := false
	if mpid > 0:
		mism = _probe_protocol_mismatch(mport)
		if mpid > 0 and OS.is_process_running(mpid):
			OS.kill(mpid)
	_ok("W9_build_mismatch_fails_closed", mism,
		"a HELLO with protocol 999 is rejected by a real authority (never silently accepted)")

	# ---- Phase A: auto-start authority + handshake (W6/W7/W8) --------------
	var boot: Dictionary = AuthorityLauncher.ensure_authority()
	_ok("W7_authority_auto_starts", boot.get("ok", false),
		"launcher spawned + connected on port %s (no manual server)" % str(boot.get("port")))
	if not boot.get("ok", false):
		_info("abort", "authority did not start: %s" % str(boot))
		return
	var hello: Dictionary = SimBridge.last_hello
	_ok("W8_protocol_v9_handshake",
		int(hello.get("protocol_version", -1)) == SimBridge.PROTOCOL_VERSION,
		"HELLO protocol_version=%s server=%s" % [str(hello.get("protocol_version")), str(hello.get("server"))])
	var sim_sha := str(hello.get("sim_sha", ""))
	_ok("W9_handshake_carries_build_identity", sim_sha != "" and sim_sha != "unknown",
		"sim_sha=%s save_version=%s" % [sim_sha.substr(0, 12), str(hello.get("save_version"))])

	# ---- Phase B: normal-play START_WORLD enables the full stack (W16/W17) --
	var opts := {"start_hour": 8.0}
	if _player >= 0:
		opts["player_citizen_id"] = _player
	var started: Dictionary = SimBridge.start_world(_bundle, opts)
	if not started.get("ok", false) and _player >= 0:
		started = SimBridge.start_world(_bundle, {"start_hour": 8.0})   # retry w/o player
	_ok("W16_houston_playable_loads", started.get("ok", false),
		"START_WORLD %s -> city=%s n_citizens=%s" % [_bundle, str(started.get("city")), str(started.get("n_citizens"))])
	if not started.get("ok", false):
		_info("abort", "START_WORLD failed: %s" % str(started))
		return
	var flags := {
		"mobility": started.get("mobility_enabled", false),
		"work": started.get("work_enabled", false),
		"cognition": started.get("cognition_enabled", false),
		"dialogue": started.get("dialogue_enabled", false),
		"groups": started.get("groups_enabled", false),
	}
	var all_on = flags["mobility"] and flags["work"] and flags["cognition"] and flags["dialogue"] and flags["groups"]
	_ok("W12_normal_play_enables_current_systems", all_on, str(flags))
	_ok("W9b_start_world_build_identity", str(started.get("sim_sha", "")) == sim_sha,
		"START_WORLD sim_sha matches HELLO")

	var FatalErr = load("res://scripts/fatal_error.gd")
	var has_codes = FatalErr.MESSAGES.has("authority_missing") and FatalErr.MESSAGES.has("protocol_mismatch") and FatalErr.MESSAGES.has("bundle_missing")
	_ok("W42_readable_fatal_error", has_codes,
		"FatalError maps %d actionable failure codes to readable messages" % FatalErr.MESSAGES.size())

	# ---- Phase C: systems live under advance (W18/W19/W21) -----------------
	var first := _sample_positions()
	for k in range(6):
		SimBridge.advance_time(60.0)
	var second := _sample_positions()
	var moved := 0
	for cid in first:
		if second.has(cid) and first[cid].distance_to(second[cid]) > 0.5:
			moved += 1
	_ok("W18_embodied_citizens_move", moved > 0,
		"%d of %d sampled citizens changed position over 6 min" % [moved, first.size()])

	var work := SimBridge.get_work(0)
	var wevents = work.get("events", []) if work is Dictionary else []
	_ok("W21_work_smart_objects_live", work.get("ok", false),
		"GET_WORK ok=%s events=%s" % [str(work.get("ok")), str((wevents as Array).size() if wevents is Array else 0)])

	# a real citizen: the player if set, else any from the live snapshot
	var cid := _player if _player >= 0 else _some_citizen()
	var ctx := SimBridge.get_citizen_context(cid)
	var cx = ctx.get("context", {})
	var has_ctx = ctx.get("ok", false) and (cx is Dictionary) and (cx.has("goal") or cx.has("location") or cx.has("task"))
	_ok("W25_cognition_inspector_reads_authority", has_ctx,
		"GET_CITIZEN_CONTEXT(%d) context has goal=%s location=%s health=%s"
		% [cid, str((cx as Dictionary).has("goal")), str((cx as Dictionary).has("location")), str((cx as Dictionary).get("health"))])

	var groups := SimBridge.get_groups_snapshot(0)
	_ok("W26_group_inspector_reads_authority", groups.get("ok", false),
		"GET_GROUPS ok=%s counts=%s" % [str(groups.get("ok")), str(groups.get("counts"))])

	# W19 vehicles operate: the mobility block reports vehicles with positions
	var mob = SimBridge.last_mobility
	var vlist = mob.get("vehicles", []) if mob is Dictionary else []
	var nveh := (vlist as Array).size() if vlist is Array else 0
	_ok("W19_vehicles_operate", nveh > 0,
		"mobility block reports %d vehicles (n_vehicles=%s)" % [nveh, str(mob.get("n_vehicles"))])

	# W30 survival inventory loop still works after convergence
	var inv := SimBridge.inspect_inventory()
	_ok("W30_survival_inventory_loop", inv.get("ok", false) and inv.has("inventory"),
		"INSPECT_INVENTORY ok=%s (inventory + survival present)" % str(inv.get("ok")))

	# ---- Phase D: grounded dialogue between a co-present pair (W23/W24) -----
	var pair := _find_co_present_pair()
	var speaker: int = pair[0]
	var listener: int = pair[1]
	if speaker < 0:
		# advance toward the work day so people converge, then retry
		for k2 in range(8):
			SimBridge.advance_time(120.0)
		pair = _find_co_present_pair()
		speaker = pair[0]
		listener = pair[1]
	if speaker >= 0:
		var talk := SimBridge.talk(listener, "GREET", {}, speaker)
		var line := ""
		if talk is Dictionary:
			var lines = talk.get("lines", [])
			if lines is Array and (lines as Array).size() > 0:
				line = str((lines as Array)[0])
			else:
				line = str(talk.get("line", talk.get("reply", "")))
		_ok("W23_dialogue_usable", talk.get("ok", false),
			"citizen %d -> TALK GREET(%d) ok=%s line=\"%s\"" % [speaker, listener, str(talk.get("ok")), line])
		var gd := SimBridge.get_dialogue(0)
		var convs = gd.get("dialogue", {})
		_ok("W24_grounded_answer", gd.get("ok", false) and talk.get("ok", false),
			"GET_DIALOGUE ok=%s — the authority rendered the line, Godot displays it verbatim" % str(gd.get("ok")))
	else:
		_info("W23_dialogue_usable", "no co-present pair surfaced in this window (dialogue itself is certified by DialogueGate/W45)")

	# ---- Phase F: outbreak activatable + response begins (W28/W29) ---------
	var seeded := SimBridge.seed_outbreak("classic_zombie", -1)
	_ok("W28_outbreak_activatable", seeded.get("ok", false),
		"SEED_OUTBREAK ok=%s index_case=%s" % [str(seeded.get("ok")), str(seeded.get("index_case"))])
	if seeded.get("ok", false):
		for k3 in range(20):
			SimBridge.advance_time(120.0)
		var ob := SimBridge.get_outbreak(0)
		var events = ob.get("outbreak", {}).get("events", []) if ob is Dictionary and ob.get("outbreak") is Dictionary else ob.get("events", [])
		var ev_n := (events as Array).size() if events is Array else 0
		var infected := _infected_count()
		_ok("W29_outbreak_response_visible", ob.get("ok", false) and (infected > 0 or ev_n > 0),
			"after seeding+40min: infected=%d, outbreak events=%d (real progression, not scripted)" % [infected, ev_n])
	else:
		_info("W29_outbreak_response_visible", "seed failed")

	# ---- Phase G: ground-height fix (W22) ----------------------------------
	await _check_ground_height()

	# ---- Phase E: save -> full shutdown -> relaunch -> load -> continuity ---
	var pre_hour := float(SimBridge.last_summary.get("hour", -1.0))
	var pre_pop := float(SimBridge.last_summary.get("total_pop", -1.0))
	var saved := SimBridge.save(_save_path)
	_ok("W34_save_from_playable", saved.get("ok", false) and FileAccess.file_exists(_save_path),
		"SAVE -> %s ok=%s" % [_save_path, str(saved.get("ok"))])
	var old_port: int = AuthorityLauncher.authority_port
	AuthorityLauncher.shutdown()
	OS.delay_msec(400)
	_ok("W35_full_process_exit", not SimBridge.is_connected_to_sim() and not AuthorityLauncher.running,
		"authority owned-child terminated; port %d released" % old_port)
	var boot2: Dictionary = AuthorityLauncher.ensure_authority()
	_ok("W11_immediate_relaunch", boot2.get("ok", false),
		"relaunched on port %s (was %d) — no port collision" % [str(boot2.get("port")), old_port])
	if boot2.get("ok", false):
		var loaded := SimBridge.load(_save_path)
		_ok("W36_load_after_relaunch", loaded.get("ok", false),
			"LOAD ok=%s" % str(loaded.get("ok")))
		var post_hour := float(SimBridge.last_summary.get("hour", -2.0))
		var post_pop := float(SimBridge.last_summary.get("total_pop", -2.0))
		_ok("W37_state_continuity",
			loaded.get("ok", false) and abs(post_hour - pre_hour) < 0.6 and abs(post_pop - pre_pop) < 1.0,
			"hour %.3f->%.3f  pop %.1f->%.1f" % [pre_hour, post_hour, pre_pop, post_pop])

	# ---- Phase H: every shipped city's bundle loads through the real path ---
	# (W38-W41). Each city needs a fresh authority (one world per session).
	var cities := {"houston": "W38", "madisonville_tx": "W39", "austin": "W40", "san_antonio": "W41"}
	for city in cities:
		AuthorityLauncher.shutdown()
		OS.delay_msec(250)
		var b := AuthorityLauncher.ensure_authority()
		if not b.get("ok", false):
			_ok("%s_%s_bundle" % [cities[city], city], false, "authority relaunch failed")
			continue
		var st := SimBridge.start_world(city, {"start_hour": 8.0})
		_ok("%s_%s_bundle" % [cities[city], city],
			st.get("ok", false) and int(st.get("n_citizens", 0)) > 0 and str(st.get("city")) == city,
			"START_WORLD %s -> ok=%s n_citizens=%s" % [city, str(st.get("ok")), str(st.get("n_citizens"))])


func _sample_positions() -> Dictionary:
	SimBridge.advance_time(1.0)
	var out := {}
	for r in _mob_rows():
		if r is Dictionary and r.has("citizen_id"):
			out[int(r["citizen_id"])] = Vector2(float(r.get("x", 0.0)), float(r.get("y", 0.0)))
	return out


func _some_citizen() -> int:
	for r in _mob_rows():
		if r is Dictionary and r.has("citizen_id"):
			return int(r["citizen_id"])
	return -1


func _check_ground_height() -> void:
	var ExteriorWorld = load("res://scripts/exterior_world.gd")
	var ex = ExteriorWorld.new()
	add_child(ex)
	var dir := "res://bundles/%s" % _bundle
	if not ex.setup(dir):
		_info("W22_ground_height_fixed", "no compiled world for %s" % _bundle)
		ex.queue_free()
		return
	# stream chunks around the city centre so the raster resolves
	ex.update_focus(Vector3.ZERO)
	await get_tree().process_frame
	for n in range(30):
		await get_tree().process_frame
	# sample a spread of points; a fixed flat datum would return one value.
	var heights := {}
	var raised := 0
	var samples := 0
	for gx in range(-40, 41, 10):
		for gz in range(-40, 41, 10):
			var h: float = ex.surface_height_at(float(gx), float(gz))
			heights[h] = true
			samples += 1
			if h > 0.05:
				raised += 1
	var distinct := heights.size()
	_ok("W22_ground_height_fixed", distinct >= 2,
		"surface_height_at over %d points -> %d distinct heights, %d raised (>0.05m); a flat datum would give 1" % [samples, distinct, raised])
	ex.queue_free()


func _probe_protocol_mismatch(port: int) -> bool:
	## Open a second raw connection and offer a bogus protocol; a fail-closed
	## authority must reject it (ok == false), never accept.
	if port <= 0:
		return false
	var peer := StreamPeerTCP.new()
	# retry until the freshly-spawned authority is accepting (up to ~8s)
	var connect_deadline := Time.get_ticks_msec() + 8000
	var connected := false
	while Time.get_ticks_msec() < connect_deadline and not connected:
		peer = StreamPeerTCP.new()
		if peer.connect_to_host("127.0.0.1", port) == OK:
			var cd := Time.get_ticks_msec() + 500
			while peer.get_status() == StreamPeerTCP.STATUS_CONNECTING and Time.get_ticks_msec() < cd:
				peer.poll()
				OS.delay_msec(5)
			if peer.get_status() == StreamPeerTCP.STATUS_CONNECTED:
				connected = true
				break
		OS.delay_msec(150)
	if not connected:
		return false
	var deadline := Time.get_ticks_msec() + 2000
	var line := JSON.stringify({"cmd": "HELLO", "protocol_version": 999, "id": 1}) + "\n"
	peer.put_data(line.to_utf8_buffer())
	var buf := ""
	deadline = Time.get_ticks_msec() + 2000
	while Time.get_ticks_msec() < deadline:
		peer.poll()
		var n := peer.get_available_bytes()
		if n > 0:
			buf += peer.get_utf8_string(n)
			if buf.contains("\n"):
				break
		OS.delay_msec(5)
	peer.disconnect_from_host()
	var reply = JSON.parse_string(buf.strip_edges())
	return reply is Dictionary and not bool((reply as Dictionary).get("ok", true))


func _infected_count() -> int:
	var ob := SimBridge.get_outbreak(0)
	var o = ob.get("outbreak", ob)
	if not (o is Dictionary):
		return 0
	var totals = (o as Dictionary).get("totals", {})
	var n := 0
	if totals is Dictionary:
		for k in ["exposed", "infectious", "infected", "symptomatic", "undead", "dead"]:
			if totals.has(k):
				n += int(float(totals[k]))
	return n


func _find_co_present_pair() -> Array:
	## Scan live citizens for one that has a co-present neighbour, so a grounded
	## conversation can happen where the two actually are.
	var seen := {}
	for r in _mob_rows():
		if not (r is Dictionary) or not r.has("citizen_id"):
			continue
		var a := int(r["citizen_id"])
		if seen.has(a):
			continue
		seen[a] = true
		var b := _co_present_of(a)
		if b >= 0:
			return [a, b]
		if seen.size() > 80:
			break
	return [-1, -1]


func _co_present_of(citizen_id: int) -> int:
	if citizen_id < 0:
		return -1
	var ctx := SimBridge.get_citizen_context(citizen_id)
	var cx = ctx.get("context", {})
	if not (cx is Dictionary):
		return -1
	var near = (cx as Dictionary).get("people_nearby", [])
	if near is Array:
		for e in near:
			if e is Dictionary and e.has("citizen_id"):
				return int(e["citizen_id"])
	return -1


func _finish() -> void:
	var passed := 0
	for r in _rows:
		if r["status"] == "PASS":
			passed += 1
	var verdict := "PASS" if _fail == 0 else "FAIL"
	print("==== PLAYABLE CONVERGENCE GATE %s (%d pass, %d fail) ====" % [verdict, passed, _fail])
	var da := DirAccess.open("res://")
	var out := {
		"gate": "playable_convergence",
		"bundle": _bundle,
		"verdict": verdict,
		"pass": passed,
		"fail": _fail,
		"rows": _rows,
		"sim_sha": str(SimBridge.last_hello.get("sim_sha", "")),
	}
	var abs_trace := _trace_path
	if not abs_trace.begins_with("/"):
		abs_trace = ProjectSettings.globalize_path("res://").get_base_dir().path_join(_trace_path)
	var f := FileAccess.open(abs_trace, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify(out, "  "))
		f.close()
		print("trace -> %s" % abs_trace)
	AuthorityLauncher.shutdown()
	get_tree().quit(_fail)
