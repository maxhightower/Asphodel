extends Node3D

## CitizenRender — draws the authoritative citizen simulation from a live snapshot,
## scalably, as low-poly HUMANOIDS (not capsules). The renderer is a pure CONSUMER
## of `World.snapshot()`: it never decides behaviour, only shows what the
## authoritative Python world reports. It may interpolate between snapshots for
## smoothness and derive a presentation heading, but the truth is always the last
## snapshot — nothing here is ever fed back to the simulation (H16).
##
## Visual LOD (so thousands of *simulated* agents are never thousands of expensive
## nodes — H4/H12):
##   FAR / NORMAL crowd -> a BOUNDED set of MultiMeshInstance3D buckets:
##       12 body buckets keyed on (body_variant, lower-clothing) + 6 hair buckets.
##       Every visible citizen is one instance in a bucket, coloured by its
##       deterministic CitizenVisualIdentity appearance. Global mesh fidelity
##       (LOD_FAR vs LOD_NORMAL) is chosen by the world from camera zoom.
##   NEAR / named / interaction -> a small POOLED set of CitizenAvatar (richer
##       mesh, same shared shader + identity), capped at MAX_AVATARS. Everyone
##       else stays batched.
##
## Appearance is derived ONLY from CitizenVisualIdentity, so a citizen looks the
## same outdoors, indoors, and across every LOD transition (H0/H15). Disease state
## is preserved as a DEBUG marker overlay, decoupled from clothing (H7).
##
## Executed headless in tests/live_bench.gd; wired into isometric_world /
## street_world for play.

const V = preload("res://scripts/citizen_visual_identity.gd")
const M = preload("res://scripts/citizen_meshes.gd")

const MAX_RENDER := 320        # a plausible street crowd, not the whole zone census
const PEDESTRIAN_FRAC := 0.06  # most of a zone is indoors/in vehicles at any moment
const MAX_AVATARS := 24        # bounded high-fidelity near pool (H4)
const NEAR_RADIUS := 22.0      # metres from focus point that promote to an avatar
const TELEPORT_DIST := 12.0    # jump farther than this -> snap, don't lerp through walls

# Disease-state colours (indices match STATE_NAMES: S,E,Ia,Is,R,D). DEBUG ONLY.
const STATE_COLOR := [
	Color(0.70, 0.72, 0.78), Color(0.95, 0.85, 0.35), Color(0.95, 0.55, 0.20),
	Color(0.90, 0.25, 0.20), Color(0.35, 0.65, 0.85), Color(0.15, 0.15, 0.17),
]

var _material: ShaderMaterial
var _buckets: Dictionary = {}        # body*N_LOWER+lower -> MultiMeshInstance3D
var _hair_buckets: Dictionary = {}   # hair variant -> MultiMeshInstance3D
var _avatars: Array = []             # pool of CitizenAvatar
var _labels: Array[Label3D] = []     # pooled nameplates for named crowd (non-avatar)
var _debug_mmi: MultiMeshInstance3D
var _debug_mm: MultiMesh

var crowd_lod := M.LOD_NORMAL
var debug_disease := false
var near_avatars_enabled := true
var _focus_point := Vector3.ZERO
var last_instance_count := 0

# animation + interpolation state (presentation only)
var _anim_time := 0.0
var _last_snap_msec := 0
var _snap_interval := 0.25
var _snap_tick := -1
var _heading: Dictionary = {}        # cid -> yaw (persists across snapshots)
var _prev_pos: Dictionary = {}       # cid -> Vector3 (previous authoritative pos)

# Transform records as PARALLEL PACKED arrays (not dicts): _write_transforms runs
# every frame for interpolation, so the hot loop must avoid per-element dict
# allocation and string-key lookups (that is the sustained per-frame cost, and
# the dominant slice of the per-snapshot apply cost).
var _tr_mm: Array = []               # MultiMesh ref per record
var _tr_slot := PackedInt32Array()
var _tr_kind := PackedInt32Array()   # 0 = crowd body, 1 = hair
var _tr_body := PackedInt32Array()   # body variant (hair lift/scale)
var _tr_prev := PackedVector3Array()
var _tr_tgt := PackedVector3Array()
var _tr_y0 := PackedFloat32Array()
var _tr_y1 := PackedFloat32Array()
var _lbl: Array = []                 # {label, body, prev, tgt, y0, y1} — few (named only)
var _active_avatars: Array = []      # avatar transform records (<= MAX_AVATARS)

# Precomputed per-body head tables (hair lift + scale), so the per-frame hair
# transform never recomputes geometry.
var _head_cy := PackedFloat32Array()
var _head_scale := PackedFloat32Array()
var _head_top := PackedFloat32Array()


func _ready() -> void:
	_material = V.build_material()
	for b in range(V.N_BODY):
		_head_cy.append(M.head_center_y(b))
		_head_scale.append(M.head_radius(b) / M.REF_HEAD_R)
		_head_top.append(M.head_height(b))
	set_process(true)


# --- public configuration (set by the world / tests) -------------------------
func set_focus_point(p: Vector3) -> void: _focus_point = p
func set_crowd_lod(lod: int) -> void: crowd_lod = lod
func set_debug_disease(on: bool) -> void:
	debug_disease = on
	if _debug_mmi != null:
		_debug_mmi.visible = on
func set_near_avatars_enabled(on: bool) -> void: near_avatars_enabled = on


func _process(delta: float) -> void:
	_anim_time += delta
	if _material != null:
		_material.set_shader_parameter("anim_time", _anim_time)
	# Interpolate toward the latest authoritative snapshot for smooth motion.
	var alpha := 1.0
	if _snap_interval > 0.0:
		alpha = clampf(float(Time.get_ticks_msec() - _last_snap_msec) / (_snap_interval * 1000.0), 0.0, 1.0)
	_write_transforms(alpha)


# =========================================================================
# snapshot ingest
# =========================================================================

## Draw one authoritative snapshot's agents for `focus_zone`. Returns the number
## rendered. A promoted zone holds its ENTIRE population (thousands) packed onto a
## small transmission torus; we (a) render at most MAX_RENDER agents — always the
## named ones plus an even sample of the rest — and (b) SPREAD them across the
## zone's real `extent` (metres). Identified citizens carry an absolute world
## position; anonymous fill is placed approximately.
func render_snapshot(snap: Dictionary, focus_zone: int,
		world_offset: Vector3 = Vector3.ZERO,
		extent: Vector2 = Vector2.ZERO) -> int:
	var agents: Dictionary = snap.get("agents", {})
	var a: Dictionary = agents.get(str(focus_zone), {})
	var pos: Array = a.get("positions", [])
	var state: Array = a.get("state", [])
	var citizen_id: Array = a.get("citizen_id", [])
	var named: Array = a.get("named", [])
	var chosen_action: Array = a.get("chosen_action", [])
	var area: float = float(a.get("area_size", 100.0))
	var emb: Dictionary = a.get("embodiment", {})
	var world_xy: Array = emb.get("world_xy", [])
	var movement: Array = emb.get("movement", [])
	var n := pos.size()
	if extent == Vector2.ZERO:
		extent = Vector2(area, area)

	# Track snapshot cadence for interpolation; reset interpolation on a genuinely
	# new tick (demotion/re-promotion produces a fresh tick and must not lerp
	# through stale state).
	var tick := int(snap.get("tick", -1))
	if tick != _snap_tick:
		var now := Time.get_ticks_msec()
		if _last_snap_msec > 0:
			var dt_ms := now - _last_snap_msec
			if dt_ms > 0:
				_snap_interval = clampf(float(dt_ms) / 1000.0, 0.05, 1.0)
		_last_snap_msec = now
		_snap_tick = tick

	# Choose which agents to draw: every named agent, then an even stride sample.
	var idx: Array[int] = []
	for i in range(n):
		if named.size() > i and bool(named[i]):
			idx.append(i)
	var target: int = clampi(int(round(n * PEDESTRIAN_FRAC)), idx.size(), MAX_RENDER)
	var remaining := target - idx.size()
	if remaining > 0 and n > 0:
		var stride: int = max(1, int(ceil(float(n) / float(remaining))))
		var i := 0
		while i < n and idx.size() < target:
			if not (named.size() > i and bool(named[i])):
				idx.append(i)
			i += stride

	# Resolve each drawn agent to (cid, appearance, world pos, gait, named).
	var drawn: Array = []          # array of per-agent dictionaries
	var seen_cids: Dictionary = {}
	for i in idx:
		var cid: int = int(citizen_id[i]) if citizen_id.size() > i else -1
		var appear := V.appearance(cid) if cid >= 0 else V.appearance_from_seed(0x51ED + i * 2654435761)
		var origin := _world_pos(i, pos, world_xy, area, extent, world_offset)
		var mv: String = str(movement[i]) if movement.size() > i else "stationary"
		var act: int = int(chosen_action[i]) if chosen_action.size() > i else 0
		var gait := _gait(mv, act)
		var is_named: bool = named.size() > i and bool(named[i])
		# Interpolation continuity: previous position for identified citizens; new
		# or anonymous ones start pinned (no lerp from nowhere).
		var prev: Vector3 = origin
		if cid >= 0 and _prev_pos.has(cid):
			prev = _prev_pos[cid]
			if prev.distance_to(origin) > TELEPORT_DIST:
				prev = origin
		# Heading from motion; retain last heading when ~stationary; seed for first sight.
		var yaw0: float = _heading.get(cid, _seed_heading(cid, i)) if cid >= 0 else _seed_heading(cid, i)
		var yaw1 := yaw0
		var d := origin - prev
		var flat := Vector2(d.x, d.z)
		if flat.length() > 0.05:
			yaw1 = atan2(d.x, d.z)
		if cid >= 0:
			_heading[cid] = yaw1
			_prev_pos[cid] = origin
		if cid >= 0:
			seen_cids[cid] = true
		drawn.append({"cid": cid, "appear": appear, "target": origin, "prev": prev,
			"yaw0": yaw0, "yaw1": yaw1, "gait": gait, "named": is_named,
			"state": int(state[i]) if state.size() > i else 0})

	# Forget stale interpolation state for citizens no longer drawn (bounded memory,
	# and correct heading when they return).
	_gc_dict(_prev_pos, seen_cids)
	_gc_dict(_heading, seen_cids)

	# Partition into a bounded near-avatar set (identified, close to focus) and the
	# batched crowd. _pick_near flags the chosen records in place.
	if near_avatars_enabled:
		_pick_near(drawn)
	_tr_clear()
	_lbl.clear()
	_active_avatars.clear()
	var crowd_by_bucket: Dictionary = {}
	var hair_by_bucket: Dictionary = {}
	var avatar_i := 0
	var label_i := 0
	var debug_pts: Array = []
	for rec in drawn:
		if debug_disease and int(rec["state"]) != 0:
			debug_pts.append(rec)
		if bool(rec.get("near", false)) and avatar_i < MAX_AVATARS:
			var av := _avatar(avatar_i)
			avatar_i += 1
			av.configure(int(rec["cid"]), rec["appear"], _material, float(rec["gait"]), M.LOD_NEAR)
			if bool(rec["named"]) and int(rec["cid"]) >= 0:
				av.set_nameplate("Citizen %d" % int(rec["cid"]))
			else:
				av.set_nameplate("")
			_active_avatars.append({"avatar": av, "target": rec["target"], "prev": rec["prev"],
				"yaw0": rec["yaw0"], "yaw1": rec["yaw1"]})
		else:
			var appear: Dictionary = rec["appear"]
			var bkey := int(appear["body"]) * V.N_LOWER + int(appear["lower"])
			if not crowd_by_bucket.has(bkey):
				crowd_by_bucket[bkey] = []
			crowd_by_bucket[bkey].append(rec)
			var hv := int(appear["hair"])
			if hv != V.HAIR_BALD:
				if not hair_by_bucket.has(hv):
					hair_by_bucket[hv] = []
				hair_by_bucket[hv].append(rec)
			if bool(rec["named"]) and int(rec["cid"]) >= 0:
				var lbl := _label(label_i)
				label_i += 1
				lbl.text = "Citizen %d" % int(rec["cid"])
				_lbl.append({"label": lbl, "target": rec["target"], "prev": rec["prev"],
					"yaw0": rec["yaw0"], "yaw1": rec["yaw1"], "body": int(appear["body"])})

	_fill_crowd(crowd_by_bucket)
	_fill_hair(hair_by_bucket)
	_release_avatars(avatar_i)
	for j in range(label_i, _labels.size()):
		_labels[j].visible = false
	if debug_disease:
		_fill_debug(debug_pts)

	_write_transforms(1.0)                 # place at authoritative targets immediately
	last_instance_count = idx.size()
	return idx.size()


# =========================================================================
# placement helpers
# =========================================================================

func _world_pos(i: int, pos: Array, world_xy: Array, area: float,
		extent: Vector2, world_offset: Vector3) -> Vector3:
	if world_xy.size() > i and world_xy[i] != null:
		var wp: Array = world_xy[i]
		return Vector3(float(wp[0]), 0.0, float(wp[1]))
	var p: Array = pos[i]
	var fx := (float(p[0]) / area - 0.5) * extent.x
	var fz := (float(p[1]) / area - 0.5) * extent.y
	return Vector3(world_offset.x + fx, 0.0, world_offset.z + fz)


func _gait(movement: String, action: int) -> float:
	# chosen_action index 2 == "flee" (npc.ACTION_NAMES) -> run.
	if action == 2:
		return 1.0
	if movement == "walking" or movement == "commuting":
		return 0.5
	return 0.0


func _seed_heading(cid: int, i: int) -> float:
	var s := V.visual_seed(cid) if cid >= 0 else ((i * 2654435761) & 0x7FFFFFFF)
	return float(s % 628) / 100.0


func _pick_near(drawn: Array) -> void:
	## Flag the <= MAX_AVATARS identified citizens closest to the focus point
	## (named first) as near — those promote to high-fidelity avatars.
	var cand: Array = []
	for rec in drawn:
		if int(rec["cid"]) < 0:
			continue
		var dist: float = _focus_point.distance_to(rec["target"])
		if dist <= NEAR_RADIUS:
			cand.append({"rec": rec, "d": dist, "named": bool(rec["named"])})
	cand.sort_custom(func(x, y):
		if x["named"] != y["named"]:
			return bool(x["named"])
		return float(x["d"]) < float(y["d"]))
	for k in range(min(cand.size(), MAX_AVATARS)):
		cand[k]["rec"]["near"] = true


# =========================================================================
# MultiMesh crowd buckets
# =========================================================================

func _bucket(bkey: int) -> MultiMeshInstance3D:
	if _buckets.has(bkey):
		return _buckets[bkey]
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.use_colors = true
	mm.use_custom_data = true
	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	mmi.material_override = _material
	mmi.name = "CrowdBucket_%d" % bkey
	add_child(mmi)
	_buckets[bkey] = mmi
	return mmi


func _hair_bucket(hv: int) -> MultiMeshInstance3D:
	if _hair_buckets.has(hv):
		return _hair_buckets[hv]
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.use_colors = true
	mm.use_custom_data = true
	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	mmi.material_override = _material
	mmi.name = "HairBucket_%d" % hv
	add_child(mmi)
	_hair_buckets[hv] = mmi
	return mmi


func _fill_crowd(crowd_by_bucket: Dictionary) -> void:
	# Empty every existing bucket first so churn never leaves stale instances.
	for bkey in _buckets:
		_buckets[bkey].multimesh.instance_count = 0
	for bkey in crowd_by_bucket:
		var recs: Array = crowd_by_bucket[bkey]
		var body := int(bkey) / V.N_LOWER
		var lower := int(bkey) % V.N_LOWER
		var mmi := _bucket(bkey)
		var mm := mmi.multimesh
		mm.mesh = M.body_mesh(body, lower, crowd_lod)
		mm.instance_count = recs.size()
		for slot in range(recs.size()):
			var rec: Dictionary = recs[slot]
			var appear: Dictionary = rec["appear"]
			mm.set_instance_color(slot, V.instance_color(appear, float(rec["gait"])))
			mm.set_instance_custom_data(slot, V.instance_custom(appear))
			_tr_append(mm, slot, 0, 0, rec["prev"], rec["target"], float(rec["yaw0"]), float(rec["yaw1"]))


func _fill_hair(hair_by_bucket: Dictionary) -> void:
	for hv in _hair_buckets:
		_hair_buckets[hv].multimesh.instance_count = 0
	for hv in hair_by_bucket:
		var recs: Array = hair_by_bucket[hv]
		var mmi := _hair_bucket(hv)
		var mm := mmi.multimesh
		mm.mesh = M.hair_mesh(int(hv), crowd_lod)
		if mm.mesh == null:
			mm.instance_count = 0
			continue
		mm.instance_count = recs.size()
		for slot in range(recs.size()):
			var rec: Dictionary = recs[slot]
			var appear: Dictionary = rec["appear"]
			var body := int(appear["body"])
			mm.set_instance_color(slot, V.instance_color(appear, float(rec["gait"])))
			mm.set_instance_custom_data(slot, V.instance_custom(appear))
			_tr_append(mm, slot, 1, body, rec["prev"], rec["target"], float(rec["yaw0"]), float(rec["yaw1"]))


# =========================================================================
# per-frame transform write (interpolation + heading + animation anchoring)
# =========================================================================

func _write_transforms(alpha: float) -> void:
	# Hot path — runs every frame. Parallel packed arrays, no dict lookups.
	var up := Vector3.UP
	for i in range(_tr_mm.size()):
		var pos: Vector3 = _tr_prev[i].lerp(_tr_tgt[i], alpha)
		var yaw: float = lerp_angle(_tr_y0[i], _tr_y1[i], alpha)
		if _tr_kind[i] == 0:
			_tr_mm[i].set_instance_transform(_tr_slot[i], Transform3D(Basis(up, yaw), pos))
		else:
			var body := _tr_body[i]
			var s := _head_scale[body]
			var hb := Basis(up, yaw).scaled(Vector3(s, s, s))
			var ho := pos + Vector3(0.0, _head_cy[body], 0.0)
			_tr_mm[i].set_instance_transform(_tr_slot[i], Transform3D(hb, ho))
	for r in _lbl:
		var lp: Vector3 = (r["prev"] as Vector3).lerp(r["target"], alpha)
		var lbl: Label3D = r["label"]
		lbl.position = lp + Vector3(0.0, _head_top[int(r["body"])] + 0.28, 0.0)
		lbl.visible = true
	for r in _active_avatars:
		var av: CitizenAvatar = r["avatar"]
		var pos2: Vector3 = (r["prev"] as Vector3).lerp(r["target"], alpha)
		av.position = pos2
		av.set_heading(lerp_angle(float(r["yaw0"]), float(r["yaw1"]), alpha))


func _tr_clear() -> void:
	_tr_mm.clear()
	_tr_slot.clear(); _tr_kind.clear(); _tr_body.clear()
	_tr_prev.clear(); _tr_tgt.clear(); _tr_y0.clear(); _tr_y1.clear()

func _tr_append(mm: MultiMesh, slot: int, kind: int, body: int,
		prev: Vector3, tgt: Vector3, y0: float, y1: float) -> void:
	_tr_mm.append(mm)
	_tr_slot.append(slot); _tr_kind.append(kind); _tr_body.append(body)
	_tr_prev.append(prev); _tr_tgt.append(tgt); _tr_y0.append(y0); _tr_y1.append(y1)


# =========================================================================
# pools
# =========================================================================

func _avatar(i: int) -> CitizenAvatar:
	while _avatars.size() <= i:
		var av := CitizenAvatar.new()
		add_child(av)
		_avatars.append(av)
	_avatars[i].visible = true
	return _avatars[i]

func _release_avatars(used: int) -> void:
	for j in range(used, _avatars.size()):
		_avatars[j].release()

func _label(i: int) -> Label3D:
	while _labels.size() <= i:
		var lbl := Label3D.new()
		lbl.billboard = BaseMaterial3D.BILLBOARD_ENABLED
		lbl.no_depth_test = true
		lbl.pixel_size = 0.004
		lbl.outline_size = 8
		add_child(lbl)
		_labels.append(lbl)
	_labels[i].visible = true
	return _labels[i]


# =========================================================================
# disease debug overlay (H7) — a small ground marker, clothing untouched
# =========================================================================

func _fill_debug(pts: Array) -> void:
	if _debug_mmi == null:
		var disc := CylinderMesh.new()
		disc.top_radius = 0.35
		disc.bottom_radius = 0.35
		disc.height = 0.02
		disc.radial_segments = 8
		var dmat := StandardMaterial3D.new()
		dmat.vertex_color_use_as_albedo = true
		dmat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		disc.material = dmat
		_debug_mm = MultiMesh.new()
		_debug_mm.transform_format = MultiMesh.TRANSFORM_3D
		_debug_mm.use_colors = true
		_debug_mm.mesh = disc
		_debug_mmi = MultiMeshInstance3D.new()
		_debug_mmi.multimesh = _debug_mm
		_debug_mmi.name = "DiseaseDebug"
		add_child(_debug_mmi)
	_debug_mmi.visible = debug_disease
	_debug_mm.instance_count = pts.size()
	for slot in range(pts.size()):
		var rec: Dictionary = pts[slot]
		var p: Vector3 = rec["target"]
		_debug_mm.set_instance_transform(slot, Transform3D(Basis(), p + Vector3(0, 0.03, 0)))
		_debug_mm.set_instance_color(slot, STATE_COLOR[clampi(int(rec["state"]), 0, STATE_COLOR.size() - 1)])


func _gc_dict(d: Dictionary, keep: Dictionary) -> void:
	var drop: Array = []
	for k in d:
		if not keep.has(k):
			drop.append(k)
	for k in drop:
		d.erase(k)
