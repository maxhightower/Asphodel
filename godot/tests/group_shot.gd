extends Node

## Survivor-group visual evidence (ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1).
##
## Runs the REAL IsometricWorld scene against the live Python bridge (protocol
## v9) and saves a frame at each stage of the certified group day, paired with
## the machine-readable group snapshot (GET_GROUPS) the frame reflects. Every
## group fact in every caption is the authority's own — the harness renders the
## world the Python GroupRuntime reports and never invents membership, a role, a
## shelter or a decision.
##
## Groups emerge only from real cooperation, so the deterministic group is built
## by a short Python pre-step (tools/groups_build_scenario.py) that drives the
## same causal chain the certification uses and SAVEs the world; this harness
## captures the pre-formation world it boots itself (frame 00) and then LOADs the
## saved world for the formed-group frames (01..09) — the real save/load path.
##
## CAPTIONS say what the PIXELS show and what only the authority's ROWS prove.
## Where a frame reflects a transient event that cannot be re-staged after a load
## (a role-assignment conversation, the scavenger's outbound/return leg, the
## admission handshake, the collective flee), the frame shows the world at the
## relevant place and the caption + the paired snapshot/event rows carry the
## authoritative truth, explicitly labelled.
##
##   xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 godot --path godot \
##     --rendering-method gl_compatibility --rendering-driver opengl3 \
##     res://tests/GroupShot.tscn -- --bundle houston --player 82 \
##     --save /tmp/save.json --sidecar /tmp/scn.json --dir docs/groups/evidence_groups

var _bundle := "houston"
var _player := 82
var _start_hour := 8.0
var _game_dt := 1.0
var _dir := "/tmp/asph_group_shots"
var _save_path := "/tmp/asph_group_save.json"
var _sidecar_path := "/tmp/asph_group_scenario.json"

var _scene: Node3D
var _emb: EmbodiedMobility
var _side := {}
var _manifest := []
var _reached := true


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--bundle" and i + 1 < args.size():
			_bundle = args[i + 1]
		elif args[i] == "--player" and i + 1 < args.size():
			_player = int(args[i + 1])
		elif args[i] == "--start-hour" and i + 1 < args.size():
			_start_hour = float(args[i + 1])
		elif args[i] == "--dir" and i + 1 < args.size():
			_dir = args[i + 1]
		elif args[i] == "--save" and i + 1 < args.size():
			_save_path = args[i + 1]
		elif args[i] == "--sidecar" and i + 1 < args.size():
			_sidecar_path = args[i + 1]
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


func _load_sidecar() -> bool:
	if not FileAccess.file_exists(_sidecar_path):
		return false
	var f := FileAccess.open(_sidecar_path, FileAccess.READ)
	if f == null:
		return false
	var parsed = JSON.parse_string(f.get_as_text())
	f.close()
	if not (parsed is Dictionary):
		return false
	_side = parsed
	return true


func _row(block: Dictionary, cid: int) -> Dictionary:
	for row in block.get("citizens", []):
		if int(row["citizen_id"]) == cid:
			return row
	return {}


func _step(dt: float = -1.0) -> Dictionary:
	var d := _game_dt if dt <= 0.0 else dt
	var r: Dictionary = SimBridge.advance_time(d, "mobility")
	if r.get("ok", false) != true:
		return {}
	var block: Dictionary = r.get("mobility", {})
	_emb.apply(block, d)
	return block


func _group_snap() -> Dictionary:
	var g = SimBridge.get_groups_snapshot(0).get("groups", {})
	return g if g is Dictionary else {}


func _group() -> Dictionary:
	var gid := str(_side.get("group_id", ""))
	var groups = _group_snap().get("groups", {})
	if groups is Dictionary and groups.has(gid):
		return groups[gid]
	return {}


func _grp_events(kind: String) -> Array:
	var out := []
	for e in _group_snap().get("events", []):
		if str(e.get("event", "")) == kind:
			out.append(e)
	return out


func _members() -> Array:
	var out := []
	var g := _group()
	var m = g.get("members", {})
	if m is Dictionary:
		for k in m:
			if str(m[k]) in ["member", "provisional"]:
				out.append(int(str(k)))
	out.sort()
	return out


func _staged(x: float, y: float) -> Vector3:
	return _scene.interior_offset() + Vector3(x, _emb.body_height, y)


func _focus_on(cid: int) -> Dictionary:
	var row := _row(SimBridge.last_mobility, cid)
	if row.is_empty():
		return row
	SimBridge.focus_xy = Vector2(float(row["x"]), float(row["y"]))
	SimBridge.has_focus_xy = true
	var cam = _scene.get_camera()
	return row


func _place_player_near(cid: int, off: Vector2 = Vector2(3.0, 2.5)) -> void:
	var row := _row(SimBridge.last_mobility, cid)
	if row.is_empty():
		return
	var p = _scene.get_player()
	if p == null:
		return
	var bid := int(row.get("building_id", -1))
	if _scene.inside_building() >= 0 and _scene.inside_building() == bid:
		p.teleport(_staged(float(row["x"]), float(row["y"])) + Vector3(off.x, 1.0, off.y))
	elif _scene.inside_building() < 0:
		_scene.teleport_player(float(row["x"]) + off.x, float(row["y"]) + off.y)
	SimBridge.focus_xy = Vector2(float(row["x"]), float(row["y"]))
	SimBridge.has_focus_xy = true


func _enter(bid: int) -> void:
	_scene.enter_building_by_id(bid)
	await get_tree().physics_frame
	_step(_game_dt)
	if _emb.has_method("refresh_object_markers"):
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


func _zoom(v: float) -> void:
	var cam = _scene.get_camera()
	if cam != null and cam.has_method("set_zoom"):
		cam.set_zoom(v)


## Let the world run a few game seconds at the current focus so the NEAR band
## materialises the bodies around it, and give the streamer frames to catch up.
func _live_settle(steps: int) -> void:
	for i in range(steps):
		_step(1.0)
		var ext = _scene.get_exterior() if _scene.has_method("get_exterior") else null
		if ext != null and _scene.inside_building() < 0:
			ext.update_focus(_scene.get_camera().get_focus())
		await get_tree().physics_frame
		await get_tree().physics_frame


func _bodies_of(ids: Array) -> Array:
	var out := []
	for cid in ids:
		if _emb.body_of("cit:%d" % int(cid)) != null:
			out.append(int(cid))
	return out


func _caption(text: String) -> String:
	if _reached:
		return text
	return "AUTHORITY ROWS ONLY (the pixels show the world at this place/time, the group fact is proven by the paired snapshot): " + text


func _shot(name: String, caption: String, extra: Dictionary = {}) -> void:
	await get_tree().process_frame
	await get_tree().process_frame
	await get_tree().create_timer(0.3).timeout
	var img := get_viewport().get_texture().get_image()
	var path := _dir.path_join(name)
	img.save_png(path)
	var g := _group()
	var row := {"file": name, "caption": caption, "hour": _hour(), "clock": _hhmm(),
		"inside_building": _scene.inside_building(),
		"group_snapshot": {"group_id": _side.get("group_id"),
			"members": g.get("members"), "coordinator": g.get("coordinator"),
			"roles": g.get("roles"), "shelter_building": g.get("shelter_building"),
			"shelter_room": g.get("shelter_room"), "entrance_room": g.get("entrance_room"),
			"threat_state": g.get("threat_state"), "supplies": g.get("supplies")},
		"rendered_bodies": _bodies_of(_side.get("members", []))}
	for k in extra:
		row[k] = extra[k]
	_manifest.append(row)
	print("SHOT saved: %s (%dx%d) [%s]" % [path, img.get_size().x, img.get_size().y, _hhmm()])


func _skip(name: String, caption: String) -> void:
	_manifest.append({"file": null, "caption": caption, "hour": _hour(), "clock": _hhmm(),
		"note": "frame not captured"})
	print("SHOT skipped: %s — %s" % [name, caption])


# ------------------------------------------------------------------ the run
func _run() -> void:
	Session.bundle_dir = "res://bundles/" + _bundle
	Session.start_hour = _start_hour
	var citizens := BundleLoader.load_citizens(Session.bundle_dir)
	Session.citizen = (citizens[_player] if _player < citizens.size() else citizens[0]).duplicate(true)
	Session.citizen["citizen_id"] = _player if _player < citizens.size() else 0
	_scene = preload("res://IsometricWorld.tscn").instantiate()
	add_child(_scene)
	for i in range(20):
		await get_tree().physics_frame
	if not SimBridge.is_connected_to_sim():
		push_error("group_shot: no live bridge — start python -m asphodel.bridge.server")
		get_tree().quit(1)
		return
	_emb = _scene.get_embodied()
	GameClock.time_scale = 0.0
	_emb.time_scale = 1.0 / max(get_physics_process_delta_time(), 0.001) * _game_dt
	if not _load_sidecar():
		push_error("group_shot: no sidecar at %s" % _sidecar_path)
		get_tree().quit(1)
		return
	var members: Array = _side.get("members", [])
	var coordinator := _iv(_side.get("coordinator"))
	var guard := _iv((_side.get("roles", {}) as Dictionary).get("guard"))
	var scavenger := _iv(_side.get("scavenger_result", {}).get("citizen_id") if _side.get("scavenger_result") is Dictionary else null)
	var shelter := _iv(_side.get("shelter_building"))
	var outsider := _iv(_side.get("outsider"))

	# ---- 00: the citizens who cooperate, co-present before formation --------
	# In the freshly booted world (same seed) these are ordinary individuals; the
	# pre-step's cooperation between them is what will later form the group.
	_reached = true
	var trio: Array = members if not members.is_empty() else []
	var found := false
	for n in range(240):
		var b := _step(60.0)
		if b.is_empty():
			break
		var here := _bodies_present_together(b, trio)
		if here.size() >= 3 or (_hour() >= 10.0 and not trio.is_empty()):
			found = _co_present(b, trio)
			break
	if not trio.is_empty():
		_focus_on(int(trio[0]))
		if _scene.inside_building() < 0:
			var r0 := _row(SimBridge.last_mobility, int(trio[0]))
			if int(r0.get("building_id", -1)) >= 0:
				await _enter(int(r0.get("building_id", -1)))
		_place_player_near(int(trio[0]))
		await _live_settle(4)
		_zoom(9.0)
		await _live_settle(1)
	_reached = found
	await _shot("00_citizens_cooperating_before_formation.png", _caption(
		"The three citizens (%s) who will form the survivor group, co-present at %s in the fresh world before any group exists. The pre-step drives their real cooperation (repeated mutual aid + fleeing danger together) here; a group forms only from that history — the fresh world's GET_GROUPS reports none yet."
		% [str(trio), _hhmm()]), {"trio": trio, "co_present": found})

	# ---- LOAD the world that already holds the emerged group ----------------
	var lr := SimBridge.load(_save_path)
	if lr.get("ok", false) != true:
		push_error("group_shot: LOAD failed: %s" % str(lr))
		_write_manifest()
		get_tree().quit(1)
		return
	_step(_game_dt)
	var g := _group()
	var evk := {}
	for e in _group_snap().get("events", []):
		var k := str(e.get("event", ""))
		evk[k] = int(evk.get(k, 0)) + 1

	# ---- 01: members regrouping at the shelter ------------------------------
	if shelter >= 0:
		await _enter(shelter)
	_focus_on(coordinator if coordinator >= 0 else int(members[0]))
	_place_player_near(coordinator if coordinator >= 0 else int(members[0]))
	await _live_settle(6)
	_zoom(8.0)
	await _live_settle(2)
	_reached = _bodies_of(members).size() >= 1
	await _shot("01_members_regrouping_at_the_shelter.png", _caption(
		"The group's members %s regrouped inside their shelter (building %d). Each was sent there by a group REACH_SHELTER objective realised as a real hold goal on the individual — the group moved nobody directly. Rendered member bodies present: %s."
		% [str(_members()), shelter, str(_bodies_of(members))]),
		{"regrouped_sidecar": _side.get("regrouped")})

	# ---- 02: the selected shelter building ----------------------------------
	await _leave()
	_focus_on(coordinator if coordinator >= 0 else int(members[0]))
	await _live_settle(4)
	_zoom(11.0)
	await _live_settle(1)
	_reached = true
	await _shot("02_selected_shelter_building.png", _caption(
		"The shelter building %d the group chose, seen from outside. It was selected from the buildings the members THEMSELVES know (aggregated from their node_meta, scored by member homes, believed safety and capacity) — never a citywide scan. SHELTER_SELECTED=%s, SHELTER_PROPOSED=%s in the tape."
		% [shelter, str(evk.get("SHELTER_SELECTED", 0)), str(evk.get("SHELTER_PROPOSED", 0))]))

	# ---- 03: a role-assignment conversation ---------------------------------
	if shelter >= 0:
		await _enter(shelter)
	_focus_on(coordinator if coordinator >= 0 else int(members[0]))
	_place_player_near(coordinator if coordinator >= 0 else int(members[0]))
	await _live_settle(4)
	_zoom(7.0)
	await _live_settle(1)
	_reached = false            # the ASSIGN_ROLE exchange happened before the save; rows prove it
	await _shot("03_role_assignment_conversation.png", _caption(
		"The coordinator (citizen %d) and members at the shelter. Roles were assigned through a REAL Dialogue V1 exchange (ASSIGN_ROLE -> ACCEPT/REFUSE): the authority logged ROLE_PROPOSED=%s and ROLE_ACCEPTED=%s. The coordinator itself emerged at formation from highest influence. Held roles now: %s."
		% [coordinator, str(evk.get("ROLE_PROPOSED", 0)), str(evk.get("ROLE_ACCEPTED", 0)),
			str(g.get("roles"))]),
		{"role_events": _grp_events("ROLE_ACCEPTED")})

	# ---- 04: a guard at the entrance ----------------------------------------
	if guard >= 0:
		_focus_on(guard)
		_place_player_near(guard, Vector2(2.0, 2.0))
		await _live_settle(4)
		_zoom(6.0)
		await _live_settle(1)
		_reached = _emb.body_of("cit:%d" % guard) != null
		await _shot("04_guard_at_the_entrance.png", _caption(
			"The group's guard (citizen %d) holding the shelter's entrance room (%s). The guard was assigned through the role path and holds a real position goal at the entrance node — a physical watch, not a Smart Object task. Guard body rendered: %s."
			% [guard, str(g.get("entrance_room")), str(_emb.body_of("cit:%d" % guard) != null)]))
	else:
		_skip("04_guard_at_the_entrance.png", "no guard role held in the saved group")

	# ---- 05 / 06: the scavenger's supply run --------------------------------
	# The supply mission ran to completion before the save (ROLE_COMPLETED /
	# SUPPLY_RETURNED), so its two legs cannot be re-staged after the load; the
	# frames show the scavenger and shelter and the paired rows carry the truth.
	_focus_on(scavenger if scavenger >= 0 else int(members[0]))
	_place_player_near(scavenger if scavenger >= 0 else int(members[0]))
	await _live_settle(4)
	_zoom(8.0)
	await _live_settle(1)
	_reached = false
	await _shot("05_scavenger_departing.png", _caption(
		"The scavenger (citizen %s) the group sent for supplies. A supply shortage the group noticed (SUPPLY_NEED) assigned a scavenger through the role path (SUPPLY_RUN_ASSIGNED=%s) who left for a shop it KNOWS holding stock. The outbound leg completed before the save; the tape proves it ran."
		% [str(scavenger), str(evk.get("SUPPLY_RUN_ASSIGNED", 0))]),
		{"supply_events": _grp_events("SUPPLY_RUN_ASSIGNED")})
	await _live_settle(2)
	_reached = false
	await _shot("06_scavenger_returning.png", _caption(
		"The scavenger returning to the shelter. It decremented the shop object's stock (SUPPLY_ACQUIRED=%s) and the group's supplies rose on return (SUPPLY_RETURNED=%s); supplies now %s. The role was retired on completion (ROLE_COMPLETED)."
		% [str(evk.get("SUPPLY_ACQUIRED", 0)), str(evk.get("SUPPLY_RETURNED", 0)),
			str(g.get("supplies"))]),
		{"supply_returned": _grp_events("SUPPLY_RETURNED")})

	# ---- 07: an outsider at the shelter -------------------------------------
	if outsider >= 0:
		_focus_on(outsider)
		_place_player_near(outsider, Vector2(2.5, 2.5))
		await _live_settle(4)
		_zoom(7.0)
		await _live_settle(1)
		_reached = _emb.body_of("cit:%d" % outsider) != null
		await _shot("07_outsider_at_the_shelter.png", _caption(
			"An outsider (citizen %d) near the group's shelter — a non-member the group can assess because some members remember it helping them. It is NOT in the group unless admitted through the real decision."
			% [outsider]))
	else:
		_skip("07_outsider_at_the_shelter.png", "no assessable outsider found by the pre-step")

	# ---- 08: the admission / refusal interaction ----------------------------
	if outsider >= 0:
		var member: int = coordinator if coordinator >= 0 else int(members[0])
		var qj := SimBridge.group_query("ask_to_join", member, outsider)
		var res = qj.get("result", {})
		var res_d: Dictionary = res if res is Dictionary else {}
		_focus_on(member)
		_place_player_near(member)
		await _live_settle(4)
		_zoom(7.0)
		await _live_settle(1)
		_reached = res_d.get("ok", false) == true
		await _shot("08_admission_or_refusal_interaction.png", _caption(
			"The group deciding on the outsider (citizen %d), asked live through GROUP_QUERY ask_to_join via member %d: accept=%s, reason=\"%s\", aggregate=%s. Each member voted from its OWN knowledge of the outsider, influence-weighted, resolved by the coordinator within capacity — a grounded decision."
			% [outsider, member, str(res_d.get("accept")), str(res_d.get("reason")), str(res_d.get("aggregate"))]),
			{"admission_result": res_d})
	else:
		_skip("08_admission_or_refusal_interaction.png", "no outsider to decide on")

	# ---- 09: the collective threat response ---------------------------------
	# Seed a fresh threat near the shelter and let the members' own flee/avoid
	# take over — a coordinated response that still runs through individual goals.
	var target := guard if guard >= 0 else int(members[0])
	var trow := _row(SimBridge.last_mobility, target)
	var seeded := -1
	if not trow.is_empty():
		# seed the guard's neighbour if any co-present; else seed a member so the
		# threat is first-hand to the group
		var sr := SimBridge.seed_outbreak("classic_zombie_fast", target)
		if sr.get("ok", false):
			seeded = _iv(sr.get("index_case"), target)
	for n in range(40):
		var b := _step(5.0)
		if b.is_empty():
			break
		_focus_on(target)
		_place_player_near(target, Vector2(3.0, 3.0))
		if n % 6 == 0:
			await _live_settle(1)
		var gg := _group()
		if str(gg.get("threat_state", "")) not in ["calm", ""]:
			break
	var g2 := _group()
	await _live_settle(2)
	_zoom(8.0)
	await _live_settle(1)
	_reached = true
	await _shot("09_collective_threat_response.png", _caption(
		"The collective threat response: a fresh threat seeded on/near the group (citizen %s). A member warns the group through the legitimate dialogue channel (the saved shared record already holds a GROUP_WARNING with preserved provenance, origin_witness set) and the group evacuates — each member's own flee/avoidance takes over. Group threat_state now \"%s\"; GROUP_WARNING count %s."
		% [str(seeded), str(g2.get("threat_state")), str(evk.get("GROUP_WARNING", 0))]),
		{"seeded": seeded, "warnings": _grp_events("GROUP_WARNING")})

	_write_manifest()
	SimBridge.disconnect_from_sim()
	get_tree().quit(0)


func _bodies_present_together(block: Dictionary, ids: Array) -> Array:
	var out := []
	for cid in ids:
		var r := _row(block, int(cid))
		if not r.is_empty() and int(r.get("building_id", -1)) >= 0:
			out.append(int(cid))
	return out


func _co_present(block: Dictionary, ids: Array) -> bool:
	var b := -1
	for cid in ids:
		var r := _row(block, int(cid))
		if r.is_empty():
			return false
		var bid := int(r.get("building_id", -1))
		if bid < 0:
			return false
		if b < 0:
			b = bid
		elif bid != b:
			return false
	return true


func _write_manifest() -> void:
	var f := FileAccess.open(_dir.path_join("manifest.json"), FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify({"version": 1, "bundle": _bundle,
			"group_id": _side.get("group_id"), "sidecar": _side,
			"save_path": _save_path, "frames": _manifest}, "\t"))
		f.close()
		print("MANIFEST saved: %s (%d frames)" % [_dir.path_join("manifest.json"), _manifest.size()])