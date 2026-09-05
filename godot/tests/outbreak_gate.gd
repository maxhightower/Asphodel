extends Node3D

## OUTBREAK GATE — the outbreak embodied in the real city (ASPHODEL_OUTBREAK_V1 §9, §13, §17).
##
## Live Python bridge + real Godot physics + the streamed compiled city. Starts
## a Houston weekday with the classic-zombie index case, follows that citizen
## with the NEAR band (EmbodiedMobility bodies) and checks, in engine:
## the symptomatic citizen leaving work under its own executor; the collapse
## at its authoritative place; the corpse held there; the reanimated citizen as
## the SAME id at the SAME place; the undead body walking under physics; LOD
## demotion/promotion of the undead with identity and position continuity;
## save/load in the undead state; the abandoned car as a persistent wreck body;
## the bitten citizen leaving its building on foot (a living body fleeing).
## Every check is authoritative state observed through the bridge plus a body
## the scene did not place itself.
##
##   godot --headless --path godot res://tests/OutbreakGate.tscn -- --bundle houston --citizen 42

const ExteriorWorld = preload("res://scripts/exterior_world.gd")

var _bundle := "houston"
var _cid := 42
var _trace_path := "/tmp/asph_outbreak_probe.json"
var _save_path := "/tmp/asph_outbreak_gate_save.json"
var _game_dt := 0.25
var _fail := 0
var _log: Array[String] = []
var _rows: Array = []
var _events: Array = []
var _seq := 0
var _emb: EmbodiedMobility
var _ext: ExteriorWorld
var _have_ext := false
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
		elif args[i] == "--trace" and i + 1 < args.size():
			_trace_path = args[i + 1]
		elif args[i] == "--game-dt" and i + 1 < args.size():
			_game_dt = float(args[i + 1])
	await get_tree().physics_frame
	await _run()
	_finish()


func _floor() -> void:
	var f := StaticBody3D.new()
	f.collision_layer = CollisionLayers.WORLD_STATIC
	f.collision_mask = 0
	var cs := CollisionShape3D.new()
	var b := BoxShape3D.new()
	b.size = Vector3(12000, 1, 12000)
	cs.shape = b
	f.add_child(cs)
	add_child(f)
	f.global_position = Vector3(0, -0.5, 0)


func _row(block: Dictionary, cid: int) -> Dictionary:
	for row in block.get("citizens", []):
		if int(row["citizen_id"]) == cid:
			return row
	return {}


func _vrow(block: Dictionary, vid: String) -> Dictionary:
	for row in block.get("vehicles", []):
		if str(row["vehicle_id"]) == vid:
			return row
	return {}


func _focus(row: Dictionary) -> void:
	SimBridge.focus_xy = Vector2(float(row["x"]), float(row["y"]))
	SimBridge.has_focus_xy = true
	if _have_ext:
		_ext.update_focus(Vector3(float(row["x"]), 0.0, float(row["y"])))


func _step(dt: float = -1.0) -> Dictionary:
	var d := _game_dt if dt <= 0.0 else dt
	var r: Dictionary = SimBridge.advance_time(d, "mobility")
	if r.get("ok", false) != true:
		return {}
	var block: Dictionary = r.get("mobility", {})
	_emb.apply(block, d)
	return block


func _pull_events() -> Array:
	var r: Dictionary = SimBridge.get_outbreak(_seq)
	var ob: Dictionary = r.get("outbreak", {})
	var evs: Array = ob.get("events", [])
	for e in evs:
		_events.append(e)
		_seq = max(_seq, int(e.get("seq", 0)))
	return evs


func _health(cid: int) -> String:
	var r: Dictionary = SimBridge.get_outbreak(_seq)
	for h in r.get("outbreak", {}).get("health", []):
		if int(h["citizen_id"]) == cid:
			return str(h["state"])
	return "susceptible"


func _record(block: Dictionary, tag: String) -> void:
	var row := _row(block, _cid)
	if row.is_empty():
		return
	var out := {"t": float(block.get("t_s", 0.0)), "tag": tag, "state": row.get("state"),
		"health": row.get("health"), "ax": row.get("x"), "ay": row.get("y"),
		"building_id": row.get("building_id"), "vehicle_id": row.get("vehicle_id"), "band": row.get("band")}
	var cb = _emb.body_of("cit:%d" % _cid)
	if cb != null:
		out["bx"] = cb.global_position.x
		out["bz"] = cb.global_position.z
		out["look"] = cb.get_meta("health_look", "")
	_rows.append(out)


func _lag(row: Dictionary, body: Node3D) -> float:
	return Vector2(float(row["x"]), float(row["y"])).distance_to(Vector2(body.global_position.x, body.global_position.z))


func _ff_to(hour: float) -> void:
	var h := float(SimBridge.last_summary.get("hour", 0.0))
	if h < hour:
		SimBridge.advance_time((hour - h) * 3600.0, "")


func _run() -> void:
	_floor()
	_emb = EmbodiedMobility.new()
	_emb.time_scale = 1.0 / max(get_physics_process_delta_time(), 0.001) * _game_dt
	add_child(_emb)
	_ext = ExteriorWorld.new()
	add_child(_ext)
	_have_ext = _ext.setup("res://bundles/" + _bundle)
	_info("exterior", "compiled world streamed: %s" % str(_have_ext))
	if not SimBridge.connect_to_sim():
		_ok("bridge_connected", false, "start python -m asphodel.bridge.server first")
		return
	var started: Dictionary = SimBridge.start_world(_bundle, {"seed": 0, "start_hour": 5.0,
		"outbreak": {"pathogen": "classic_zombie", "citizen_id": _cid}})
	_ok("world_started_with_outbreak", started.get("ok", false) and bool(started.get("outbreak_enabled", false)),
		"mobility=%s outbreak=%s" % [str(started.get("mobility_enabled")), str(started.get("outbreak_enabled"))])
	if not SimBridge.outbreak_enabled:
		return
	var evs := _pull_events()
	var infected := {}
	for e in evs:
		if e["event"] == "INFECTED" and int(e["citizen_id"]) == _cid:
			infected = e
	_ok("index_case_seeded", not infected.is_empty(), "citizen %d symptom_t=%s death_t=%s reanimate_t=%s" % [
		_cid, str(infected.get("symptom_t")), str(infected.get("death_t")), str(infected.get("reanimate_t"))])
	if infected.is_empty():
		return
	var symptom_t := float(infected["symptom_t"])
	var t0 := 5.0 * 3600.0     # world starts at 05:00? read the summary hour instead
	var start_hour := float(SimBridge.last_summary.get("hour", 0.0))
	var onset_hour := start_hour + symptom_t / 3600.0

	# --- 1. an ordinary infected morning: the citizen is at work, incubating ----
	_ff_to(onset_hour - 0.05)
	var m: Dictionary = SimBridge.get_mobility().get("mobility", {})
	var row := _row(m, _cid)
	_ok("incubating_at_work_before_onset", str(row.get("health")) == "incubating" and int(row.get("building_id", -1)) >= 0,
		"health=%s in building %s (ordinary life continues while incubating)" % [str(row.get("health")), str(row.get("building_id"))])
	_focus(row)
	if _have_ext:
		_ext.force_materialize(Vector3(float(row["x"]), 0.0, float(row["y"])))
		for i in range(30):
			_ext.update_focus(Vector3(float(row["x"]), 0.0, float(row["y"])))
			await get_tree().process_frame

	# --- 2. onset -> leaves work under its own executor (body on foot / car) ----
	var saw_onset := false
	var saw_left := false
	var walk_frames := 0
	var walk_ok := 0
	var veh_id := ""
	var collapsed := false
	var collapse_row := {}
	for i in range(12000):
		var block := _step()
		if block.is_empty():
			break
		row = _row(block, _cid)
		_focus(row)
		_record(block, "onset")
		var st: String = str(row.get("state"))
		if str(row.get("health")) == "symptomatic":
			saw_onset = true
		if saw_onset and st in ["on_foot", "approaching_vehicle", "entering_vehicle", "driving"]:
			saw_left = true
			var cb = _emb.body_of("cit:%d" % _cid)
			if cb != null and st != "driving":
				walk_frames += 1
				if _lag(row, cb) <= cb.follow_leash + 0.5:
					walk_ok += 1
			if st == "driving":
				veh_id = str(row.get("vehicle_id"))
		if st == "incapacitated":
			collapsed = true
			collapse_row = row.duplicate(true)
			break
		await get_tree().physics_frame
	_pull_events()
	_ok("symptomatic_deviates_from_schedule", saw_onset and saw_left,
		"onset seen=%s, left the workplace under the executor=%s (body frames %d, within leash %d)" % [str(saw_onset), str(saw_left), walk_frames, walk_ok])
	_ok("collapsed_at_authoritative_place", collapsed,
		"INCAPACITATED at (%s,%s) building=%s vehicle=%s" % [str(collapse_row.get("x")), str(collapse_row.get("y")), str(collapse_row.get("building_id")), str(collapse_row.get("vehicle_id"))])
	if not collapsed:
		return
	var died_in_car: bool = collapse_row.get("vehicle_id") != null
	var col_xy := Vector2(float(collapse_row["x"]), float(collapse_row["y"]))

	# --- 3. corpse held in place; the car is a wreck body -----------------------
	var held := true
	var wreck_seen := false
	var corpse_seen := false
	var re_row := {}
	for i in range(40000):
		# the corpse does not move: step 4 game-seconds per physics frame here
		var block := _step(4.0)
		if block.is_empty():
			break
		row = _row(block, _cid)
		_focus(row)
		_record(block, "corpse")
		var xy := Vector2(float(row["x"]), float(row["y"]))
		if xy.distance_to(col_xy) > 0.01 and str(row.get("health")) != "undead":
			held = false
		if str(row.get("health")) == "corpse":
			corpse_seen = true
		if veh_id != "":
			var vr := _vrow(block, veh_id)
			var vb = _emb.body_of(veh_id)
			if str(vr.get("fidelity")) == "persistent_wreck" and vb != null:
				wreck_seen = true
		if str(row.get("health")) == "undead":
			re_row = row.duplicate(true)
			break
		await get_tree().physics_frame
	_pull_events()
	_ok("corpse_held_at_death_location", corpse_seen and held, "position frozen from collapse through death to reanimation")
	if died_in_car:
		_ok("abandoned_car_is_persistent_wreck_body", wreck_seen, "VehicleBody %s present with fidelity persistent_wreck" % veh_id)
	else:
		_info("abandoned_car", "the citizen did not collapse in a vehicle in this run")
	_ok("reanimated_same_identity_same_place", not re_row.is_empty()
		and Vector2(float(re_row["x"]), float(re_row["y"])).distance_to(col_xy) < 0.01
		and int(re_row["citizen_id"]) == _cid,
		"citizen %d undead at (%s,%s)" % [_cid, str(re_row.get("x")), str(re_row.get("y"))])
	if re_row.is_empty():
		return

	# --- 4. the undead walks as a body; LOD demote/promote; save/load ------------
	var body_frames := 0
	var body_ok := 0
	var body_dist := 0.0
	var last_b := Vector3.ZERO
	var undead_look := false
	var body_seen := false
	var demoted := false
	var promoted_back := false
	var jump := 0.0
	var phase := 0
	var far_frames := 0
	var moved_far := 0.0
	var far_start := Vector2.ZERO
	var saveload_ok := false
	var saved := false
	for i in range(12000):
		var block := _step()
		if block.is_empty():
			break
		row = _row(block, _cid)
		var cb = _emb.body_of("cit:%d" % _cid)
		if phase == 0:
			_focus(row)
			if cb != null:
				body_seen = true
				body_frames += 1
				if _lag(row, cb) <= cb.follow_leash + 0.5 + 0.9:
					body_ok += 1
				if str(cb.get_meta("health_look", "")) == "undead":
					undead_look = true
				if last_b != Vector3.ZERO:
					body_dist += Vector2(cb.global_position.x, cb.global_position.z).distance_to(Vector2(last_b.x, last_b.z))
				last_b = cb.global_position
			if body_dist > 15.0 and not saved:
				saved = true
				var before := row.duplicate(true)
				var hb := _health(_cid)
				var sr: Dictionary = SimBridge.save(_save_path)
				var lr: Dictionary = SimBridge.load(_save_path)
				var after := _row(SimBridge.get_mobility().get("mobility", {}), _cid)
				var ha := _health(_cid)
				saveload_ok = sr.get("ok", false) and lr.get("ok", false) and hb == "undead" and ha == "undead" \
					and str(after.get("x")) == str(before.get("x")) and str(after.get("y")) == str(before.get("y")) \
					and str(after.get("state")) == str(before.get("state"))
				_ok("saveload_undead_identical", saveload_ok, "health %s -> %s, pos/state identical=%s" % [hb, ha, str(saveload_ok)])
			if body_dist > 25.0:
				SimBridge.focus_xy = Vector2(float(row["x"]) + 1500.0, float(row["y"]))
				far_start = Vector2(float(row["x"]), float(row["y"]))
				phase = 1
		elif phase == 1:
			far_frames += 1
			if cb == null:
				demoted = true
			if far_frames > int(20.0 / _game_dt):
				moved_far = far_start.distance_to(Vector2(float(row["x"]), float(row["y"])))
				_focus(row)
				phase = 2
		elif phase == 2:
			_focus(row)
			if cb != null:
				promoted_back = true
				jump = _lag(row, cb)
				_ok("undead_health_after_promotion", _health(_cid) == "undead", "promotion did not change health")
				phase = 3
		else:
			_focus(row)
			break
		_record(block, "undead")
		await get_tree().physics_frame
	_pull_events()
	_ok("undead_body_exists", body_seen and undead_look, "CitizenBody for cit:%d with the undead look, %d frames" % [_cid, body_frames])
	_ok("undead_walks_under_physics", body_frames > 0 and body_dist >= 10.0 and body_ok >= int(body_frames * 0.9),
		"body moved %.1f m; within leash %d/%d frames" % [body_dist, body_ok, body_frames])
	_ok("undead_demoted_when_player_left", demoted, "no body with the focus 1.5 km away")
	_ok("undead_progressed_while_far", moved_far > 3.0, "authoritative undead moved %.1f m with no body" % moved_far)
	_ok("undead_promoted_same_identity", promoted_back and jump <= 2.0, "body recreated at the authoritative pose (jump %.2f m)" % jump)
	if not saved:
		_ok("saveload_undead_identical", false, "undead never walked far enough to save")

	# --- 5. attack -> the bitten citizen flees on foot (living body reacting) ----
	var attack := {}
	var flee := {}
	for i in range(20000):
		var block := _step()
		if block.is_empty():
			break
		row = _row(block, _cid)
		_focus(row)
		if i % 40 == 0:
			for e in _pull_events():
				if e["event"] == "ATTACK" and int(e["citizen_id"]) == _cid and attack.is_empty():
					attack = e
				if e["event"] == "FLEE" and not attack.is_empty() and int(e["citizen_id"]) == int(attack["victim_citizen"]):
					flee = e
		if not flee.is_empty():
			break
		await get_tree().physics_frame
	_ok("undead_attacked_living_citizen", not attack.is_empty(),
		"ATTACK on citizen %s in building %s exposed=%s" % [str(attack.get("victim_citizen")), str(attack.get("building_id")), str(attack.get("exposed"))])
	_ok("victim_reacts_flee", not flee.is_empty(), "FLEE goal target %s" % str(flee.get("target")))
	if not flee.is_empty():
		var victim := int(attack["victim_citizen"])
		var fled_body := false
		var vfr := 0
		for i in range(4000):
			var block := _step()
			if block.is_empty():
				break
			var vr := _row(block, victim)
			_focus(vr)
			var vb = _emb.body_of("cit:%d" % victim)
			if vb != null and str(vr.get("state")) == "on_foot":
				vfr += 1
				if vfr > 20:
					fled_body = true
					break
			await get_tree().physics_frame
		_ok("fleeing_citizen_embodied_on_foot", fled_body, "citizen %d left building %s on foot as a CitizenBody" % [victim, str(attack.get("building_id"))])
	_stats = {"body_frames": body_frames, "body_dist_m": body_dist, "rematerializations": _emb.rematerializations, "promotions": _emb.promotions,
		"demotions": _emb.demotions, "reports": _emb.reports_sent}
	SimBridge.disconnect_from_sim()


func _finish() -> void:
	var n := 0
	for l in _log:
		if l.begins_with("PASS") or l.begins_with("FAIL"):
			n += 1
	if n < 12:
		_ok("all_checks_ran", false, "only %d checks ran" % n)
	print("\n==== OUTBREAK GATE RESULTS (%s, citizen %d) ====" % [_bundle, _cid])
	for l in _log:
		print(l)
	print("==== %s (%d failure(s)) ====" % ["PASS" if _fail == 0 else "FAIL", _fail])
	var f := FileAccess.open(_trace_path, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify({"version": 1, "bundle": _bundle, "citizen_id": _cid, "game_dt": _game_dt,
			"results": _log, "stats": _stats, "events": _events, "rows": _rows}))
		f.close()
		print("TRACE saved: %s (%d rows, %d events)" % [_trace_path, _rows.size(), _events.size()])
	get_tree().quit(1 if _fail > 0 else 0)
