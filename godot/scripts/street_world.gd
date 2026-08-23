extends Node3D

## Walkable first-person view of the loaded city. Unlike the earlier version this
## scene is a *client of the authoritative world*: it spawns the selected citizen
## at their real coordinate, drives the GameClock (which advances the outbreak),
## renders blocks at their true footprint, freezes everything on an authoritative
## pause, and recovers the player if they leave the ground.
##
## process_mode is ALWAYS so this node keeps handling Esc while the tree is
## paused; the player and GameClock are PAUSABLE, so they freeze when paused.

const HEIGHT_SCALE := 3.0
const LOW := Color(0.35, 0.45, 0.55)
const HIGH := Color(0.95, 0.85, 0.55)
const PLAYER_RADIUS := 0.5
const FALL_KILL_Y := -40.0          # below this, the player is out of bounds

var _pause_layer: CanvasLayer
var _player: CharacterBody3D
var _spawn_pos: Vector3
var _bounds: Rect2
var _block_boxes: Array = []        # [Vector3(x, z, half_extent), ...]
var _env: Environment
var _sun: DirectionalLight3D
var _time_label: Label
var _outbreak_label: Label

# Live citizen rendering (M6/BW4) + player-position focus (BW3).
var _zones: Array = []
var _zone_map: ZoneMap
var _citizen_render: Node3D
var _traffic: Node3D
var _current_focus_zone: int = -1
var _last_render_tick: int = -1


func _ready() -> void:
	# Keep processing input while paused so Esc can resume.
	process_mode = Node.PROCESS_MODE_ALWAYS
	_ensure_input()
	var dir: String = Session.bundle_dir if Session.bundle_dir != "" else "res://sample_bundle"
	var bundle := BundleLoader.load_bundle(dir)
	if bundle.is_empty():
		push_error("street_world: failed to load bundle at %s — see errors above." % dir)
		return
	var meta: Dictionary = bundle["meta"]
	var zones: Array = bundle["zones"]
	_zones = zones
	_add_environment_and_light()
	_bounds = _world_bounds(zones)
	_build_ground(_bounds)
	# Prefer real (or procedural) building footprints extruded into masses; fall
	# back to the density "blocks" for older bundles that lack buildings.json.
	var footprints := BundleLoader.load_buildings(dir)
	if footprints.is_empty():
		_build_blocks(meta, zones)
	else:
		_build_buildings(footprints)
	_build_roads(bundle["roads"])
	_build_site_detail(footprints, bundle["roads"], int(meta.get("seed", 0)))
	_build_traffic(bundle["roads"])
	_spawn_player(_bounds, bundle["roads"])
	_build_hud()
	_build_pause_overlay()

	# Authoritative clock: start at the citizen's spawn hour; it advances the
	# outbreak while unpaused. The outbreak itself is owned by the live Python
	# World, reached through SimBridge (M1) — not by any baked timeline.
	var start_hour := 8.0
	var c: Dictionary = Session.citizen
	if c.has("spawn_hour"):
		start_hour = float(c["spawn_hour"])
	GameClock.reset()
	GameClock.configure(meta, start_hour)
	_connect_live_world(dir, meta)
	GameClock.ticked.connect(_on_clock_ticked)
	_on_clock_ticked(GameClock.game_day, GameClock.hour, GameClock.outbreak_belief())


func _connect_live_world(dir: String, meta: Dictionary) -> void:
	## Bring up the authoritative Python World for this city and bind it to the
	## clock. If the sim process isn't reachable the scene still runs (the clock
	## keeps time; the outbreak simply holds), so play is never hard-blocked.
	var bundle_name := dir.get_file()          # e.g. res://bundles/houston -> houston
	if not SimBridge.connect_to_sim():
		push_warning("street_world: no live World bridge — outbreak will hold. "
			+ "Start it with: python -m asphodel.bridge.server")
		return
	var opts := {"seed": int(meta.get("seed", 0))}
	var started: Dictionary = SimBridge.start_world(bundle_name, opts)
	if not started.get("ok", false):
		push_warning("street_world: START_WORLD failed: %s" % str(started))
		SimBridge.disconnect_from_sim()
		return
	GameClock.bind_bridge(SimBridge)
	# BW3: resolve the player's world position -> zone via the SAME frame the
	# bundle uses, and focus it so the neighbourhood the player stands in resolves
	# to live agents.
	_zone_map = ZoneMap.new()
	_zone_map.load_from_zones(_zones)
	_current_focus_zone = _zone_map.zone_of_xy(_player.position.x, _player.position.z)
	SimBridge.set_focus([_current_focus_zone])
	# BW4: a MultiMesh renderer that draws the promoted bubble from live snapshots.
	_citizen_render = load("res://scripts/citizen_render.gd").new()
	_citizen_render.process_mode = Node.PROCESS_MODE_PAUSABLE
	add_child(_citizen_render)
	# Prime the initial outbreak from an authoritative snapshot.
	var snap: Dictionary = SimBridge.snapshot()
	if snap.get("ok", false):
		GameClock.apply_outbreak(SimBridge._mean_belief_from(snap))
		SimBridge.last_world = snap.get("world", {})
		_render_live()


# ----------------------------------------------------------------- input setup
func _ensure_input() -> void:
	var binds := {
		"move_forward": KEY_W, "move_back": KEY_S,
		"move_left": KEY_A, "move_right": KEY_D, "sprint": KEY_SHIFT,
		"interact": KEY_E,
	}
	for action in binds:
		if InputMap.has_action(action):
			continue
		InputMap.add_action(action)
		var ev := InputEventKey.new()
		ev.physical_keycode = binds[action]
		InputMap.action_add_event(action, ev)


# --------------------------------------------------------------------- geometry
func _world_bounds(zones: Array) -> Rect2:
	var min_x := INF
	var min_z := INF
	var max_x := -INF
	var max_z := -INF
	for z in zones:
		var c: Array = z["center_xy"]
		var e: Array = z["extent"]
		min_x = min(min_x, float(c[0]) - float(e[0]) * 0.5)
		max_x = max(max_x, float(c[0]) + float(e[0]) * 0.5)
		min_z = min(min_z, float(c[1]) - float(e[1]) * 0.5)
		max_z = max(max_z, float(c[1]) + float(e[1]) * 0.5)
	return Rect2(min_x, min_z, max_x - min_x, max_z - min_z)


func _build_ground(b: Rect2) -> void:
	var center := Vector3(b.position.x + b.size.x * 0.5, 0.0, b.position.y + b.size.y * 0.5)
	var sx := b.size.x * 1.4
	var sz := b.size.y * 1.4

	var plane := PlaneMesh.new()
	plane.size = Vector2(sx, sz)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.22, 0.26, 0.24)   # muted terrain, not near-black
	mat.roughness = 1.0
	plane.material = mat
	var mi := MeshInstance3D.new()
	mi.mesh = plane
	mi.position = center
	add_child(mi)

	var body := StaticBody3D.new()
	var shape := BoxShape3D.new()
	shape.size = Vector3(sx, 1.0, sz)
	var cs := CollisionShape3D.new()
	cs.shape = shape
	cs.position = center + Vector3(0.0, -0.5, 0.0)   # top surface at y=0
	body.add_child(cs)
	add_child(body)


# Building palette + detail metrics.
const BLDG_LOW := Color(0.62, 0.64, 0.68)
const BLDG_HIGH := Color(0.86, 0.87, 0.9)
const PLINTH_DARKEN := 0.62         # ground-floor band tint (walls fade to this at y=0)
const ROOF_COL := Color(0.34, 0.35, 0.39)
const PARAPET_COL := Color(0.28, 0.29, 0.33)
const ROOFUNIT_COL := Color(0.40, 0.41, 0.44)
const PARAPET_H := 0.9              # roof-edge lip height (m)


func _build_buildings(footprints: Array) -> void:
	## Extrude each footprint polygon (real OSM or procedural) into a solid mass:
	## a triangulated roof (its own grey), walls with a darker ground-floor plinth
	## gradient, a parapet lip around the roof edge, and rooftop units on taller
	## buildings. The whole city is one batched ArrayMesh; collision is one box per
	## building. Detail is deterministic from a fixed seed so it's stable per city.
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var body := StaticBody3D.new()
	add_child(body)
	var rng := RandomNumberGenerator.new()
	rng.seed = 0x5EED * 65537 + footprints.size()
	for b in footprints:
		var poly_xy: Array = b.get("poly", [])
		if poly_xy.size() < 3:
			continue
		var h := float(b.get("height", 6.0)) * HEIGHT_SCALE
		var ring := PackedVector2Array()
		var min_x := INF; var min_z := INF; var max_x := -INF; var max_z := -INF
		for p in poly_xy:
			var v := Vector2(float(p[0]), float(p[1]))
			ring.append(v)
			min_x = min(min_x, v.x); max_x = max(max_x, v.x)
			min_z = min(min_z, v.y); max_z = max(max_z, v.y)
		var col := BLDG_LOW.lerp(BLDG_HIGH, clampf(h / (60.0 * HEIGHT_SCALE), 0.0, 1.0))
		var plinth := col.darkened(1.0 - PLINTH_DARKEN)
		# Roof (triangulated at y = h) in its own grey so it reads as a roof.
		st.set_color(ROOF_COL)
		var tris := Geometry2D.triangulate_polygon(ring)
		for i in range(0, tris.size(), 3):
			for k in [tris[i], tris[i + 1], tris[i + 2]]:
				st.set_normal(Vector3.UP)
				st.add_vertex(Vector3(ring[k].x, h, ring[k].y))
		# Walls: a vertical gradient from the darker plinth at the base to the wall
		# colour up top, plus a parapet lip standing above the roof line. Cull is
		# disabled so winding doesn't matter for these placeholder masses.
		var n := ring.size()
		for i in range(n):
			var a := ring[i]
			var c := ring[(i + 1) % n]
			var nrm := Vector3((c.y - a.y), 0.0, -(c.x - a.x)).normalized()
			var a0 := Vector3(a.x, 0.0, a.y)
			var a1 := Vector3(a.x, h, a.y)
			var c0 := Vector3(c.x, 0.0, c.y)
			var c1 := Vector3(c.x, h, c.y)
			# gradient wall: bottom verts plinth, top verts col
			_vc(st, a0, plinth, nrm); _vc(st, c0, plinth, nrm); _vc(st, c1, col, nrm)
			_vc(st, a0, plinth, nrm); _vc(st, c1, col, nrm); _vc(st, a1, col, nrm)
			# parapet lip (h -> h + PARAPET_H) around the edge
			var a2 := Vector3(a.x, h + PARAPET_H, a.y)
			var c2 := Vector3(c.x, h + PARAPET_H, c.y)
			st.set_color(PARAPET_COL)
			for v in [a1, c1, c2, a1, c2, a2]:
				st.set_normal(nrm)
				st.add_vertex(v)
		# Rooftop units on tall-enough, wide-enough buildings — a couple of small
		# boxes so roofs aren't bare planes when seen from above / from a tower.
		var bw := max_x - min_x
		var bd := max_z - min_z
		if h > 15.0 and bw > 10.0 and bd > 10.0:
			var units := 1 + (rng.randi() % 2)
			for _u in range(units):
				var ux := lerpf(min_x + 2.0, max_x - 2.0, rng.randf())
				var uz := lerpf(min_z + 2.0, max_z - 2.0, rng.randf())
				var us := 1.5 + 1.5 * rng.randf()
				var uh := 1.2 + 1.6 * rng.randf()
				_roof_box(st, Vector3(ux, h, uz), us, uh, ROOFUNIT_COL)
		# Collision: a box spanning the footprint bounds.
		if bw > 0.1 and bd > 0.1:
			var cs := CollisionShape3D.new()
			var shape := BoxShape3D.new()
			shape.size = Vector3(bw, h, bd)
			cs.shape = shape
			cs.position = Vector3((min_x + max_x) * 0.5, h * 0.5, (min_z + max_z) * 0.5)
			body.add_child(cs)
	var mat := StandardMaterial3D.new()
	mat.vertex_color_use_as_albedo = true
	mat.roughness = 0.85
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	var mi := MeshInstance3D.new()
	mi.mesh = st.commit()
	mi.material_override = mat
	add_child(mi)


func _vc(st: SurfaceTool, v: Vector3, col: Color, nrm: Vector3) -> void:
	# One coloured, normalled vertex (gradient walls need per-vertex colour).
	st.set_color(col)
	st.set_normal(nrm)
	st.add_vertex(v)


func _roof_box(st: SurfaceTool, base: Vector3, half: float, height: float, col: Color) -> void:
	# A small axis-aligned box sitting on the roof at `base` (its bottom face).
	st.set_color(col)
	var y0 := base.y
	var y1 := base.y + height
	var xs := [base.x - half, base.x + half]
	var zs := [base.z - half, base.z + half]
	# top
	_tri(st, Vector3(xs[0], y1, zs[0]), Vector3(xs[1], y1, zs[0]), Vector3(xs[1], y1, zs[1]), Vector3.UP)
	_tri(st, Vector3(xs[0], y1, zs[0]), Vector3(xs[1], y1, zs[1]), Vector3(xs[0], y1, zs[1]), Vector3.UP)
	# four sides
	var rings := [
		[Vector2(xs[0], zs[0]), Vector2(xs[1], zs[0])],
		[Vector2(xs[1], zs[0]), Vector2(xs[1], zs[1])],
		[Vector2(xs[1], zs[1]), Vector2(xs[0], zs[1])],
		[Vector2(xs[0], zs[1]), Vector2(xs[0], zs[0])]]
	for e in rings:
		var a: Vector2 = e[0]
		var c: Vector2 = e[1]
		var nrm := Vector3((c.y - a.y), 0.0, -(c.x - a.x)).normalized()
		for v in [Vector3(a.x, y0, a.y), Vector3(c.x, y0, c.y), Vector3(c.x, y1, c.y),
				Vector3(a.x, y0, a.y), Vector3(c.x, y1, c.y), Vector3(a.x, y1, a.y)]:
			st.set_normal(nrm)
			st.add_vertex(v)


func _build_blocks(meta: Dictionary, zones: Array) -> void:
	var total := 0
	for z in zones:
		total += (z.get("blocks", []) as Array).size()
	if total == 0:
		return

	var box := BoxMesh.new()
	box.size = Vector3.ONE
	var mat := StandardMaterial3D.new()
	mat.vertex_color_use_as_albedo = true
	mat.roughness = 0.9
	box.material = mat

	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.use_colors = true
	mm.mesh = box
	mm.instance_count = total

	var body := StaticBody3D.new()   # one body, a box shape per building
	add_child(body)

	var i := 0
	for z in zones:
		var density := float(z.get("density", 0.0))
		var col := LOW.lerp(HIGH, clampf(density, 0.0, 1.0))
		for blk in (z.get("blocks", []) as Array):
			var bxy: Array = blk["xy"]
			# Use the block's OWN stored footprint so the visual box and its
			# collision box agree and match the bundle's geometry -- no more
			# constant giant width that punched through roads.
			var side := float(blk.get("footprint", 6.0))
			var h := float(blk["height"]) * HEIGHT_SCALE
			var origin := Vector3(float(bxy[0]), h * 0.5, float(bxy[1]))
			mm.set_instance_transform(i, Transform3D(Basis().scaled(Vector3(side, h, side)), origin))
			mm.set_instance_color(i, col)
			var shape := BoxShape3D.new()
			shape.size = Vector3(side, h, side)
			var cs := CollisionShape3D.new()
			cs.shape = shape
			cs.position = origin
			body.add_child(cs)
			# Remember the XZ footprint for collision-safe player placement.
			_block_boxes.append(Vector3(float(bxy[0]), float(bxy[1]), side * 0.5))
			i += 1

	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	add_child(mmi)


# Road surface colours.
const ASPHALT := Color(0.20, 0.20, 0.23)
const CONCRETE := Color(0.60, 0.60, 0.58)
const BARRIER_COL := Color(0.72, 0.70, 0.62)
const DECK_COL := Color(0.32, 0.32, 0.35)
const PILLAR_COL := Color(0.42, 0.42, 0.45)

# Curb / sidewalk / barrier / elevated-deck heights (metres).
const ROAD_Y := 0.28
const CURB_Y := 0.55
const BARRIER_Y := 1.2
const DECK_Y := 7.0
const DECK_T := 0.7

# White dashed lane markings painted on the roadway top.
const LANE_COL := Color(0.92, 0.92, 0.86)
const LANE_DASH := 4.0        # painted dash length (m)
const LANE_GAP := 5.0         # unpainted gap between dashes (m)
const LANE_W := 0.30          # stripe width (m)
const LANE_Y := ROAD_Y + 0.02 # float just above the asphalt to avoid z-fighting


func _build_roads(roads: Dictionary) -> void:
	## Extruded road network: raised asphalt roadways with concrete curbs/
	## sidewalks; barriers along major roads; and highways (motorway class) carried
	## on an ELEVATED deck on pillars — Houston's elevated freeways. (Bridge/layer
	## data isn't in the bundle, so highway elevation is a class heuristic, not a
	## per-road OSM fact.)
	var polylines: Array = roads.get("polylines", [])
	if polylines.is_empty():
		return
	var st := SurfaceTool.new()      # all opaque road/structure geometry, batched
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	for pl in polylines:
		var pts_raw: Array = pl.get("points", [])
		if pts_raw.size() < 2:
			continue
		var pts: Array = []
		for p in pts_raw:
			pts.append(Vector2(float(p[0]), float(p[1])))
		var cls := String(pl.get("class", ""))
		if cls == "motorway" or cls == "trunk":
			_build_elevated(st, pts, 16.0)          # elevated freeway on pillars
		else:
			var rw := 12.0 if cls == "primary" else 8.0
			var sw := 3.0 if cls == "primary" else 2.2
			_build_surface_road(st, pts, rw, sw, cls == "primary")
	var mat := StandardMaterial3D.new()
	mat.vertex_color_use_as_albedo = true
	mat.roughness = 0.95
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	var mi := MeshInstance3D.new()
	mi.mesh = st.commit()
	mi.material_override = mat
	add_child(mi)


func _build_site_detail(footprints: Array, roads: Dictionary, seed: int) -> void:
	# Presentation-only "stuff between the buildings": parking lots, trees, bushes,
	# fences, and ground-cover patches, placed against an occupancy grid so nothing
	# lands in a wall or on a street. No-op for bundles without real footprints.
	if footprints.is_empty():
		return
	var detail: Node3D = load("res://scripts/site_detail.gd").new()
	add_child(detail)
	detail.build(_bounds, footprints, roads, seed)


func _build_traffic(roads: Dictionary) -> void:
	# Presentation-only vehicles (cars/trucks/bikes) driving the road network.
	var polylines: Array = roads.get("polylines", [])
	if polylines.is_empty():
		return
	var traffic: Node3D = load("res://scripts/traffic.gd").new()
	traffic.process_mode = Node.PROCESS_MODE_PAUSABLE   # freezes with pause
	add_child(traffic)
	traffic.setup(polylines, 900)
	_traffic = traffic


func _build_surface_road(st: SurfaceTool, pts: Array, roadway: float,
		sidewalk: float, barriers: bool) -> void:
	# Raised asphalt roadway + a concrete sidewalk slab down each side; optional
	# low barriers along a major surface road; white dashed lane lines on top.
	var rh := roadway * 0.5
	# Lane-divider offsets across the roadway: a centre line always; wide (primary)
	# roads get quarter lines too, so the lanes read on a multi-lane street.
	var lane_offsets: Array = [0.0]
	if roadway >= 11.0:
		lane_offsets = [-roadway * 0.25, 0.0, roadway * 0.25]
	# Carry each stripe's cumulative distance so the dash pattern is continuous
	# across the polyline's segment joints instead of restarting at every vertex.
	var lane_dist: Array = []
	for _lo in lane_offsets:
		lane_dist.append(0.0)
	for k in range(pts.size() - 1):
		var a: Vector2 = pts[k]
		var b: Vector2 = pts[k + 1]
		var d := b - a
		if d.length() < 0.001:
			continue
		var n := d.orthogonal().normalized()
		_slab(st, a, b, n, -rh, rh, 0.0, ROAD_Y, ASPHALT)                     # roadway
		_slab(st, a, b, n, rh, rh + sidewalk, 0.0, CURB_Y, CONCRETE)         # sidewalk L
		_slab(st, a, b, n, -rh - sidewalk, -rh, 0.0, CURB_Y, CONCRETE)       # sidewalk R
		if barriers:
			_slab(st, a, b, n, rh + sidewalk - 0.3, rh + sidewalk, CURB_Y, BARRIER_Y, BARRIER_COL)
			_slab(st, a, b, n, -rh - sidewalk, -rh - sidewalk + 0.3, CURB_Y, BARRIER_Y, BARRIER_COL)
		for li in range(lane_offsets.size()):
			lane_dist[li] = _lane_dashes(st, a, b, n, float(lane_offsets[li]), float(lane_dist[li]))


func _build_elevated(st: SurfaceTool, pts: Array, deck_w: float) -> void:
	# An elevated highway: a deck slab held up by pillars, with edge barriers.
	var hw := deck_w * 0.5
	for k in range(pts.size() - 1):
		var a: Vector2 = pts[k]
		var b: Vector2 = pts[k + 1]
		var d := b - a
		var seglen := d.length()
		if seglen < 0.001:
			continue
		var n := d.orthogonal().normalized()
		# Deck slab.
		_slab(st, a, b, n, -hw, hw, DECK_Y - DECK_T, DECK_Y, DECK_COL)
		# Edge barriers along the deck.
		_slab(st, a, b, n, hw - 0.4, hw, DECK_Y, DECK_Y + 1.0, BARRIER_COL)
		_slab(st, a, b, n, -hw, -hw + 0.4, DECK_Y, DECK_Y + 1.0, BARRIER_COL)
		# Support pillars every ~45 m under the deck.
		var steps: int = max(1, floori(seglen / 45.0))
		for s in range(steps):
			var t := (float(s) + 0.5) / float(steps)
			var c := a.lerp(b, t)
			_pillar(st, c, 3.0, DECK_Y - DECK_T)


func _lane_dashes(st: SurfaceTool, a: Vector2, b: Vector2, n: Vector2,
		off: float, dist0: float) -> float:
	# Paint the dashed white lane stripe along a->b at perpendicular offset `off`,
	# using `dist0` as the cumulative distance already covered so the dash/gap
	# rhythm carries across segment joins. Returns the new cumulative distance.
	var d := b - a
	var seglen := d.length()
	if seglen < 0.001:
		return dist0
	var dir := d / seglen
	var half_w := LANE_W * 0.5
	var period := LANE_DASH + LANE_GAP
	st.set_color(LANE_COL)
	# Walk the dash indices whose painted span overlaps [dist0, dist0 + seglen].
	var idx := floori(dist0 / period)
	while true:
		var dash_start := float(idx) * period
		idx += 1
		if dash_start > dist0 + seglen:
			break
		var s := maxf(dash_start, dist0)
		var e := minf(dash_start + LANE_DASH, dist0 + seglen)
		if e <= s:
			continue
		var pa := a + dir * (s - dist0) + n * off
		var pb := a + dir * (e - dist0) + n * off
		var p0 := pa - n * half_w
		var p1 := pb - n * half_w
		var p2 := pb + n * half_w
		var p3 := pa + n * half_w
		_tri(st, Vector3(p0.x, LANE_Y, p0.y), Vector3(p1.x, LANE_Y, p1.y), Vector3(p2.x, LANE_Y, p2.y), Vector3.UP)
		_tri(st, Vector3(p0.x, LANE_Y, p0.y), Vector3(p2.x, LANE_Y, p2.y), Vector3(p3.x, LANE_Y, p3.y), Vector3.UP)
	return dist0 + seglen


func _slab(st: SurfaceTool, a: Vector2, b: Vector2, n: Vector2,
		off0: float, off1: float, y0: float, y1: float, color: Color) -> void:
	# A raised rectangular slab between a->b, spanning perpendicular offsets
	# off0..off1 and heights y0..y1: top face + the two long side faces.
	st.set_color(color)
	var a0 := a + n * off0
	var a1 := a + n * off1
	var b0 := b + n * off0
	var b1 := b + n * off1
	# top
	_tri(st, Vector3(a0.x, y1, a0.y), Vector3(a1.x, y1, a1.y), Vector3(b1.x, y1, b1.y), Vector3.UP)
	_tri(st, Vector3(a0.x, y1, a0.y), Vector3(b1.x, y1, b1.y), Vector3(b0.x, y1, b0.y), Vector3.UP)
	# side along off1
	var s1 := Vector3(n.x, 0, n.y)
	_quad(st, Vector3(a1.x, y0, a1.y), Vector3(b1.x, y0, b1.y), Vector3(b1.x, y1, b1.y), Vector3(a1.x, y1, a1.y), s1)
	# side along off0
	_quad(st, Vector3(b0.x, y0, b0.y), Vector3(a0.x, y0, a0.y), Vector3(a0.x, y1, a0.y), Vector3(b0.x, y1, b0.y), -s1)


func _pillar(st: SurfaceTool, c: Vector2, side: float, top: float) -> void:
	st.set_color(PILLAR_COL)
	var h := side * 0.5
	var corners: Array[Vector2] = [Vector2(-h, -h), Vector2(h, -h), Vector2(h, h), Vector2(-h, h)]
	for i in range(4):
		var p: Vector2 = c + corners[i]
		var q: Vector2 = c + corners[(i + 1) % 4]
		_quad(st, Vector3(p.x, 0, p.y), Vector3(q.x, 0, q.y),
			Vector3(q.x, top, q.y), Vector3(p.x, top, p.y),
			Vector3(q.x - p.x, 0, q.y - p.y).cross(Vector3.UP).normalized())


func _tri(st: SurfaceTool, p0: Vector3, p1: Vector3, p2: Vector3, nrm: Vector3) -> void:
	for v in [p0, p1, p2]:
		st.set_normal(nrm)
		st.add_vertex(v)


func _quad(st: SurfaceTool, p0: Vector3, p1: Vector3, p2: Vector3, p3: Vector3, nrm: Vector3) -> void:
	for v in [p0, p1, p2, p0, p2, p3]:
		st.set_normal(nrm)
		st.add_vertex(v)


func _add_environment_and_light() -> void:
	_env = Environment.new()
	_env.background_mode = Environment.BG_COLOR
	_env.background_color = Color(0.5, 0.6, 0.72)
	_env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	_env.ambient_light_color = Color(0.6, 0.64, 0.7)
	_env.ambient_light_energy = 0.6
	_env.fog_enabled = true
	_env.fog_light_color = Color(0.5, 0.6, 0.72)
	_env.fog_density = 0.0006
	var we := WorldEnvironment.new()
	we.environment = _env
	add_child(we)

	_sun = DirectionalLight3D.new()
	_sun.rotation_degrees = Vector3(-50.0, -50.0, 0.0)
	_sun.light_energy = 1.1
	_sun.shadow_enabled = true
	add_child(_sun)


# ----------------------------------------------------------------------- player
func _spawn_player(b: Rect2, roads: Dictionary) -> void:
	# Authoritative spawn: the selected citizen's own coordinate for their state
	# (home when asleep, workplace on shift, a route point mid-commute). Fall
	# back to a road point, then the city centre, only as a documented fail-safe.
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
	_spawn_pos = Vector3(clear.x, 3.0, clear.y)   # a little above ground; falls to floor

	_player = CharacterBody3D.new()
	_player.set_script(load("res://scripts/first_person.gd"))
	_player.position = _spawn_pos
	# PAUSABLE so player physics freezes when the world is paused.
	_player.process_mode = Node.PROCESS_MODE_PAUSABLE
	add_child(_player)


func _find_clear_spawn(desired: Vector2) -> Vector2:
	## Return a point not inside any building footprint. Tries the desired point,
	## then a widening ring of candidates around it, then gives up on the desired
	## point (still above ground, never inside a wall).
	if not _inside_block(desired):
		return desired
	for ring in range(1, 16):
		var r := float(ring) * 4.0
		for k in range(8):
			var a := TAU * float(k) / 8.0
			var cand := desired + Vector2(cos(a), sin(a)) * r
			if not _inside_block(cand):
				return cand
	return desired


func _inside_block(p: Vector2) -> bool:
	for bb in _block_boxes:
		var half: float = bb.z + PLAYER_RADIUS
		if abs(p.x - bb.x) <= half and abs(p.y - bb.y) <= half:
			return true
	return false


# -------------------------------------------------------------------- HUD
func _build_hud() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var c: Dictionary = Session.citizen
	var who := Label.new()
	who.text = "" if c.is_empty() else "%s · %s" % [str(c.get("name", "?")), str(c.get("occupation", "?"))]
	who.position = Vector2(16, 12)
	who.add_theme_font_size_override("font_size", 18)
	layer.add_child(who)

	_time_label = Label.new()
	_time_label.position = Vector2(16, 38)
	_time_label.add_theme_font_size_override("font_size", 16)
	_time_label.modulate = Color(0.85, 0.9, 0.95)
	layer.add_child(_time_label)

	_outbreak_label = Label.new()
	_outbreak_label.position = Vector2(16, 60)
	_outbreak_label.add_theme_font_size_override("font_size", 16)
	layer.add_child(_outbreak_label)

	var hint := Label.new()
	hint.text = "WASD move · Shift sprint · mouse look · Esc menu"
	hint.position = Vector2(16, 86)
	hint.add_theme_font_size_override("font_size", 13)
	hint.modulate = Color(0.7, 0.75, 0.8)
	layer.add_child(hint)


func _on_clock_ticked(_day: int, _hour: float, outbreak: float) -> void:
	if _time_label != null:
		_time_label.text = GameClock.time_string()
	if _outbreak_label != null:
		_outbreak_label.text = "Outbreak: %d%%" % int(round(outbreak * 100.0))
		_outbreak_label.modulate = Color(0.6, 0.7, 0.8).lerp(Color(1.0, 0.3, 0.25), outbreak)
	_apply_time_and_outbreak(outbreak)


func _apply_time_and_outbreak(outbreak: float) -> void:
	# Day/night from the clock hour + an ominous reddening as the outbreak grows,
	# so standing still and watching time pass visibly changes the world.
	if _env == null or _sun == null:
		return
	var day := GameClock.is_daytime()
	var day_sky := Color(0.5, 0.6, 0.72)
	var night_sky := Color(0.04, 0.05, 0.09)
	var base_sky := day_sky if day else night_sky
	var panic_sky := Color(0.35, 0.08, 0.08)
	_env.background_color = base_sky.lerp(panic_sky, outbreak * 0.7)
	_env.fog_light_color = _env.background_color
	_env.fog_density = 0.0006 + outbreak * 0.0025
	_sun.light_energy = (1.1 if day else 0.15) * (1.0 - 0.4 * outbreak)


# ------------------------------------------------------------------ per-frame
func _physics_process(_delta: float) -> void:
	# Out-of-bounds recovery: if the player falls off the finite ground, put them
	# back at a safe spawn instead of falling forever.
	if _player != null and _player.position.y < FALL_KILL_Y:
		_recover_player()
	_update_live_bubble()


func _update_live_bubble() -> void:
	## BW3: as the player crosses a zone boundary, move the authoritative focus so
	## the promoted micro bubble follows them. BW4: re-render when a new snapshot
	## (a new authoritative tick) has arrived. Guarded so an offline scene no-ops.
	if _zone_map == null or _player == null or not SimBridge.is_connected_to_sim():
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


func _render_live() -> void:
	if _citizen_render == null or _current_focus_zone < 0:
		return
	var world: Dictionary = SimBridge.last_world
	if world.is_empty():
		return
	# Place + spread the crowd across the zone's real footprint (not the tiny
	# transmission torus), centred on the zone's world position.
	_citizen_render.render_snapshot(world, _current_focus_zone,
		_zone_center(_current_focus_zone), _zone_extent(_current_focus_zone))


func _zone_extent(zid: int) -> Vector2:
	for zz in _zones:
		if int(zz["id"]) == zid:
			var e: Array = zz["extent"]
			return Vector2(float(e[0]), float(e[1]))
	return Vector2(400.0, 400.0)


func _recover_player() -> void:
	_player.velocity = Vector3.ZERO
	_player.position = _spawn_pos + Vector3(0.0, 2.0, 0.0)


# ------------------------------------------------------------------ pause / Esc
func _build_pause_overlay() -> void:
	_pause_layer = CanvasLayer.new()
	_pause_layer.visible = false
	# The pause UI must keep working while the tree is paused.
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
	b.pressed.connect(handler)
	return b


func _pause() -> void:
	_pause_layer.visible = true
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	GameClock.set_paused(true)          # authoritative: freezes clock + outbreak + player


func _resume() -> void:
	_pause_layer.visible = false
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	GameClock.set_paused(false)


func _to_menu() -> void:
	GameClock.set_paused(false)
	GameClock.reset()
	# Tear down the authoritative world cleanly (sends SHUTDOWN) before leaving.
	if SimBridge.is_connected_to_sim():
		SimBridge.disconnect_from_sim()
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	get_tree().change_scene_to_file("res://MainMenu.tscn")


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_cancel"):
		if _pause_layer != null and _pause_layer.visible:
			_resume()
		elif _pause_layer != null:
			_pause()
	elif event.is_action_pressed("interact"):
		_try_interact()


func _try_interact() -> void:
	## BW5: engage the nearest identified citizen -> authoritative roster. Resolves
	## a citizen_id from the live snapshot and sends INTERACT_WITH; the citizen
	## becomes persistent (named) and is recognisable on return.
	if not SimBridge.is_connected_to_sim() or _current_focus_zone < 0:
		return
	var world: Dictionary = SimBridge.last_world
	var a: Dictionary = world.get("agents", {}).get(str(_current_focus_zone), {})
	var ids: Array = a.get("citizen_id", [])
	var pos: Array = a.get("positions", [])
	var area: float = float(a.get("area_size", 100.0))
	var half := area * 0.5
	var offset := _zone_center(_current_focus_zone)
	var best := -1
	var best_d := INF
	for i in range(ids.size()):
		if int(ids[i]) < 0:
			continue
		var p: Array = pos[i]
		var wp := offset + Vector3(float(p[0]) - half, 0.0, float(p[1]) - half)
		var d := wp.distance_squared_to(_player.position)
		if d < best_d:
			best_d = d
			best = int(ids[i])
	if best >= 0:
		var r: Dictionary = SimBridge.interact_with(best)
		if r.get("ok", false) and _outbreak_label != null:
			_outbreak_label.text = "Met Citizen %d (now in your roster)" % best


func _zone_center(zid: int) -> Vector3:
	for zz in _zones:
		if int(zz["id"]) == zid:
			var c: Array = zz["center_xy"]
			return Vector3(float(c[0]), 0.0, float(c[1]))
	return Vector3.ZERO
