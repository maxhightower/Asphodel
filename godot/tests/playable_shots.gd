extends Node

## Windows-Playable Convergence V2 visual evidence (§40).
##
## Renders the REAL canonical IsometricWorld scene against the live Python
## authority (protocol v9) and saves a PNG at each converged-system moment, each
## paired in manifest.json with the AUTHORITATIVE bridge data the frame reflects.
##
## This harness mirrors tests/group_shot.gd exactly: it instantiates the real
## res://IsometricWorld.tscn (which brings up the owned authority through
## AuthorityLauncher and START_WORLDs the full certified stack — mobility, work,
## cognition, dialogue, groups), waits for the live bridge, then drives only
## LEGITIMATE player/dev actions (advance the clock, enter a building, TALK,
## SEED_OUTBREAK, SAVE/LOAD) and READ-ONLY observer surfaces (the BuildOverlay,
## the SimulationInspector, the DialoguePanel). It NEVER edits the certified
## sim/visibility scripts and NEVER invents a simulation fact — every value in
## every caption is the authority's own, echoed from a bridge reply.
##
## CAPTIONS separate three things honestly, per §40:
##   * visible_fact          — what the PIXELS actually show.
##   * authoritative_trace   — the paired bridge rows that support the frame.
##   * inference             — what the frame does NOT prove (never "this
##                             screenshot proves hidden cognition").
## A frame that could not be staged faithfully in the render window is marked
## kind="authority_rows_only": the pixels show the world at that place/time and
## the paired rows carry the authoritative truth, explicitly labelled.
##
##   xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 godot --path godot \
##     --rendering-method gl_compatibility --rendering-driver opengl3 \
##     res://tests/PlayableShots.tscn -- --bundle houston --player 82 \
##     --dir docs/windows/evidence_windows \
##     --group-save /tmp/asph_group_save.json --group-sidecar /tmp/asph_group_scenario.json

var _bundle := "houston"
var _player := 82
var _start_hour := 8.0
var _game_dt := 1.0
var _dir := "/tmp/asph_playable_shots"
var _save_path := "/tmp/asph_playable_save.json"
var _group_save := "/tmp/asph_group_save.json"
var _group_sidecar := "/tmp/asph_group_scenario.json"

var _scene: Node3D
var _emb: EmbodiedMobility
var _side := {}
var _manifest := []


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
		elif args[i] == "--group-save" and i + 1 < args.size():
			_group_save = args[i + 1]
		elif args[i] == "--group-sidecar" and i + 1 < args.size():
			_group_sidecar = args[i + 1]
	DirAccess.make_dir_recursive_absolute(_dir)
	await _run()


# ------------------------------------------------------------------ helpers
func _hour() -> float:
	return float(SimBridge.last_summary.get("hour", 0.0))


func _hhmm() -> String:
	var h := _hour()
	return "%02d:%02d" % [int(h), int(floor((h - floor(h)) * 60.0))]


func _rows() -> Array:
	var m = SimBridge.last_mobility
	if not (m is Dictionary):
		return []
	var c = m.get("citizens", [])
	return c if c is Array else []


func _vehicles() -> Array:
	var m = SimBridge.last_mobility
	if not (m is Dictionary):
		return []
	var v = m.get("vehicles", [])
	return v if v is Array else []


func _row(cid: int) -> Dictionary:
	for r in _rows():
		if r is Dictionary and int(r.get("citizen_id", -1)) == cid:
			return r
	return {}


func _step(dt: float = -1.0) -> Dictionary:
	var d := _game_dt if dt <= 0.0 else dt
	var r: Dictionary = SimBridge.advance_time(d, "mobility")
	if r.get("ok", false) != true:
		return {}
	var block: Dictionary = r.get("mobility", {})
	if _emb != null:
		_emb.apply(block, d)
	return block


func _staged(x: float, y: float) -> Vector3:
	return _scene.interior_offset() + Vector3(x, _emb.body_height, y)


func _focus_on(cid: int) -> Dictionary:
	var row := _row(cid)
	if row.is_empty():
		return row
	SimBridge.focus_xy = Vector2(float(row["x"]), float(row["y"]))
	SimBridge.has_focus_xy = true
	return row


func _place_player_near(cid: int, off: Vector2 = Vector2(3.0, 2.5)) -> void:
	var row := _row(cid)
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
	if _emb != null and _emb.has_method("refresh_object_markers"):
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


func _bodies_present(ids: Array) -> Array:
	var out := []
	for cid in ids:
		if _emb != null and _emb.body_of("cit:%d" % int(cid)) != null:
			out.append(int(cid))
	return out


func _surface_at(cid: int) -> float:
	var row := _row(cid)
	if row.is_empty():
		return 0.0
	var ext = _scene.get_exterior() if _scene.has_method("get_exterior") else null
	if ext != null and ext.has_method("surface_height_at"):
		return float(ext.surface_height_at(float(row["x"]), float(row["y"])))
	return 0.0


func _shot(name: String, kind: String, visible_fact: String, trace: String,
		inference: String, authority: Dictionary = {}) -> void:
	await get_tree().process_frame
	await get_tree().process_frame
	await get_tree().create_timer(0.35).timeout
	var img := get_viewport().get_texture().get_image()
	var path := _dir.path_join(name)
	img.save_png(path)
	var non_blank := _non_blank(img)
	var row := {
		"file": name, "kind": kind,
		"visible_fact": visible_fact,
		"authoritative_trace": trace,
		"inference": inference,
		"hour": _hour(), "clock": _hhmm(),
		"inside_building": _scene.inside_building(),
		"size": [img.get_size().x, img.get_size().y],
		"distinct_colors_sampled": non_blank,
		"authority": authority}
	_manifest.append(row)
	print("SHOT %s (%dx%d) colors=%d [%s] kind=%s" % [
		path, img.get_size().x, img.get_size().y, non_blank, _hhmm(), kind])


## Cheap not-solid-colour witness: count distinct sampled pixels on a grid.
func _non_blank(img: Image) -> int:
	var seen := {}
	var w := img.get_size().x
	var h := img.get_size().y
	for gx in range(0, w, maxi(1, int(w / 40))):
		for gy in range(0, h, maxi(1, int(h / 40))):
			seen[img.get_pixel(gx, gy).to_rgba32()] = true
	return seen.size()


func _load_group_sidecar() -> bool:
	if not FileAccess.file_exists(_group_sidecar):
		return false
	var f := FileAccess.open(_group_sidecar, FileAccess.READ)
	if f == null:
		return false
	var parsed = JSON.parse_string(f.get_as_text())
	f.close()
	if not (parsed is Dictionary):
		return false
	_side = parsed
	return true


# ------------------------------------------------------------------ finders
## Exterior "foot" states that EmbodiedMobility renders as a body standing on the
## ground surface (embodied_mobility.apply): a person walking, or walking to/from a
## vehicle on the lot. All are legitimate feet-on-surface evidence; undead excluded.
const FOOT_STATES := ["on_foot", "approaching_vehicle", "entering_vehicle", "exiting_vehicle"]


func _street_citizen() -> int:
	## An ordinary pedestrian on the exterior ground surface (on foot, not inside a
	## building, not undead) that the NEAR band can embody.
	for r in _rows():
		if not (r is Dictionary):
			continue
		if int(r.get("building_id", -1)) >= 0:
			continue
		if str(r.get("state", "")) not in FOOT_STATES:
			continue
		if str(r.get("health", "susceptible")) not in ["susceptible", "exposed"]:
			continue
		return int(r["citizen_id"])
	return -1


func _street_count() -> int:
	var n := 0
	for r in _rows():
		if r is Dictionary and int(r.get("building_id", -1)) < 0 \
				and str(r.get("state", "")) in FOOT_STATES \
				and str(r.get("health", "susceptible")) in ["susceptible", "exposed"]:
			n += 1
	return n


func _busiest_building() -> int:
	## The interior with the most citizens currently inside it working/active —
	## an authentic workplace, discovered from the authority's own rows.
	var counts := {}
	for r in _rows():
		if not (r is Dictionary):
			continue
		var bid := int(r.get("building_id", -1))
		if bid < 0:
			continue
		if str(r.get("state", "")) not in ["doing_activity", "inside_building"]:
			continue
		counts[bid] = int(counts.get(bid, 0)) + 1
	var best := -1
	var best_n := 0
	for bid in counts:
		if int(counts[bid]) > best_n:
			best_n = int(counts[bid])
			best = int(bid)
	return best


func _worker_using(bid: int) -> int:
	## A worker inside `bid` the authority reports as actively USING a smart
	## object (work.phase == "using"), else any indoor worker with a work task.
	var fallback := -1
	for r in _rows():
		if not (r is Dictionary) or int(r.get("building_id", -1)) != bid:
			continue
		var work = r.get("work", {})
		if work is Dictionary and str(work.get("phase", "")) == "using":
			return int(r["citizen_id"])
		if work is Dictionary and (work.get("object_id") != null or str(work.get("phase", "")) != ""):
			fallback = int(r["citizen_id"])
	return fallback


func _co_present_of(citizen_id: int) -> int:
	if citizen_id < 0:
		return -1
	var ctx := SimBridge.get_citizen_context(citizen_id)
	var cx = ctx.get("context", {})
	if cx is Dictionary:
		var near = cx.get("people_nearby", [])
		if near is Array:
			for e in near:
				if e is Dictionary and e.has("citizen_id"):
					return int(e["citizen_id"])
	return -1


func _co_present_pair() -> Array:
	var seen := {}
	var n := 0
	for r in _rows():
		if not (r is Dictionary) or not r.has("citizen_id"):
			continue
		var a := int(r["citizen_id"])
		if seen.has(a):
			continue
		seen[a] = true
		n += 1
		var ctx := SimBridge.get_citizen_context(a)
		var cx = ctx.get("context", {})
		if cx is Dictionary:
			var near = cx.get("people_nearby", [])
			if near is Array:
				for e in near:
					if e is Dictionary and e.has("citizen_id"):
						return [a, int(e["citizen_id"])]
		if n > 60:
			break
	return [-1, -1]


func _undead_body() -> int:
	for r in _rows():
		if not (r is Dictionary):
			continue
		if str(r.get("state", "")) == "undead" or str(r.get("health", "")) == "undead":
			if int(r.get("building_id", -1)) < 0:
				return int(r["citizen_id"])
	return -1


func _outbreak_totals() -> Dictionary:
	var ob := SimBridge.get_outbreak(0)
	var o = ob.get("outbreak", ob)
	if o is Dictionary and o.get("totals") is Dictionary:
		return o["totals"]
	return {}


# ------------------------------------------------------------------ the run
func _run() -> void:
	Session.bundle_dir = "res://bundles/" + _bundle
	Session.start_hour = _start_hour
	var citizens := BundleLoader.load_citizens(Session.bundle_dir)
	Session.citizen = (citizens[_player] if _player < citizens.size() else citizens[0]).duplicate(true)
	Session.citizen["citizen_id"] = _player if _player < citizens.size() else 0
	_scene = preload("res://IsometricWorld.tscn").instantiate()
	add_child(_scene)
	for i in range(30):
		await get_tree().physics_frame
	if not SimBridge.is_connected_to_sim():
		push_error("playable_shots: no live bridge (IsometricWorld/AuthorityLauncher did not connect)")
		_write_manifest()
		get_tree().quit(1)
		return
	_emb = _scene.get_embodied()
	GameClock.time_scale = 0.0
	if _emb != null:
		_emb.time_scale = 1.0 / max(get_physics_process_delta_time(), 0.001) * _game_dt

	var overlay = _scene.get_node_or_null("BuildOverlay")
	var inspector = _scene.get_node_or_null("SimulationInspector")

	# ---- 00: the build / metadata overlay ----------------------------------
	if overlay != null:
		if overlay.has_method("is_shown") and not overlay.is_shown():
			overlay.toggle()
		overlay.refresh()
	await _live_settle(2)
	_zoom(11.0)
	await _live_settle(1)
	var over_render: Dictionary = (overlay.last_render if overlay != null else {})
	await _shot("00_build_metadata.png", "full_render",
		"The BuildOverlay panel (top-left) rendered over the live city: it names this Godot client's build, the authority's sim SHA, the protocol version the client speaks vs the handshake reported, the city, the CONNECTED state, the game clock and which feature flags are on.",
		"Every line is read verbatim from the already-fetched handshake/summary: SimBridge.last_summary + SimBridge.PROTOCOL_VERSION. The paired 'overlay' dict is exactly what the panel displayed.",
		"The overlay proves WHICH client is bound to WHICH authority; it does not by itself prove any downstream system is running (the later frames do).",
		{"overlay": over_render, "sim_sha": SimBridge.last_summary.get("sim_sha"),
			"protocol_reported": SimBridge.last_summary.get("protocol_version"),
			"protocol_speaks": SimBridge.PROTOCOL_VERSION,
			"flags": {"mobility": SimBridge.mobility_enabled, "work": SimBridge.work_enabled,
				"cognition": SimBridge.cognition_enabled, "dialogue": SimBridge.dialogue_enabled,
				"groups": SimBridge.groups_enabled, "outbreak": SimBridge.outbreak_enabled}})

	# ---- 01: ordinary street, embodied citizens ON the ground (§17) --------
	# Advance to the evening commute. Verified against the authority: this houston
	# world keeps citizens indoors ("doing_activity") through the working day and
	# only puts pedestrians on foot in the evening (exterior on_foot: 0 at 08-12h,
	# 26 at 17:00, 51 at 18:30). So we advance until pedestrians appear.
	for n in range(360):
		SimBridge.advance_time(120.0, "mobility")
		if _street_count() >= 5 or _hour() >= 18.6:
			break
	var candidates01 := []
	for r in _rows():
		if r is Dictionary and int(r.get("building_id", -1)) < 0 and str(r.get("state", "")) in FOOT_STATES \
				and str(r.get("health", "susceptible")) in ["susceptible", "exposed"]:
			candidates01.append(int(r["citizen_id"]))
	# Choose the placement that renders the MOST pedestrians standing on the ground,
	# so the feet-on-surface fact reads across several bodies, not just one.
	var scid := -1
	var best_n := 0
	for cand in candidates01.slice(0, 8):
		_focus_on(cand)
		_place_player_near(cand, Vector2(2.8, 2.4))
		await _live_settle(5)
		_zoom(6.0)
		await _live_settle(1)
		var here := _bodies_present(candidates01)
		if here.size() > best_n:
			best_n = here.size()
			scid = cand
		if here.size() >= 3:
			break
	if scid < 0 and not candidates01.is_empty():
		scid = candidates01[0]
	if scid >= 0:
		_focus_on(scid)
		_place_player_near(scid, Vector2(2.8, 2.4))
		await _live_settle(4)
		_zoom(6.0)
		await _live_settle(2)
	var srow := _row(scid)
	var surface := _surface_at(scid)
	var present01 := _bodies_present(candidates01)
	await _shot("01_ordinary_street_citizens.png",
		"full_render" if not present01.is_empty() else "authority_rows_only",
		"An ordinary street with embodied CitizenBody agents standing/walking on the exterior ground. The VISIBLE FACT is feet-on-surface: the bodies rest on the sidewalk/lot they occupy, NOT sunk beneath the raised relief (the §17 ground-height fix seats each body on ExteriorWorld.surface_height_at, not a flat datum).",
		"Focus citizen c%d at authoritative (%s, %s), state=%s; the rendered ground surface height there is %.3f m (a flat datum would be 0). Rendered NEAR bodies present: %s."
			% [scid, str(srow.get("x")), str(srow.get("y")), str(srow.get("state")), surface, str(present01)],
		"The screenshot shows placement on the surface; it does not show WHY a citizen walks there (that is the mobility authority, sampled in the paired rows).",
		{"focus_citizen": scid, "row": srow, "surface_height_m": surface,
			"rendered_bodies": present01})

	# ---- 02: commute — citizens + vehicles moving --------------------------
	var before := {}
	for r in _rows():
		if r is Dictionary:
			before[int(r.get("citizen_id", -1))] = Vector2(float(r.get("x", 0.0)), float(r.get("y", 0.0)))
	var veh_before := _vehicles().size()
	for n in range(10):
		_step(60.0)
	var moved := 0
	for r in _rows():
		if not (r is Dictionary):
			continue
		var cid := int(r.get("citizen_id", -1))
		if before.has(cid) and before[cid].distance_to(Vector2(float(r.get("x", 0.0)), float(r.get("y", 0.0)))) > 1.0:
			moved += 1
	var vlist := _vehicles()
	# Frame where vehicles actually render: stand the camera at a physical-band
	# vehicle so a VehicleBody (and any nearby pedestrians) materialise on the road.
	var vx := 0.0
	var vy := 0.0
	var vfound := false
	for vrow in vlist:
		if vrow is Dictionary and str(vrow.get("band", "")) == "physical" and not bool(vrow.get("parked", false)):
			vx = float(vrow["x"])
			vy = float(vrow["y"])
			vfound = true
			break
	if not vfound:
		for vrow in vlist:
			if vrow is Dictionary and str(vrow.get("band", "")) == "physical":
				vx = float(vrow["x"])
				vy = float(vrow["y"])
				vfound = true
				break
	var focus02 := _street_citizen()
	if vfound:
		_scene.teleport_player(vx + 6.0, vy + 5.0)
		SimBridge.focus_xy = Vector2(vx, vy)
		SimBridge.has_focus_xy = true
		await _live_settle(6)
		_zoom(10.0)
		await _live_settle(2)
	elif focus02 >= 0:
		_focus_on(focus02)
		_place_player_near(focus02, Vector2(5.0, 4.0))
		await _live_settle(5)
		_zoom(9.0)
		await _live_settle(2)
	await _shot("02_commute.png", "full_render",
		"The city mid-commute: embodied pedestrians on the streets and, where the mobility block reports them in the physical band, VehicleBody vehicles on the roads.",
		"A still cannot show motion, but the authoritative rows do: over the 10 minutes advanced between samples, %d citizens changed position by >1 m; the mobility block reports %d vehicles now (was %d). n_vehicles=%s."
			% [moved, vlist.size(), veh_before, str((SimBridge.last_mobility as Dictionary).get("n_vehicles"))],
		"That some bodies stand still in the frame is not evidence of a frozen sim — motion is proven by the paired position deltas, not the pixels.",
		{"citizens_moved_gt1m": moved, "n_vehicles": vlist.size(),
			"sample_minutes": 10, "focus_citizen": focus02, "framed_at_vehicle": vfound})

	# ---- 03: workplace interior (rooms + worker bodies + smart objects) ----
	# advance toward the working day so buildings fill, then enter the busiest.
	for n in range(20):
		_step(120.0)
		if _busiest_building() >= 0:
			break
	var wbid := _busiest_building()
	var rooms := {}
	var workers_inside := []
	if wbid >= 0:
		await _enter(wbid)
		rooms = SimBridge.get_rooms(wbid)
		await _live_settle(4)
		# frame the interior content
		for r in _rows():
			if r is Dictionary and int(r.get("building_id", -1)) == wbid \
					and str(r.get("state", "")) in ["doing_activity", "inside_building"]:
				workers_inside.append(int(r["citizen_id"]))
		if not workers_inside.is_empty():
			_place_player_near(workers_inside[0], Vector2(4.0, 4.0))
		await _live_settle(4)
		_zoom(9.0)
		await _live_settle(2)
	var present03 := _bodies_present(workers_inside)
	var n_objects := (rooms.get("objects", []) as Array).size() if rooms.get("objects") is Array else 0
	await _shot("03_workplace_interior.png",
		"full_render" if wbid >= 0 and not present03.is_empty() else "authority_rows_only",
		"The staged interior of a workplace building (cutaway ceiling/near-walls) with its rooms, its smart-object fixtures, and embodied worker bodies standing inside the rooms.",
		"Entered building %d via SimBridge.enter_building. GET_ROOMS reports %d smart objects in it; %d citizens are inside it (states doing_activity/inside_building): %s. Rendered worker bodies present: %s."
			% [wbid, n_objects, workers_inside.size(), str(workers_inside), str(present03)],
		"The rooms and object positions are authoritative interior descriptors; the frame shows they render, not what any worker is thinking.",
		{"building_id": wbid, "n_smart_objects": n_objects,
			"workers_inside": workers_inside, "rendered_bodies": present03,
			"objects": rooms.get("objects", [])})

	# ---- 04: a worker at a smart object / interaction ----------------------
	var user := _worker_using(wbid) if wbid >= 0 else -1
	var user_work := {}
	if user >= 0:
		if _emb != null and _emb.has_method("refresh_object_markers"):
			_emb.refresh_object_markers()
		_place_player_near(user, Vector2(2.0, 2.0))
		await _live_settle(3)
		_zoom(6.0)
		await _live_settle(2)
		var ur := _row(user)
		if ur.get("work") is Dictionary:
			user_work = ur["work"]
	var present04 := _bodies_present([user]) if user >= 0 else []
	await _shot("04_smart_object_use.png",
		"full_render" if user >= 0 and not present04.is_empty() else "authority_rows_only",
		"A worker body at a smart object inside the workplace; smart objects that currently have a holder are ringed by EmbodiedMobility.refresh_object_markers.",
		"Worker c%d inside building %d; its authoritative work row: %s. Rendered body present: %s."
			% [user, wbid, str(user_work), str(present04)],
		"The highlight reflects the authority's reported work.phase; the pixels do not independently prove the task's internal state (the work row does).",
		{"worker": user, "building_id": wbid, "work": user_work,
			"rendered_bodies": present04})

	# ---- 05: the Simulation Inspector (F3 lens) over a selected NPC --------
	await _leave()
	await _live_settle(2)
	var isel := _street_citizen()
	if isel < 0:
		isel = _player
	if inspector != null:
		inspector.set_selected(isel)
		if inspector.has_method("is_shown") and not inspector.is_shown():
			inspector.toggle()
		inspector.refresh()
	_focus_on(isel)
	_place_player_near(isel, Vector2(4.0, 3.0))
	await _live_settle(3)
	if inspector != null:
		inspector.refresh()
	_zoom(8.0)
	await _live_settle(1)
	var insp_render: Dictionary = (inspector.last_render if inspector != null else {})
	var ctx := SimBridge.get_citizen_context(isel)
	await _shot("05_inspector.png", "full_render",
		"The SimulationInspector overlay (right side) open over selected NPC c%d, laid out with the authority's own identity / physical / behavior / cognition / social / group rows." % isel,
		"The panel is a read-only window: it calls only GET_CITIZEN_CONTEXT / GROUP_QUERY(membership,where) / GET_GROUPS and never a mutating command. The paired 'inspector' dict is exactly what the panel rendered; the 'context' dict is the same GET_CITIZEN_CONTEXT reply.",
		"The screenshot proves the panel DISPLAYS the authority's reported context for c%d. It does NOT prove the NPC 'really thinks' — the cognition is the authority's; the frame only shows the lens is faithful to it." % isel,
		{"selected": isel, "inspector": insp_render,
			"context_ok": ctx.get("ok"), "context": ctx.get("context", {})})

	# hide the inspector so the next exterior frames are not cluttered by the
	# player's own context panel (re-shown for the group frame).
	if inspector != null and inspector.has_method("is_shown") and inspector.is_shown():
		inspector.toggle()

	# ---- 06: a grounded dialogue line from a real TALK ---------------------
	var dlg = _scene.get_dialogue_panel() if _scene.has_method("get_dialogue_panel") else null
	var speaker := -1
	var listener := -1
	var talk_reply := {}
	var lines := []
	if dlg != null:
		# Build candidate co-present pairs. Citizens sharing a building (and room)
		# are genuinely co-present in the authority — the most reliable pairing;
		# people_nearby entries are added as a fallback. TALK is attempted until the
		# authority accepts one (it decides co-presence, never Godot).
		var buckets := {}
		for r in _rows():
			if not (r is Dictionary):
				continue
			var bid := int(r.get("building_id", -1))
			if bid < 0:
				continue
			var rm := -1
			if r.get("work") is Dictionary:
				rm = int((r["work"] as Dictionary).get("room_id", -1))
			var key := "%d:%d" % [bid, rm]
			if not buckets.has(key):
				buckets[key] = []
			buckets[key].append(int(r["citizen_id"]))
		var pairs := []
		for key in buckets:
			var lst = buckets[key]
			if lst.size() >= 2:
				for i in range(min(lst.size(), 4)):
					for j in range(i + 1, min(lst.size(), 4)):
						pairs.append([lst[i], lst[j]])
		for r in _rows():
			if not (r is Dictionary) or not r.has("citizen_id"):
				continue
			var a := int(r["citizen_id"])
			var bcp := _co_present_of(a)
			if bcp >= 0:
				pairs.append([a, bcp])
			if pairs.size() > 150:
				break
		var tried := 0
		for pr in pairs:
			tried += 1
			dlg.player_citizen = int(pr[0])
			dlg.context_subject = -1
			var rep = dlg.open_with(int(pr[1]))
			if rep is Dictionary and rep.get("ok", false) == true:
				speaker = int(pr[0])
				listener = int(pr[1])
				talk_reply = rep
				lines = dlg.authority_lines() if dlg.has_method("authority_lines") else []
				break
			elif dlg.has_method("close"):
				dlg.close()
			if tried >= 90:
				break
		# GREET opened the conversation; elicit an actual SPOKEN line via a bounded
		# question so the panel shows a grounded NPC line, not just the greeting.
		if speaker >= 0:
			dlg.context_building_id = _scene.inside_building()
			for opt in [3, 0, 1, 4]:   # ASK_SAFETY, ASK_FACT, ASK_LOCATION, ASK_FOR_HELP
				var rr = dlg.choose(opt)
				var ll = dlg.authority_lines() if dlg.has_method("authority_lines") else []
				if ll is Array and not (ll as Array).is_empty():
					lines = ll
					talk_reply = rr
					break
	if speaker >= 0:
		_focus_on(speaker)
		_place_player_near(speaker, Vector2(3.0, 2.5))
		await _live_settle(3)
		_zoom(6.5)
		await _live_settle(2)
	var dlg_ok: bool = talk_reply is Dictionary and talk_reply.get("ok", false) == true
	await _shot("06_dialogue.png",
		"full_render" if dlg_ok else "authority_rows_only",
		"The DialoguePanel (bottom-left) showing the line the authority rendered for a real TALK between co-present citizens c%s and c%s." % [str(speaker), str(listener)],
		"The panel is a thin window: it sent TALK GREET through SimBridge and displays acts[i].line VERBATIM (no word composed in Godot). Authority ok=%s; the paired 'lines' are the authority's rendered strings."
			% str(dlg_ok),
		"The frame proves the panel shows the authority's own line; it does not prove the NPC 'meant' it — the DialogueRuntime authored the words.",
		{"speaker": speaker, "listener": listener, "talk_ok": dlg_ok,
			"lines": lines, "warmth": (talk_reply.get("warmth") if talk_reply is Dictionary else null)})
	if dlg != null and dlg.has_method("close"):
		dlg.close()

	# ---- 08: outbreak — a reanimated/undead body rendered ------------------
	var seed_target := _street_citizen()
	var seeded := SimBridge.seed_outbreak("classic_zombie_fast", seed_target)
	var index_case := int(seeded.get("index_case", seed_target)) if seeded.get("ok", false) else -1
	var undead := -1
	for n in range(60):
		_step(20.0)
		undead = _undead_body()
		if undead >= 0:
			break
	if undead >= 0:
		_focus_on(undead)
		_place_player_near(undead, Vector2(2.0, 1.8))
		await _live_settle(3)
		_zoom(4.5)
		# re-frame right before the shot so a wandering undead stays centred
		_focus_on(undead)
		_place_player_near(undead, Vector2(2.0, 1.8))
		await _live_settle(2)
	elif index_case >= 0:
		_focus_on(index_case)
		_place_player_near(index_case, Vector2(4.0, 3.0))
		await _live_settle(3)
		_zoom(8.0)
		await _live_settle(1)
	var totals := _outbreak_totals()
	var present08 := _bodies_present([undead]) if undead >= 0 else []
	await _shot("08_outbreak.png",
		"full_render" if undead >= 0 and not present08.is_empty() else "authority_rows_only",
		"After SEED_OUTBREAK and advancing, %s." % (
			("a reanimated/undead CitizenBody rendered on the street (c%d, shown with the undead look)" % undead)
			if undead >= 0 else
			"the seeded index case at its authoritative location; no body had reanimated yet in this render window"),
		"SEED_OUTBREAK ok=%s index_case=%s (a dev control, Python decides progression). GET_OUTBREAK totals now: %s. Rendered undead body present: %s."
			% [str(seeded.get("ok")), str(index_case), str(totals), str(present08)],
		"The outbreak progression is the authority's; the frame shows the embodied result (an undead body / the index case), not the epidemic model.",
		{"seed_ok": seeded.get("ok"), "index_case": index_case,
			"undead_citizen": undead, "totals": totals, "rendered_bodies": present08})

	# ---- 07: a survivor group at its shelter (build+SAVE pre-step, LOAD) ----
	var have_group := _load_group_sidecar() and FileAccess.file_exists(_group_save)
	var loaded := {}
	if have_group:
		loaded = SimBridge.load(_group_save)
	var grp := {}
	var members: Array = []
	var coordinator := -1
	var shelter := -1
	if loaded.get("ok", false):
		_step(_game_dt)
		coordinator = int(_side.get("coordinator", -1))
		shelter = int(_side.get("shelter_building", -1))
		members = _side.get("members", [])
		var gsnap = SimBridge.get_groups_snapshot(0).get("groups", {})
		var groups = gsnap.get("groups", {}) if gsnap is Dictionary else {}
		if groups is Dictionary and groups.has(str(_side.get("group_id", ""))):
			grp = groups[str(_side.get("group_id"))]
		if shelter >= 0:
			await _enter(shelter)
		var member_ids := []
		for m in members:
			member_ids.append(int(m))
		# frame a member that is actually inside the shelter
		var anchor: int = coordinator if coordinator >= 0 else (int(member_ids[0]) if not member_ids.is_empty() else -1)
		for m in member_ids:
			if int(_row(m).get("building_id", -1)) == shelter:
				anchor = m
				break
		if anchor >= 0:
			_focus_on(anchor)
			_place_player_near(anchor, Vector2(3.0, 2.5))
		await _live_settle(6)
		# if the anchor's body did not materialise, hunt for a member that did
		if _bodies_present(member_ids).is_empty():
			for m in member_ids:
				_focus_on(m)
				_place_player_near(m, Vector2(3.0, 2.5))
				await _live_settle(4)
				if not _bodies_present([m]).is_empty():
					anchor = m
					break
		# the inspector shows the coordinator's GROUP section straight from GET_GROUPS
		if inspector != null:
			inspector.set_selected(coordinator if coordinator >= 0 else anchor)
			if inspector.has_method("is_shown") and not inspector.is_shown():
				inspector.toggle()
			inspector.refresh()
		await _live_settle(2)
		_zoom(8.0)
		await _live_settle(1)
	var present07 := _bodies_present(members)
	await _shot("07_group_shelter.png",
		"full_render" if loaded.get("ok", false) and not present07.is_empty() else "authority_rows_only",
		"A survivor group at its shelter: a member CitizenBody agent inside the shelter interior (building %s), with the SimulationInspector (right) open on coordinator c%d showing its authoritative context — its received group threat-warning memories (WARNED_BY / ATTACK_SEEN) among them — and the event feed showing the group's WARNING_SHARED / WARNING_RECEIVED. (The inspector's explicit [GROUP] section sits below the visible fold; the membership/roles/shelter it names are carried in the paired GET_GROUPS trace.)"
			% [str(shelter), coordinator],
		"The deterministic group was formed + SAVEd by tools/groups_build_scenario.py (real cooperation -> emergence) and LOADed here (ok=%s). GET_GROUPS reports members=%s coordinator=%s shelter_building=%s roles=%s. Rendered member bodies present: %s."
			% [str(loaded.get("ok")), str(grp.get("members", members)), str(grp.get("coordinator", coordinator)),
				str(grp.get("shelter_building", shelter)), str(grp.get("roles")), str(present07)],
		"Membership, roles and the shelter are proven by the paired GET_GROUPS rows, not by the pixels; the frame shows the members are co-located where the authority says the shelter is.",
		{"loaded": loaded.get("ok"), "group_id": _side.get("group_id"),
			"members": grp.get("members", members), "coordinator": grp.get("coordinator", coordinator),
			"roles": grp.get("roles"), "shelter_building": grp.get("shelter_building", shelter),
			"rendered_bodies": present07, "sidecar_members": members})

	# ---- 09: save -> load continuation (same city continuing) --------------
	if _scene.inside_building() >= 0:
		await _leave()
	var pre_hour := _hour()
	var pre_pop := float(SimBridge.last_summary.get("total_pop", -1.0))
	var saved := SimBridge.save(_save_path)
	var reload := {}
	if saved.get("ok", false):
		reload = SimBridge.load(_save_path)
	if reload.get("ok", false):
		_step(_game_dt)
		var focus09 := _street_citizen()
		if focus09 >= 0:
			_focus_on(focus09)
			_place_player_near(focus09, Vector2(4.0, 3.5))
		await _live_settle(5)
		_zoom(9.0)
		await _live_settle(2)
	var post_hour := _hour()
	var post_pop := float(SimBridge.last_summary.get("total_pop", -2.0))
	await _shot("09_saveload_continuation.png",
		"full_render" if reload.get("ok", false) else "authority_rows_only",
		"The same city rendered and continuing after a real SAVE -> LOAD round-trip through the bridge.",
		"SAVE ok=%s -> LOAD ok=%s. Continuity in the authority's own summary: hour %.3f -> %.3f, total_pop %.1f -> %.1f (a clean reload preserves the world state)."
			% [str(saved.get("ok")), str(reload.get("ok")), pre_hour, post_hour, pre_pop, post_pop],
		"The frame shows the city still renders after reload; the state-continuity claim rests on the paired hour/pop trace, not the pixels.",
		{"save_ok": saved.get("ok"), "load_ok": reload.get("ok"),
			"pre_hour": pre_hour, "post_hour": post_hour,
			"pre_pop": pre_pop, "post_pop": post_pop})

	_write_manifest()
	if SimBridge.is_connected_to_sim():
		SimBridge.disconnect_from_sim()
	get_tree().quit(0)


func _write_manifest() -> void:
	var f := FileAccess.open(_dir.path_join("manifest.json"), FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify({
			"version": 1, "milestone": "ASPHODEL_WINDOWS_PLAYABLE_CONVERGENCE_V2",
			"bundle": _bundle, "player_citizen": _player,
			"sim_sha": SimBridge.last_summary.get("sim_sha"),
			"protocol": SimBridge.PROTOCOL_VERSION,
			"scene": "res://IsometricWorld.tscn (real canonical playable)",
			"group_save": _group_save, "group_sidecar": _group_sidecar,
			"frames": _manifest}, "\t"))
		f.close()
		print("MANIFEST %s (%d frames)" % [_dir.path_join("manifest.json"), _manifest.size()])
