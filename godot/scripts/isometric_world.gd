extends Node3D

## Isometric presentation scene for Asphodel (ISO-2/3/6) — a PARALLEL renderer over
## the same authoritative Python world the first-person StreetScene uses. It reuses,
## unchanged:
##   * SimBridge (authoritative command bridge)      — intent in, truth out
##   * GameClock (time / pause / outbreak authority)  — incl. time_scale (ISO-8)
##   * ExteriorWorld (chunked continuous city stream) — real OSM geometry, no tiles
##   * CitizenRender (MultiMesh crowd from snapshots)
##   * InteriorBuilder (authoritative interior descriptors)
##   * BundleLoader / Session / ZoneMap
## and adds only PRESENTATION: an orthographic follow camera, a direct WASD walker
## with no eye-camera, continuous-distance interaction targeting, and an interior
## cutaway. No simulation logic is duplicated here and NO tile authority is
## introduced — the world stays continuous (see docs/findings/FINDINGS_ISO0_SURFACE_CENSUS.md).

const InteriorBuilder = preload("res://scripts/interior_builder.gd")
const ExteriorWorld = preload("res://scripts/exterior_world.gd")
const IsometricCameraScript = preload("res://scripts/isometric_camera.gd")
const IsometricPlayerScript = preload("res://scripts/isometric_player.gd")
const IsometricInteractionScript = preload("res://scripts/isometric_interaction.gd")
const IsometricHighlightScript = preload("res://scripts/isometric_highlight.gd")
const IsometricCutawayScript = preload("res://scripts/isometric_cutaway.gd")

const HEIGHT_SCALE := 3.0
const PLAYER_RADIUS := 0.5
const FALL_KILL_Y := -40.0
const INTERACT_REACH := 8.0
const FIXTURE_REACH := 3.0
const INTERIOR_OFFSET := Vector3(100000.0, 0.0, 0.0)   # legacy far cell (unused; kept for ref)
const INTERIOR_STAGE_ANCHOR := Vector3(0.0, 0.0, 9000.0)  # interior hull centre lands here (clear of city, tight FP)
const EXTERIOR_FOCUS_INTERVAL := 0.5
const FAST_TIME_SCALE := 12.0

# --- presentation nodes -----------------------------------------------------
var _camera: Camera3D
var _player: CharacterBody3D
var _interaction: Node
var _highlight: Node3D
var _cutaway: Node
var _env: Environment
var _sun: DirectionalLight3D
var _exterior: ExteriorWorld = null
var _region_loader: RegionLoader = null
var _citizen_render: Node3D
var _embodied: EmbodiedMobility = null     # NEAR bodies of the embodied mobility runtime
var _has_compiled_world := false

# --- authoritative bookkeeping (identity, not truth) ------------------------
var _zones: Array = []
var _zone_map: ZoneMap
var _current_focus_zone := -1
var _player_home_zone := -1
var _last_render_tick := -1
var _building_centroids: Array = []      # Array[Vector2], index == building_id
var _building_aabb: Array = []           # Array[Rect2],   index == building_id
var _bounds: Rect2
var _spawn_pos: Vector3

# --- interior state ---------------------------------------------------------
var _active_interior: Node3D = null
var _inside_building := -1
## The translation _enter_building staged the active interior with
## (INTERIOR_STAGE_ANCHOR - hull centre). Authoritative interior coordinates are
## WORLD metres, so a point p reported by Python renders at _interior_offset + p.
var _interior_offset := Vector3.ZERO
var _interior_return_pos := Vector3.ZERO

# --- HUD --------------------------------------------------------------------
var _time_label: Label
var _outbreak_label: Label
var _target_label: Label
var _inventory_label: Label
var _status_label: Label
var _pause_layer: CanvasLayer


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	_ensure_input()
	var dir: String = Session.bundle_dir if Session.bundle_dir != "" else "res://sample_bundle"
	var bundle := BundleLoader.load_bundle(dir)
	if bundle.is_empty():
		push_error("isometric_world: failed to load bundle at %s" % dir)
		return
	# Gate I: the schema contract at the Godot boundary. Rendering a bundle we
	# only half-understand would draw a city Python does not believe in, so a
	# version/shape skew stops the scene here rather than downstream.
	var schema_err := BundleLoader.validate_bundle_schema(dir)
	if schema_err != "":
		push_error("isometric_world: bundle schema rejected at %s -- %s" % [dir, schema_err])
		return
	var meta: Dictionary = bundle["meta"]
	_zones = bundle["zones"]
	_add_environment_and_light()
	_bounds = _world_bounds(_zones)
	_has_compiled_world = FileAccess.file_exists(dir.path_join("world/world_meta.json"))
	_build_ground(_bounds)

	var footprints := BundleLoader.load_buildings(dir)
	_index_buildings(footprints)
	if _has_compiled_world:
		_setup_exterior_streaming(dir)
	elif not footprints.is_empty():
		_build_fallback_buildings(footprints)
	_setup_regional_terrain(dir)

	_spawn_player(_bundle_roads(bundle))
	_setup_camera()
	_setup_interaction()
	_build_hud()
	_build_pause_overlay()

	# Focus timer keeps the exterior stream following the camera focus.
	var timer := Timer.new()
	timer.wait_time = EXTERIOR_FOCUS_INTERVAL
	timer.autostart = true
	timer.process_mode = Node.PROCESS_MODE_PAUSABLE
	timer.timeout.connect(_on_focus_timer)
	add_child(timer)

	var start_hour := 8.0
	var c: Dictionary = Session.citizen
	if c.has("spawn_hour"):
		start_hour = float(c["spawn_hour"])
	GameClock.reset()
	GameClock.configure(meta, start_hour)
	_connect_live_world(dir, meta)
	GameClock.ticked.connect(_on_clock_ticked)
	_on_clock_ticked(GameClock.game_day, GameClock.hour, GameClock.outbreak_belief())


func _bundle_roads(bundle: Dictionary) -> Dictionary:
	return bundle.get("roads", {})


# ------------------------------------------------------------------ input
func _ensure_input() -> void:
	var key_binds := {
		"move_forward": KEY_W, "move_back": KEY_S,
		"move_left": KEY_A, "move_right": KEY_D, "sprint": KEY_SHIFT,
		"interact": KEY_E,
		"cam_rotate_left": KEY_BRACKETLEFT, "cam_rotate_right": KEY_BRACKETRIGHT,
		"cam_zoom_in": KEY_EQUAL, "cam_zoom_out": KEY_MINUS,
		"time_pause": KEY_SPACE, "time_fast": KEY_F,
	}
	for action in key_binds:
		if InputMap.has_action(action):
			continue
		InputMap.add_action(action)
		var ev := InputEventKey.new()
		ev.physical_keycode = key_binds[action]
		InputMap.action_add_event(action, ev)


# ------------------------------------------------------------------ geometry
func _world_bounds(zones: Array) -> Rect2:
	var min_x := INF; var min_z := INF; var max_x := -INF; var max_z := -INF
	for z in zones:
		var c: Array = z["center_xy"]
		var e: Array = z["extent"]
		min_x = min(min_x, float(c[0]) - float(e[0]) * 0.5)
		max_x = max(max_x, float(c[0]) + float(e[0]) * 0.5)
		min_z = min(min_z, float(c[1]) - float(e[1]) * 0.5)
		max_z = max(max_z, float(c[1]) + float(e[1]) * 0.5)
	return Rect2(min_x, min_z, max_x - min_x, max_z - min_z)


func _build_ground(b: Rect2) -> void:
	var ground_y := -0.5 if _has_compiled_world else 0.0
	var center := Vector3(b.position.x + b.size.x * 0.5, ground_y, b.position.y + b.size.y * 0.5)
	var sx := b.size.x * 1.4
	var sz := b.size.y * 1.4
	var plane := PlaneMesh.new()
	plane.size = Vector2(sx, sz)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.22, 0.26, 0.24)
	mat.roughness = 1.0
	plane.material = mat
	var mi := MeshInstance3D.new()
	mi.mesh = plane
	mi.position = center
	add_child(mi)
	var body := StaticBody3D.new()
	body.name = "Ground"
	body.collision_layer = CollisionLayers.WORLD_STATIC
	body.collision_mask = 0
	var shape := BoxShape3D.new()
	shape.size = Vector3(sx, 1.0, sz)
	var cs := CollisionShape3D.new()
	cs.shape = shape
	cs.position = center + Vector3(0.0, -0.5, 0.0)
	body.add_child(cs)
	add_child(body)


func _index_buildings(footprints: Array) -> void:
	## Fill index-aligned centroid/AABB tables (index == Python building_id) from the
	## continuous footprint polygons — the load-bearing identity map for interiors /
	## containers / interact. Never snapped to a grid.
	for b in footprints:
		var poly_xy: Array = b.get("poly", [])
		if poly_xy.size() > 0:
			var cx := 0.0; var cy := 0.0
			var bx0 := INF; var by0 := INF; var bx1 := -INF; var by1 := -INF
			for p in poly_xy:
				var px := float(p[0]); var pz := float(p[1])
				cx += px; cy += pz
				bx0 = min(bx0, px); bx1 = max(bx1, px)
				by0 = min(by0, pz); by1 = max(by1, pz)
			_building_centroids.append(Vector2(cx / poly_xy.size(), cy / poly_xy.size()))
			_building_aabb.append(Rect2(bx0, by0, bx1 - bx0, by1 - by0))
		else:
			_building_centroids.append(Vector2(INF, INF))
			_building_aabb.append(Rect2(INF, INF, 0, 0))


func _build_fallback_buildings(footprints: Array) -> void:
	## Minimal exterior for bundles WITHOUT a compiled world/ stream (e.g. the sample
	## bundle): one batched mass mesh + per-building collision, purely so a non-Houston
	## bundle is not an empty void. Real cities use ExteriorWorld instead.
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var body := StaticBody3D.new()
	body.name = "FallbackBuildingCollision"
	body.collision_layer = CollisionLayers.WORLD_STATIC
	body.collision_mask = 0
	add_child(body)
	for b in footprints:
		var poly_xy: Array = b.get("poly", [])
		if poly_xy.size() < 3:
			continue
		var h := float(b.get("height", 6.0)) * HEIGHT_SCALE
		var ring := PackedVector2Array()
		for p in poly_xy:
			ring.append(Vector2(float(p[0]), float(p[1])))
		var col := Color(0.62, 0.64, 0.68).lerp(Color(0.86, 0.87, 0.9),
			clampf(h / (60.0 * HEIGHT_SCALE), 0.0, 1.0))
		st.set_color(Color(0.34, 0.35, 0.39))
		var tris := Geometry2D.triangulate_polygon(ring)
		for i in range(0, tris.size(), 3):
			for k in [tris[i], tris[i + 1], tris[i + 2]]:
				st.set_normal(Vector3.UP)
				st.add_vertex(Vector3(ring[k].x, h, ring[k].y))
		var n := ring.size()
		for i in range(n):
			var a := ring[i]; var c := ring[(i + 1) % n]
			var nrm := Vector3((c.y - a.y), 0.0, -(c.x - a.x)).normalized()
			var a0 := Vector3(a.x, 0.0, a.y); var a1 := Vector3(a.x, h, a.y)
			var c0 := Vector3(c.x, 0.0, c.y); var c1 := Vector3(c.x, h, c.y)
			for v in [a0, c0, c1, a0, c1, a1]:
				st.set_color(col); st.set_normal(nrm); st.add_vertex(v)
	var mesh := st.commit()
	if mesh != null:
		var mi := MeshInstance3D.new()
		mi.mesh = mesh
		var mat := StandardMaterial3D.new()
		mat.vertex_color_use_as_albedo = true
		mat.cull_mode = BaseMaterial3D.CULL_DISABLED
		mi.material_override = mat
		add_child(mi)
	# Per-building box collision so the player can't walk through masses.
	for i in range(_building_aabb.size()):
		var r: Rect2 = _building_aabb[i]
		if r.position.x == INF:
			continue
		var cs := CollisionShape3D.new()
		var shape := BoxShape3D.new()
		shape.size = Vector3(r.size.x, 24.0, r.size.y)
		cs.shape = shape
		cs.position = Vector3(r.position.x + r.size.x * 0.5, 12.0, r.position.y + r.size.y * 0.5)
		body.add_child(cs)


func _setup_regional_terrain(dir: String) -> void:
	## Regional terrain beyond the compiled city (region.json, schema v2). The
	## city itself sits on the plateau at y = 0 — the loader lowers terrain under
	## the city disc and skips chunks the ExteriorWorld ground already covers, so
	## hills/mountains/coast exist because the regional model says so, not
	## because a mesh was placed by hand. Absent region.json => flat world.
	if not FileAccess.file_exists(dir.path_join("region.json")):
		return
	var region := RegionLoader.new()
	region.name = "RegionalTerrain"
	region.bundle_dir = dir
	region.own_atmosphere = false          # the scene owns its WorldEnvironment
	region.omit_city_interior = true
	add_child(region)                      # _ready -> load_region
	_region_loader = region


func get_region_loader() -> RegionLoader:
	return _region_loader


func _setup_exterior_streaming(dir: String) -> void:
	_exterior = ExteriorWorld.new()
	add_child(_exterior)
	if not _exterior.setup(dir):
		push_error("isometric_world: ExteriorWorld.setup failed for %s" % dir)
		return


func _on_focus_timer() -> void:
	# Drive streaming from the camera's continuous ground focus (which follows the
	# player). Freeze while inside a staged interior so the huge offset never thrashes.
	if _exterior == null or _inside_building >= 0:
		return
	var focus := _player.position if _player != null else Vector3.ZERO
	if _camera != null and _camera.has_method("get_focus"):
		focus = _camera.get_focus()
	_exterior.update_focus(focus)


# ------------------------------------------------------------------ env + light
func _add_environment_and_light() -> void:
	_env = Environment.new()
	_env.background_mode = Environment.BG_COLOR
	_env.background_color = Color(0.5, 0.6, 0.72)
	_env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	_env.ambient_light_color = Color(0.62, 0.66, 0.72)
	_env.ambient_light_energy = 0.7
	_env.fog_enabled = true
	_env.fog_light_color = Color(0.5, 0.6, 0.72)
	_env.fog_density = 0.0004
	var we := WorldEnvironment.new()
	we.environment = _env
	add_child(we)
	_sun = DirectionalLight3D.new()
	_sun.rotation_degrees = Vector3(-55.0, -45.0, 0.0)
	_sun.light_energy = 1.1
	_sun.shadow_enabled = true
	add_child(_sun)


# ------------------------------------------------------------------ player + camera
func _spawn_player(roads: Dictionary) -> void:
	var b := _bounds
	var desired := Vector2(b.position.x + b.size.x * 0.5, b.position.y + b.size.y * 0.5)
	var have_citizen := false
	var c: Dictionary = Session.citizen
	if c.has("spawn_xy") and c["spawn_xy"] != null:
		var sp: Array = c["spawn_xy"]
		if sp.size() >= 2:
			desired = Vector2(float(sp[0]), float(sp[1]))
			have_citizen = true
	if not have_citizen:
		var polylines: Array = roads.get("polylines", [])
		if polylines.size() > 0:
			var pts: Array = polylines[0].get("points", [])
			if pts.size() > 0:
				desired = Vector2(float(pts[0][0]), float(pts[0][1]))
	var clear := _find_clear_spawn(desired)
	_spawn_pos = Vector3(clear.x, 3.0, clear.y)

	_player = IsometricPlayerScript.new()
	_player.position = _spawn_pos
	_player.process_mode = Node.PROCESS_MODE_PAUSABLE
	add_child(_player)
	if _exterior != null:
		_exterior.force_materialize(_player.position)


func _setup_camera() -> void:
	_camera = IsometricCameraScript.new()
	add_child(_camera)
	_camera.set_target(_player)
	if _player.has_method("set_camera"):
		_player.set_camera(_camera)
	# Materialize the exterior at the initial camera focus so frame 1 isn't a void.
	if _exterior != null:
		_exterior.force_materialize(_camera.get_focus())


func _find_clear_spawn(desired: Vector2) -> Vector2:
	if not _inside_building_footprint(desired):
		return desired
	for ring in range(1, 16):
		var r := float(ring) * 4.0
		for k in range(8):
			var a := TAU * float(k) / 8.0
			var cand := desired + Vector2(cos(a), sin(a)) * r
			if not _inside_building_footprint(cand):
				return cand
	return desired


func _inside_building_footprint(p: Vector2) -> bool:
	for r in _building_aabb:
		var rr: Rect2 = r
		if rr.position.x == INF:
			continue
		if rr.grow(PLAYER_RADIUS).has_point(p):
			return true
	return false


# ------------------------------------------------------------------ live world
func _connect_live_world(dir: String, meta: Dictionary) -> void:
	var bundle_name := dir.get_file()
	if not SimBridge.connect_to_sim():
		push_warning("isometric_world: no live World bridge — outbreak holds. "
			+ "Start it with: python -m asphodel.bridge.server")
		return
	var opts := {"seed": int(meta.get("seed", 0))}
	# If the flow told us which citizen the player embodies, pass it so the player's
	# home zone is promoted with them (and their identified neighbours) present.
	var pcid := int(Session.citizen.get("citizen_id", -1)) if Session.citizen.has("citizen_id") else -1
	if pcid >= 0:
		opts["player_citizen_id"] = pcid
	# A harness may ask for a specific in-game start hour (Session.start_hour);
	# the authority owns the clock either way.
	if Session.start_hour >= 0.0:
		opts["start_hour"] = Session.start_hour
	var started: Dictionary = SimBridge.start_world(bundle_name, opts)
	if not started.get("ok", false):
		push_warning("isometric_world: START_WORLD failed: %s" % str(started))
		SimBridge.disconnect_from_sim()
		return
	var phz = started.get("player_home_zone")
	_player_home_zone = int(phz) if phz != null else -1
	GameClock.bind_bridge(SimBridge)
	_zone_map = ZoneMap.new()
	_zone_map.load_from_zones(_zones)
	_current_focus_zone = _zone_map.zone_of_xy(_player.position.x, _player.position.z)
	SimBridge.set_focus([_current_focus_zone])
	_citizen_render = load("res://scripts/citizen_render.gd").new()
	_citizen_render.process_mode = Node.PROCESS_MODE_PAUSABLE
	add_child(_citizen_render)
	# Embodied mobility: the movement clock's NEAR band becomes real bodies
	# (CitizenBody / VehicleBody) around the player and reports physics back.
	if SimBridge.mobility_enabled:
		_embodied = EmbodiedMobility.new()
		_embodied.name = "EmbodiedMobility"
		_embodied.process_mode = Node.PROCESS_MODE_PAUSABLE
		# Bodies must keep up with the clock's pacing (game seconds per real second).
		_embodied.time_scale = (24.0 * 3600.0 / GameClock.REAL_SECONDS_PER_DAY) * GameClock.time_scale
		add_child(_embodied)
		GameClock.mobility_updated.connect(_embodied.apply)
		if _player != null:
			SimBridge.focus_xy = Vector2(_player.position.x, _player.position.z)
			SimBridge.has_focus_xy = true
	var snap: Dictionary = SimBridge.snapshot()
	if snap.get("ok", false):
		GameClock.apply_outbreak(SimBridge._mean_belief_from(snap))
		SimBridge.last_world = snap.get("world", {})
		_render_live()


func _render_live() -> void:
	if _citizen_render == null or _current_focus_zone < 0:
		return
	var world: Dictionary = SimBridge.last_world
	if world.is_empty():
		return
	# Promote citizens near the player to high-fidelity avatars, and pick global
	# crowd mesh fidelity from camera zoom (far when zoomed out).
	if _player != null:
		_citizen_render.set_focus_point(_player.global_position)
	if _camera != null and "ortho_size" in _camera:
		var far: bool = float(_camera.ortho_size) > 90.0
		_citizen_render.set_crowd_lod(CitizenMeshes.LOD_FAR if far else CitizenMeshes.LOD_NORMAL)
	_citizen_render.render_snapshot(world, _current_focus_zone,
		_zone_center(_current_focus_zone), _zone_extent(_current_focus_zone))


func _zone_center(zid: int) -> Vector3:
	for zz in _zones:
		if int(zz["id"]) == zid:
			var c: Array = zz["center_xy"]
			return Vector3(float(c[0]), 0.0, float(c[1]))
	return Vector3.ZERO


func _zone_extent(zid: int) -> Vector2:
	for zz in _zones:
		if int(zz["id"]) == zid:
			var e: Array = zz["extent"]
			return Vector2(float(e[0]), float(e[1]))
	return Vector2(400.0, 400.0)


# ------------------------------------------------------------------ per-frame
func _physics_process(_delta: float) -> void:
	if _player != null and _player.position.y < FALL_KILL_Y and _inside_building < 0:
		_player.teleport(_spawn_pos + Vector3(0.0, 2.0, 0.0))
	_update_live_bubble()
	_update_highlight()


func _update_live_bubble() -> void:
	if _zone_map == null or _player == null or not SimBridge.is_connected_to_sim():
		return
	# The player's ground position is the embodied LOD focus (bodies within the
	# physical radius); sent with every ADVANCE_TIME.
	SimBridge.focus_xy = Vector2(_player.position.x, _player.position.z)
	SimBridge.has_focus_xy = true
	if _inside_building >= 0:
		return
	var z := _zone_map.zone_of_xy(_player.position.x, _player.position.z)
	if z != _current_focus_zone and z >= 0:
		_current_focus_zone = z
		SimBridge.set_focus([z])
	var world: Dictionary = SimBridge.last_world
	var tick := int(world.get("tick", -1)) if not world.is_empty() else -1
	if tick != _last_render_tick:
		_last_render_tick = tick
		_render_live()


func _update_highlight() -> void:
	if _highlight == null or _interaction == null or _player == null:
		return
	_highlight.mark_player(_player.global_position)
	var target: Dictionary = _interaction.resolve_target(true)
	if target.is_empty():
		_highlight.clear_target()
		if _target_label != null:
			_target_label.text = ""
	else:
		_highlight.show_target(target.get("position", Vector3.ZERO), int(target.get("kind", 0)))
		if _target_label != null:
			var actions: Array = _interaction.query_affordances(target)
			var verb := str(actions[0]) if actions.size() > 0 else ""
			_target_label.text = "%s   [E / click: %s]" % [_interaction.describe(target), verb]


# ------------------------------------------------------------------ interaction
func _setup_interaction() -> void:
	_highlight = IsometricHighlightScript.new()
	add_child(_highlight)
	_cutaway = IsometricCutawayScript.new()
	add_child(_cutaway)
	_interaction = IsometricInteractionScript.new()
	_interaction.interaction_radius = INTERACT_REACH
	add_child(_interaction)
	_interaction.configure(_player, _camera, Callable(self, "_gather_candidates"))


## Build the candidate entity list for interaction targeting from AUTHORITATIVE
## sources: outdoor citizens from the live snapshot + the nearest enterable
## building; or, when inside, the interior's occupants / fixtures / exit. Every
## candidate carries a real id — never a node name.
func _gather_candidates() -> Array:
	var out: Array = []
	if _inside_building >= 0 and _active_interior != null and is_instance_valid(_active_interior):
		var occ := _active_interior.get_node_or_null("Occupants")
		if occ != null:
			for o in occ.get_children():
				out.append({"kind": IsometricInteraction.OCCUPANT,
					"id": int(o.get_meta("citizen_id", -1)),
					"position": o.global_position, "meta": {}})
		var fx := _active_interior.get_node_or_null("Fixtures")
		if fx != null:
			for f in fx.get_children():
				out.append({"kind": IsometricInteraction.FIXTURE,
					"id": int(f.get_meta("fixture_id", -1)),
					"position": f.global_position,
					"meta": {"building_id": int(f.get_meta("building_id", -1)),
						"container_index": int(f.get_meta("container_index", -1)),
						"label": str(f.name)}})
		var marker := _active_interior.get_node_or_null("ExitMarker")
		if marker != null:
			out.append({"kind": IsometricInteraction.EXIT, "id": _inside_building,
				"position": marker.global_position, "meta": {}})
		return out

	# Outdoors: live citizens in the focus zone.
	if _current_focus_zone >= 0:
		var world: Dictionary = SimBridge.last_world
		var a: Dictionary = world.get("agents", {}).get(str(_current_focus_zone), {})
		var ids: Array = a.get("citizen_id", [])
		var pos: Array = a.get("positions", [])
		var emb: Dictionary = a.get("embodiment", {})
		var world_xy: Array = emb.get("world_xy", [])
		var area: float = float(a.get("area_size", 100.0))
		var half := area * 0.5
		var offset := _zone_center(_current_focus_zone)
		for i in range(ids.size()):
			var cid := int(ids[i])
			if cid < 0:
				continue
			var wp: Vector3
			if world_xy.size() > i and world_xy[i] != null:
				var w: Array = world_xy[i]
				wp = Vector3(float(w[0]), 1.0, float(w[1]))
			else:
				var p: Array = pos[i]
				wp = offset + Vector3(float(p[0]) - half, 1.0, float(p[1]) - half)
			out.append({"kind": IsometricInteraction.CITIZEN, "id": cid,
				"position": wp, "meta": {}})
	# The nearest enterable building at the player's continuous position.
	if _player != null:
		var bid := _nearest_building(Vector2(_player.position.x, _player.position.z))
		if bid >= 0:
			out.append({"kind": IsometricInteraction.BUILDING, "id": bid,
				"position": Vector3(_building_centroids[bid].x, 1.0, _building_centroids[bid].y),
				"meta": {}})
	return out


func _nearest_building(xy: Vector2) -> int:
	var best := -1
	var best_d := INTERACT_REACH * INTERACT_REACH
	for i in range(_building_aabb.size()):
		var r: Rect2 = _building_aabb[i]
		if r.position.x == INF:
			continue
		var dx := maxf(maxf(r.position.x - xy.x, xy.x - (r.position.x + r.size.x)), 0.0)
		var dy := maxf(maxf(r.position.y - xy.y, xy.y - (r.position.y + r.size.y)), 0.0)
		var d := dx * dx + dy * dy
		if d < best_d:
			best_d = d
			best = i
	return best


## Execute the primary affordance of a resolved target through the AUTHORITATIVE
## bridge. Godot applies nothing until Python accepts it. Returns the target acted
## on (or {}). Public so headless tests can drive it deterministically.
func execute_on(target: Dictionary) -> Dictionary:
	if target.is_empty() or not SimBridge.is_connected_to_sim():
		return {}
	match int(target.get("kind", 0)):
		IsometricInteraction.CITIZEN, IsometricInteraction.OCCUPANT:
			var cid := int(target.get("id", -1))
			var r: Dictionary = SimBridge.interact_with(cid)
			if r.get("ok", false):
				_set_status("Met Citizen %d (now in your roster)" % cid)
		IsometricInteraction.BUILDING:
			_enter_building(int(target.get("id", -1)))
		IsometricInteraction.FIXTURE:
			_search_fixture(target)
		IsometricInteraction.EXIT:
			_leave_building()
	_interaction.set_selected(target)
	return target


## Resolve the current target (cursor -> selected -> nearest) and act on it.
func interact() -> Dictionary:
	if _interaction == null:
		return {}
	var target: Dictionary = _interaction.resolve_target(true)
	return execute_on(target)


## Test hook: resolve by NEAREST only (no cursor) and act. Deterministic headless.
func interact_nearest() -> Dictionary:
	if _interaction == null:
		return {}
	return execute_on(_interaction.resolve_target(false))


func _enter_building(bid: int) -> void:
	if bid < 0:
		return
	var gi: Dictionary = SimBridge.get_interior(bid)
	if not gi.get("ok", false):
		return
	var desc: Dictionary = gi.get("interior", {})
	SimBridge.enter_building(bid)
	_interior_return_pos = _player.position
	# Authoritative interior descriptors are in WORLD coordinates (the building's real
	# footprint). Stage the interior by translating it so its hull centre lands on a
	# fixed anchor clear of the city — this keeps float precision tight (unlike the
	# raw ~100k world offset) and puts the player inside the room on entry, while
	# preserving every authoritative id (building/fixture/container/occupant/exit).
	var hull: Array = desc.get("hull", [])
	var hc := Vector3.ZERO
	if hull.size() > 0:
		var sx := 0.0; var sy := 0.0
		for p in hull:
			sx += float(p[0]); sy += float(p[1])
		hc = Vector3(sx / hull.size(), 0.0, sy / hull.size())
	var offset := INTERIOR_STAGE_ANCHOR - hc
	_interior_offset = offset
	_active_interior = InteriorBuilder.build(desc, offset)
	add_child(_active_interior)
	_inside_building = bid
	# ASPHODEL_SMART_OBJECTS_WORK_V1: embody the occupants/workers of THIS
	# building inside the staged interior (authoritative interior positions) and
	# ring the smart objects that currently have a holder.
	if _embodied != null:
		_embodied.set_interior(bid, offset, _active_interior, InteriorBuilder.FLOOR_Y)
		if not SimBridge.last_mobility.is_empty():
			_embodied.apply(SimBridge.last_mobility, 0.0)
		_embodied.refresh_object_markers()
	var ents: Array = desc.get("entrances", [])
	var spawn := offset + hc + Vector3(0, 1.5, 0)
	if ents.size() > 0:
		var e = ents[0]
		spawn = offset + Vector3(
			float(e["x"]) + float(e["nx"]) * 1.5, 1.5,
			float(e["y"]) + float(e["ny"]) * 1.5)
	_player.teleport(spawn)
	if _camera != null and _camera.has_method("settle"):
		_camera.settle()
	# Cutaway: hide the ceiling and the camera-facing walls so the rooms read.
	if _cutaway != null:
		_cutaway.apply(_active_interior, _camera)
	_set_status("Entered building %d (%s) — search fixtures, E at door to leave"
		% [bid, str(desc.get("archetype", "?"))])


func _leave_building() -> void:
	if _active_interior == null:
		return
	var marker := _active_interior.get_node_or_null("ExitMarker")
	if marker != null and _player.position.distance_to(marker.global_position) > 4.0:
		_set_status("Head to the door to leave")
		return
	if _cutaway != null:
		_cutaway.clear()
	if _embodied != null:
		_embodied.clear_interior()
	_active_interior.queue_free()
	_active_interior = null
	_interior_offset = Vector3.ZERO
	var bid := _inside_building
	_inside_building = -1
	SimBridge.leave_building()
	_player.teleport(_interior_return_pos)
	if _camera != null and _camera.has_method("settle"):
		_camera.settle()
	_set_status("Left building %d" % bid)


func _search_fixture(target: Dictionary) -> void:
	var meta: Dictionary = target.get("meta", {})
	var bid := int(meta.get("building_id", -1))
	var ci := int(meta.get("container_index", -1))
	if bid < 0 or ci < 0:
		return
	var searched: Dictionary = SimBridge.search_container(bid, ci)
	if not searched.get("ok", false):
		return
	var contents: Array = searched.get("contents", [])
	if contents.is_empty():
		_set_status("That container is empty")
		return
	var kind := str(contents[0]["kind"])
	var took: Dictionary = SimBridge.take_item(bid, ci, kind, 1)
	if took.get("ok", false):
		_refresh_inventory_hud()
		_set_status("Took %s" % kind)


# ------------------------------------------------------------------ HUD
func _build_hud() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var c: Dictionary = Session.citizen
	var who := Label.new()
	who.text = "" if c.is_empty() else "%s · %s" % [str(c.get("name", "?")), str(c.get("occupation", "?"))]
	who.position = Vector2(16, 12)
	who.add_theme_font_size_override("font_size", 18)
	layer.add_child(who)

	_time_label = _hud_label(layer, Vector2(16, 38), 16, Color(0.85, 0.9, 0.95))
	_outbreak_label = _hud_label(layer, Vector2(16, 60), 16, Color(0.8, 0.85, 0.9))
	_inventory_label = _hud_label(layer, Vector2(16, 86), 14, Color(0.9, 0.95, 0.8))

	var hint := _hud_label(layer, Vector2(16, 132), 13, Color(0.7, 0.75, 0.8))
	hint.text = "WASD move · Shift sprint · E/click interact · [ ] rotate · +/- zoom · Space pause · F fast"

	# Target/context surface (bottom-centre).
	_target_label = Label.new()
	_target_label.add_theme_font_size_override("font_size", 16)
	_target_label.modulate = Color(1.0, 0.97, 0.8)
	_target_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_target_label.anchor_left = 0.0
	_target_label.anchor_right = 1.0
	_target_label.anchor_top = 1.0
	_target_label.anchor_bottom = 1.0
	_target_label.offset_top = -84
	_target_label.offset_bottom = -60
	layer.add_child(_target_label)

	_status_label = Label.new()
	_status_label.add_theme_font_size_override("font_size", 14)
	_status_label.modulate = Color(0.9, 0.95, 1.0)
	_status_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_status_label.anchor_left = 0.0
	_status_label.anchor_right = 1.0
	_status_label.anchor_top = 1.0
	_status_label.anchor_bottom = 1.0
	_status_label.offset_top = -54
	_status_label.offset_bottom = -32
	layer.add_child(_status_label)

	_build_time_controls(layer)
	_refresh_inventory_hud()


func _build_time_controls(layer: CanvasLayer) -> void:
	## ISO-8 hook: a clean home for pause / normal / (future) accelerate-time. Uses
	## GameClock.set_paused + GameClock.time_scale; the fast button is a placeholder
	## for finer future world time, not a baked-in six-hour macro tick.
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 6)
	row.anchor_left = 1.0
	row.anchor_right = 1.0
	row.offset_left = -170
	row.offset_top = 12
	layer.add_child(row)
	row.add_child(_time_button("II", func(): GameClock.set_paused(true)))
	row.add_child(_time_button("▶", func(): GameClock.set_paused(false); GameClock.time_scale = 1.0))
	row.add_child(_time_button("▶▶", func(): GameClock.set_paused(false); GameClock.time_scale = FAST_TIME_SCALE))


func _time_button(text: String, handler: Callable) -> Button:
	var b := Button.new()
	b.text = text
	b.custom_minimum_size = Vector2(48, 30)
	b.process_mode = Node.PROCESS_MODE_ALWAYS
	b.pressed.connect(handler)
	return b


func _hud_label(layer: CanvasLayer, pos: Vector2, size: int, col: Color) -> Label:
	var l := Label.new()
	l.position = pos
	l.add_theme_font_size_override("font_size", size)
	l.modulate = col
	layer.add_child(l)
	return l


func _set_status(text: String) -> void:
	if _status_label != null:
		_status_label.text = text


func _on_clock_ticked(_day: int, _hour: float, outbreak: float) -> void:
	if _time_label != null:
		_time_label.text = GameClock.time_string()
	if _outbreak_label != null:
		_outbreak_label.text = "Outbreak: %d%%" % int(round(outbreak * 100.0))
		_outbreak_label.modulate = Color(0.6, 0.7, 0.8).lerp(Color(1.0, 0.3, 0.25), outbreak)
	_apply_time_and_outbreak(outbreak)


func _apply_time_and_outbreak(outbreak: float) -> void:
	if _env == null or _sun == null:
		return
	var day := GameClock.is_daytime()
	var base_sky := Color(0.5, 0.6, 0.72) if day else Color(0.05, 0.06, 0.1)
	_env.background_color = base_sky.lerp(Color(0.35, 0.08, 0.08), outbreak * 0.7)
	_env.fog_light_color = _env.background_color
	_env.fog_density = 0.0004 + outbreak * 0.002
	_sun.light_energy = (1.1 if day else 0.15) * (1.0 - 0.4 * outbreak)


func _refresh_inventory_hud() -> void:
	if _inventory_label == null or not SimBridge.is_connected_to_sim():
		return
	var inv: Dictionary = SimBridge.inspect_inventory()
	if not inv.get("ok", false):
		return
	var items_d: Dictionary = inv.get("inventory", {})
	var sv: Dictionary = inv.get("survival", {})
	var parts: Array = []
	for k in items_d:
		parts.append("%s x%d" % [k, int(items_d[k])])
	_inventory_label.text = "H:%d T:%d HP:%d\n%s" % [int(sv.get("hunger", 0)),
		int(sv.get("thirst", 0)), int(sv.get("health", 100)), ", ".join(parts)]


# ------------------------------------------------------------------ pause / input
func _build_pause_overlay() -> void:
	_pause_layer = CanvasLayer.new()
	_pause_layer.visible = false
	_pause_layer.process_mode = Node.PROCESS_MODE_ALWAYS
	add_child(_pause_layer)
	var dim := ColorRect.new()
	dim.color = Color(0.0, 0.0, 0.0, 0.6)
	dim.set_anchors_preset(Control.PRESET_FULL_RECT)
	_pause_layer.add_child(dim)
	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	_pause_layer.add_child(center)
	var vb := VBoxContainer.new()
	vb.add_theme_constant_override("separation", 12)
	center.add_child(vb)
	var title := Label.new()
	title.text = "Paused"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 36)
	vb.add_child(title)
	vb.add_child(_overlay_button("Resume", _resume))
	vb.add_child(_overlay_button("Back to Menu", _to_menu))


func _overlay_button(text: String, handler: Callable) -> Button:
	var b := Button.new()
	b.text = text
	b.custom_minimum_size = Vector2(260, 46)
	b.add_theme_font_size_override("font_size", 22)
	b.process_mode = Node.PROCESS_MODE_ALWAYS
	b.pressed.connect(handler)
	return b


func _pause() -> void:
	_pause_layer.visible = true
	GameClock.set_paused(true)


func _resume() -> void:
	_pause_layer.visible = false
	GameClock.set_paused(false)


func _to_menu() -> void:
	GameClock.set_paused(false)
	GameClock.reset()
	if SimBridge.is_connected_to_sim():
		SimBridge.disconnect_from_sim()
	get_tree().change_scene_to_file("res://MainMenu.tscn")


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_cancel"):
		if _pause_layer != null and _pause_layer.visible:
			_resume()
		elif _pause_layer != null:
			_pause()
	elif event.is_action_pressed("interact"):
		interact()
	elif event.is_action_pressed("time_pause"):
		GameClock.toggle_paused()
	elif event.is_action_pressed("time_fast"):
		GameClock.set_paused(false)
		GameClock.time_scale = FAST_TIME_SCALE if GameClock.time_scale < FAST_TIME_SCALE else 1.0
	elif event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		interact()


# ------------------------------------------------------------------ test hooks
func get_player() -> Node3D: return _player
func get_camera() -> Camera3D: return _camera
func get_exterior() -> ExteriorWorld: return _exterior
func get_interaction() -> Node: return _interaction
func get_cutaway() -> Node: return _cutaway
func active_interior() -> Node3D: return _active_interior
func inside_building() -> int: return _inside_building
## The offset the active interior is staged with: world point p (authoritative
## interior metres) renders at interior_offset() + Vector3(p.x, floor_y, p.y).
func interior_offset() -> Vector3: return _interior_offset
func focus_zone() -> int: return _current_focus_zone
func building_count() -> int: return _building_aabb.size()


func get_citizen_render() -> Node3D: return _citizen_render
func get_embodied() -> EmbodiedMobility: return _embodied
func render_live_now() -> void: _render_live()
func gather_candidates() -> Array: return _gather_candidates()
func enter_building_by_id(bid: int) -> void: _enter_building(bid)


## The world-space point the active interior's hull centre is staged at (constant
## by construction — see _enter_building). The room renders here.
func interior_center_world() -> Vector3:
	return INTERIOR_STAGE_ANCHOR


## World-space centre of the active interior's content (fixtures/occupants/exit),
## for framing the cutaway view on the rooms rather than the entrance corner.
func interior_focus_point() -> Vector3:
	if _active_interior == null or not is_instance_valid(_active_interior):
		return Vector3.ZERO
	var acc := Vector3.ZERO
	var n := 0
	for group in ["Fixtures", "Occupants"]:
		var node := _active_interior.get_node_or_null(group)
		if node != null:
			for child in node.get_children():
				acc += child.global_position
				n += 1
	var marker := _active_interior.get_node_or_null("ExitMarker")
	if marker != null:
		acc += marker.global_position
		n += 1
	if n == 0:
		return _active_interior.global_position
	return acc / float(n)


## Test/demo hook: move the player to the most-populated promoted zone and render
## it, so interaction/crowd surfaces have live identified citizens to work with.
## Returns the zone id chosen (or -1). Presentation-only; uses only authoritative
## snapshot data + the existing focus/streaming path.
func focus_populated_zone() -> int:
	if not SimBridge.is_connected_to_sim():
		return -1
	# Prefer the player's own home zone (from START_WORLD): it is promoted with the
	# player + identified neighbours. Focus it, advance to promote, and render.
	var target_zone := _player_home_zone
	if target_zone >= 0:
		var c := _zone_center(target_zone)
		teleport_player(c.x, c.z)
	SimBridge.advance(3, true)
	# Choose the promoted zone that actually has the most identified citizens.
	var agents: Dictionary = SimBridge.last_world.get("agents", {})
	var best_zone := -1
	var best_n := -1
	for zkey in agents:
		var n := 0
		for v in agents[zkey].get("citizen_id", []):
			if int(v) >= 0:
				n += 1
		if n > best_n:
			best_n = n
			best_zone = int(zkey)
	if best_zone >= 0 and best_n > 0:
		var c2 := _zone_center(best_zone)
		teleport_player(c2.x, c2.z)
		SimBridge.advance(2, true)
		_render_live()
		return best_zone
	# else keep the home-zone focus we set above
	_render_live()
	return _current_focus_zone


func leave_current_building() -> void: _leave_building()


func teleport_player(x: float, z: float) -> void:
	## Test/screenshot helper: move the player in continuous coordinates and refocus.
	if _player == null:
		return
	_player.teleport(Vector3(x, 2.0, z))
	if _camera != null and _camera.has_method("settle"):
		_camera.settle()
	if _exterior != null:
		_exterior.force_materialize(_player.position)
	if _zone_map != null and SimBridge.is_connected_to_sim():
		var z2 := _zone_map.zone_of_xy(x, z)
		if z2 >= 0:
			_current_focus_zone = z2
			SimBridge.set_focus([z2])
