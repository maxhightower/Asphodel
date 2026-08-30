class_name ExteriorWorld
extends Node3D

## Streaming chunk renderer for the compiled exterior world
## (godot/bundles/<city>/world/). Pure presentation: it never touches
## SimBridge/session state and never mutates simulation truth — it only reads
## the compiled `chunks/c_<cx>_<cz>.json.gz` files and materializes/frees
## batched geometry as the focus (the player) moves.
##
## Tiers by chunk-center distance to the focus point (2D xz):
##   T1 <= 1408 m : ground raster mesh + simple building masses.
##   T2 <=  800 m : building grammar detail + road markings + collision.
##   T3 <=  416 m : props/vehicles/trees via MultiMesh.
## Unload happens only once a chunk drifts past its tier radius + HYSTERESIS,
## so a player pacing a tier boundary doesn't thrash load/unload every call.
##
## Contract reference: asphodel/world_source/schema.py (chunk JSON) and
## asphodel/world_source/grammar_tables.py (SURFACE_TYPES / colour hints,
## hardcoded below to match).

const PropMeshes = preload("res://scripts/prop_meshes.gd")

const T1_RADIUS := 1408.0
const T2_RADIUS := 800.0
const T3_RADIUS := 416.0
const HYSTERESIS := 96.0
const BUILD_BUDGET := 2
const UNLOAD_BUDGET := 4
const CACHE_CAP := 96
const CELLS := 128          # 128x128 surface raster per chunk
const CELL_M := 2.0

# --- surface enum (must match asphodel/world_source/grammar_tables.py::SURFACE_TYPES)
const SURFACE_TYPES := [
	"ROAD", "SIDEWALK", "PARKING", "OTHER_IMPERVIOUS", "MAINTAINED_GRASS",
	"ROUGH_VEGETATION", "TREE_CANOPY", "BARE_GROUND", "WATER", "BUILDING",
]
const S_ROAD := 0
const S_SIDEWALK := 1
const S_PARKING := 2
const S_OTHER_IMPERVIOUS := 3
const S_MAINTAINED_GRASS := 4
const S_ROUGH_VEGETATION := 5
const S_TREE_CANOPY := 6
const S_BARE_GROUND := 7
const S_WATER := 8
const S_BUILDING := 9

# --- SURFACE_COLOR_HINTS, hardcoded to match grammar_tables.py exactly.
const SURFACE_COLORS := [
	Color(0.16, 0.16, 0.17),   # ROAD
	Color(0.55, 0.55, 0.55),   # SIDEWALK
	Color(0.22, 0.22, 0.23),   # PARKING
	Color(0.35, 0.35, 0.35),   # OTHER_IMPERVIOUS
	Color(0.30, 0.42, 0.22),   # MAINTAINED_GRASS
	Color(0.33, 0.38, 0.24),   # ROUGH_VEGETATION
	Color(0.20, 0.32, 0.18),   # TREE_CANOPY
	Color(0.45, 0.38, 0.30),   # BARE_GROUND
	Color(0.15, 0.25, 0.35),   # WATER
	Color(0.40, 0.40, 0.40),   # BUILDING (unused directly — painted as OTHER_IMPERVIOUS)
]

const BUILDING_ARCH_COLORS := {
	"DETACHED_RESIDENTIAL": Color(0.70, 0.62, 0.52),
	"MULTIFAMILY": Color(0.62, 0.60, 0.58),
	"SMALL_COMMERCIAL": Color(0.68, 0.66, 0.60),
	"BIG_BOX_COMMERCIAL": Color(0.72, 0.72, 0.70),
	"INDUSTRIAL": Color(0.55, 0.55, 0.58),
	"OFFICE_HIGHRISE": Color(0.60, 0.65, 0.72),
	"CIVIC_SPECIAL": Color(0.66, 0.60, 0.50),
	"GENERIC_UNKNOWN": Color(0.60, 0.60, 0.60),
}
const GLASS_COL := Color(0.10, 0.13, 0.18)
const STOREFRONT_GLASS_COL := Color(0.14, 0.20, 0.24)
const DOOR_COL := Color(0.06, 0.06, 0.07)
const ROOF_COL := Color(0.32, 0.33, 0.36)
const PARAPET_COL := Color(0.26, 0.27, 0.30)
const PARAPET_H := 0.8
const LANE_COL := Color(0.90, 0.90, 0.85)
const DECK_COL := Color(0.32, 0.32, 0.35)
const PILLAR_COL := Color(0.42, 0.42, 0.45)
const BARRIER_COL := Color(0.72, 0.70, 0.62)
const DECK_Y := 7.0
const DECK_T := 0.7

static var _ground_mat: StandardMaterial3D = null
static var _opaque_mat: StandardMaterial3D = null


static func _ground_material() -> StandardMaterial3D:
	if _ground_mat == null:
		_ground_mat = StandardMaterial3D.new()
		_ground_mat.vertex_color_use_as_albedo = true
		_ground_mat.roughness = 1.0
		_ground_mat.cull_mode = BaseMaterial3D.CULL_BACK
	return _ground_mat


static func _shared_opaque_material() -> StandardMaterial3D:
	if _opaque_mat == null:
		_opaque_mat = StandardMaterial3D.new()
		_opaque_mat.vertex_color_use_as_albedo = true
		_opaque_mat.roughness = 0.9
		_opaque_mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	return _opaque_mat


# ------------------------------------------------------------------- world state
var _world_dir: String = ""
var _ready_ok: bool = false
var _chunk_size: float = 256.0
var _min_x: float = 0.0
var _min_z: float = 0.0
var _cols: int = 0
var _rows: int = 0

# Parsed-chunk-JSON LRU cache: key "cx_cz" -> Dictionary.
var _chunk_cache: Dictionary = {}
var _chunk_cache_touch: Dictionary = {}     # key -> monotonic access counter
var _cache_clock: int = 0

# Resident chunks: key "cx_cz" -> {cx, cz, nodes: {1:Node3D,2:Node3D,3:Node3D}, stats: {tier:Dictionary}}
var _resident: Dictionary = {}

# Perf certification (BW/OW harness reads this — see tests/): per-tier build
# time in milliseconds for every _ensure_tier call this session, keyed by
# tier (1/2/3) -> Array[float ms]. Pure bookkeeping; never affects behaviour.
var last_build_ms: Dictionary = {1: [], 2: [], 3: []}


# ------------------------------------------------------------------------- setup
func setup(bundle_dir: String) -> bool:
	var meta_path := bundle_dir.path_join("world/world_meta.json")
	if not FileAccess.file_exists(meta_path):
		return false
	var text := FileAccess.get_file_as_string(meta_path)
	var parsed: Variant = JSON.parse_string(text)
	if not (parsed is Dictionary):
		return false
	var meta: Dictionary = parsed
	var bounds: Array = meta.get("bounds_m", [])
	if bounds.size() < 4:
		return false
	_min_x = float(bounds[0])
	_min_z = float(bounds[1])
	_chunk_size = float(meta.get("chunk_size_m", 256.0))
	var grid: Dictionary = meta.get("chunk_grid", {})
	_cols = int(grid.get("cols", 0))
	_rows = int(grid.get("rows", 0))
	_world_dir = bundle_dir.path_join("world")
	_ready_ok = _cols > 0 and _rows > 0
	return _ready_ok


func world_meta_ok() -> bool:
	return _ready_ok


func chunk_grid_size() -> Vector2i:
	return Vector2i(_cols, _rows)


# --------------------------------------------------------------------- key/addr
static func _key(cx: int, cz: int) -> String:
	return "%d_%d" % [cx, cz]


func _chunk_origin(cx: int, cz: int) -> Vector2:
	return Vector2(_min_x + float(cx) * _chunk_size, _min_z + float(cz) * _chunk_size)


func _chunk_center(cx: int, cz: int) -> Vector2:
	var o := _chunk_origin(cx, cz)
	return o + Vector2(_chunk_size * 0.5, _chunk_size * 0.5)


func _chunk_of(x: float, z: float) -> Vector2i:
	var cx := int(floor((x - _min_x) / _chunk_size))
	var cz := int(floor((z - _min_z) / _chunk_size))
	cx = clampi(cx, 0, max(_cols - 1, 0))
	cz = clampi(cz, 0, max(_rows - 1, 0))
	return Vector2i(cx, cz)


# ------------------------------------------------------------------ chunk cache
func _get_chunk(cx: int, cz: int) -> Dictionary:
	var key := _key(cx, cz)
	_cache_clock += 1
	if _chunk_cache.has(key):
		_chunk_cache_touch[key] = _cache_clock
		return _chunk_cache[key]
	var path := _world_dir.path_join("chunks/c_%d_%d.json.gz" % [cx, cz])
	if not FileAccess.file_exists(path):
		return {}
	var bytes := FileAccess.get_file_as_bytes(path)
	if bytes.is_empty():
		return {}
	var raw := bytes.decompress_dynamic(-1, FileAccess.COMPRESSION_GZIP)
	if raw.is_empty():
		return {}
	var parsed: Variant = JSON.parse_string(raw.get_string_from_utf8())
	if not (parsed is Dictionary):
		return {}
	var chunk: Dictionary = parsed
	_chunk_cache[key] = chunk
	_chunk_cache_touch[key] = _cache_clock
	_evict_if_needed()
	return chunk


func _evict_if_needed() -> void:
	while _chunk_cache.size() > CACHE_CAP:
		var oldest_key := ""
		var oldest_t := _cache_clock + 1
		for k in _chunk_cache_touch.keys():
			var t: int = _chunk_cache_touch[k]
			if t < oldest_t:
				oldest_t = t
				oldest_key = k
		if oldest_key == "":
			break
		_chunk_cache.erase(oldest_key)
		_chunk_cache_touch.erase(oldest_key)


# ------------------------------------------------------------------ RLE decode
static func _decode_rle(runs: Array, expect_len: int) -> PackedByteArray:
	var out := PackedByteArray()
	out.resize(expect_len)
	var idx := 0
	var i := 0
	while i + 1 < runs.size() and idx < expect_len:
		var t := int(runs[i])
		var n := int(runs[i + 1])
		var end := mini(idx + n, expect_len)
		for k in range(idx, end):
			out[k] = t
		idx = end
		i += 2
	return out


# -------------------------------------------------------------------- focus API
func update_focus(pos: Vector3) -> void:
	if not _ready_ok:
		return
	var focus := Vector2(pos.x, pos.z)
	_unload_pass(focus)
	_build_pass(focus)


func force_materialize(pos: Vector3) -> void:
	## Synchronously build T1+T2+T3 of the focus chunk and T1 of its 8
	## neighbours, bypassing the per-call budget — used at spawn so the
	## starting chunk is fully materialized before the first frame ends.
	if not _ready_ok:
		return
	var c := _chunk_of(pos.x, pos.z)
	for tier in [1, 2, 3]:
		_ensure_tier(c.x, c.y, tier)
	for dz in range(-1, 2):
		for dx in range(-1, 2):
			if dx == 0 and dz == 0:
				continue
			var ncx := c.x + dx
			var ncz := c.y + dz
			if ncx < 0 or ncx >= _cols or ncz < 0 or ncz >= _rows:
				continue
			_ensure_tier(ncx, ncz, 1)


func _tier_radius(tier: int) -> float:
	match tier:
		1: return T1_RADIUS
		2: return T2_RADIUS
		3: return T3_RADIUS
	return 0.0


func _build_pass(focus: Vector2) -> void:
	# Scan the bounding box of chunks that could fall within T1_RADIUS of the
	# focus, collect missing tiers, sort by (distance, tier), build up to budget.
	var reach := T1_RADIUS + _chunk_size
	var lo := _chunk_of(focus.x - reach, focus.y - reach)
	var hi := _chunk_of(focus.x + reach, focus.y + reach)
	var queue: Array = []      # [dist, cx, cz, tier]
	for cz in range(lo.y, hi.y + 1):
		for cx in range(lo.x, hi.x + 1):
			var center := _chunk_center(cx, cz)
			var dist := focus.distance_to(center)
			var desired := 0
			if dist <= T3_RADIUS:
				desired = 3
			elif dist <= T2_RADIUS:
				desired = 2
			elif dist <= T1_RADIUS:
				desired = 1
			if desired == 0:
				continue
			var key := _key(cx, cz)
			var have: Dictionary = _resident.get(key, {})
			var have_nodes: Dictionary = have.get("nodes", {})
			for tier in range(1, desired + 1):
				if not have_nodes.has(tier):
					queue.append([dist, cx, cz, tier])
	if queue.is_empty():
		return
	queue.sort_custom(func(a, b):
		if a[0] != b[0]:
			return a[0] < b[0]
		return a[3] < b[3])
	var built := 0
	for item in queue:
		if built >= BUILD_BUDGET:
			break
		_ensure_tier(int(item[1]), int(item[2]), int(item[3]))
		built += 1


func _unload_pass(focus: Vector2) -> void:
	var to_unload: Array = []   # [dist, key, tier]
	for key in _resident.keys():
		var rec: Dictionary = _resident[key]
		var cx: int = rec["cx"]
		var cz: int = rec["cz"]
		var center := _chunk_center(cx, cz)
		var dist := focus.distance_to(center)
		var nodes: Dictionary = rec["nodes"]
		for tier in nodes.keys():
			if dist > _tier_radius(int(tier)) + HYSTERESIS:
				to_unload.append([dist, key, tier])
	if to_unload.is_empty():
		return
	to_unload.sort_custom(func(a, b): return a[0] > b[0])
	var freed := 0
	for item in to_unload:
		if freed >= UNLOAD_BUDGET:
			break
		var key: String = item[1]
		var tier: int = item[2]
		_unload_tier(key, tier)
		freed += 1


func _unload_tier(key: String, tier: int) -> void:
	if not _resident.has(key):
		return
	var rec: Dictionary = _resident[key]
	var nodes: Dictionary = rec["nodes"]
	if nodes.has(tier):
		var n: Node3D = nodes[tier]
		if is_instance_valid(n):
			n.queue_free()
		nodes.erase(tier)
	var stats: Dictionary = rec["stats"]
	stats.erase(tier)
	if nodes.is_empty():
		_resident.erase(key)


# ------------------------------------------------------------------ tier build
func _ensure_tier(cx: int, cz: int, tier: int) -> void:
	if cx < 0 or cx >= _cols or cz < 0 or cz >= _rows:
		return
	var key := _key(cx, cz)
	var rec: Dictionary = _resident.get(key, {"cx": cx, "cz": cz, "nodes": {}, "stats": {}})
	var nodes: Dictionary = rec["nodes"]
	if nodes.has(tier):
		_resident[key] = rec
		return
	var chunk := _get_chunk(cx, cz)
	if chunk.is_empty():
		return
	var root := Node3D.new()
	root.name = "c_%d_%d_t%d" % [cx, cz, tier]
	add_child(root)
	var t0 := Time.get_ticks_usec()
	var stats: Dictionary
	match tier:
		1:
			stats = _build_t1(chunk, root)
		2:
			stats = _build_t2(chunk, root)
		3:
			stats = _build_t3(chunk, root)
		_:
			stats = {}
	var elapsed_ms := (Time.get_ticks_usec() - t0) / 1000.0
	if last_build_ms.has(tier):
		last_build_ms[tier].append(elapsed_ms)
	nodes[tier] = root
	rec["stats"][tier] = stats
	rec["nodes"] = nodes
	_resident[key] = rec


# ------------------------------------------------------------------------- T1
func _build_t1(chunk: Dictionary, root: Node3D) -> Dictionary:
	var origin_arr: Array = chunk.get("origin", [0.0, 0.0])
	var origin := Vector2(float(origin_arr[0]), float(origin_arr[1]))
	var runs: Array = chunk.get("surface", [])
	var cells := _decode_rle(runs, CELLS * CELLS)

	var quads := 0
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	for row in range(CELLS):
		var col := 0
		while col < CELLS:
			var t := cells[row * CELLS + col]
			var col2 := col + 1
			while col2 < CELLS and cells[row * CELLS + col2] == t:
				col2 += 1
			var color: Color = SURFACE_COLORS[S_OTHER_IMPERVIOUS] if t == S_BUILDING \
				else (SURFACE_COLORS[t] if t < SURFACE_COLORS.size() else Color(1, 0, 1))
			var y := -0.15 if t == S_WATER else 0.02
			var x0 := origin.x + float(col) * CELL_M
			var x1 := origin.x + float(col2) * CELL_M
			var z0 := origin.y + float(row) * CELL_M
			var z1 := origin.y + float(row + 1) * CELL_M
			st.set_color(color)
			_tri(st, Vector3(x0, y, z0), Vector3(x1, y, z0), Vector3(x1, y, z1), Vector3.UP)
			_tri(st, Vector3(x0, y, z0), Vector3(x1, y, z1), Vector3(x0, y, z1), Vector3.UP)
			quads += 1
			col = col2
	var ground_mesh := st.commit()
	var mi := MeshInstance3D.new()
	mi.mesh = ground_mesh
	mi.material_override = _ground_material()
	root.add_child(mi)

	var buildings: Array = chunk.get("buildings", [])
	var bverts := 0
	if not buildings.is_empty():
		var bst := SurfaceTool.new()
		bst.begin(Mesh.PRIMITIVE_TRIANGLES)
		for b in buildings:
			bverts += _mass_building(bst, b)
		var bmesh := bst.commit()
		var bmi := MeshInstance3D.new()
		bmi.mesh = bmesh
		bmi.material_override = _shared_opaque_material()
		root.add_child(bmi)

	return {"quads": quads, "verts": quads * 6 + bverts, "buildings": buildings.size(),
		"mm_instances": 0, "collisions": 0}


func _mass_building(st: SurfaceTool, b: Dictionary) -> int:
	var poly: Array = b.get("poly", [])
	if poly.size() < 3:
		return 0
	var h := float(b.get("h", 3.0))
	var bid := int(b.get("bid", 0))
	var arch := String(b.get("arch", "GENERIC_UNKNOWN"))
	var base_col: Color = BUILDING_ARCH_COLORS.get(arch, BUILDING_ARCH_COLORS["GENERIC_UNKNOWN"])
	var tint := (float(_stable_hash(bid, 7) % 1000) / 1000.0 - 0.5) * 0.12
	var col := Color(
		clampf(base_col.r + tint, 0.0, 1.0),
		clampf(base_col.g + tint, 0.0, 1.0),
		clampf(base_col.b + tint, 0.0, 1.0))

	var ring := PackedVector2Array()
	for p in poly:
		ring.append(Vector2(float(p[0]), float(p[1])))
	var n := ring.size()
	var verts := 0
	# Flat roof.
	st.set_color(col.darkened(0.15))
	var tris := Geometry2D.triangulate_polygon(ring)
	for i in range(0, tris.size(), 3):
		for k in [tris[i], tris[i + 1], tris[i + 2]]:
			st.set_normal(Vector3.UP)
			st.add_vertex(Vector3(ring[k].x, h, ring[k].y))
		verts += 3
	# Walls.
	st.set_color(col)
	for i in range(n):
		var a := ring[i]
		var c := ring[(i + 1) % n]
		var nrm := Vector3((c.y - a.y), 0.0, -(c.x - a.x)).normalized()
		var a0 := Vector3(a.x, 0.0, a.y)
		var a1 := Vector3(a.x, h, a.y)
		var c0 := Vector3(c.x, 0.0, c.y)
		var c1 := Vector3(c.x, h, c.y)
		for v in [a0, c0, c1, a0, c1, a1]:
			st.set_normal(nrm)
			st.add_vertex(v)
		verts += 6
	return verts


static func _stable_hash(a: int, b: int) -> int:
	var x: int = (a * 0x9E3779B1) ^ (b * 0x85EBCA6B)
	x = x & 0x7FFFFFFF
	x ^= (x >> 13)
	x = (x * 0x2545F491) & 0x7FFFFFFF
	return x


# ------------------------------------------------------------------------- T2
func _build_t2(chunk: Dictionary, root: Node3D) -> Dictionary:
	var buildings: Array = chunk.get("buildings", [])
	var dst := SurfaceTool.new()
	dst.begin(Mesh.PRIMITIVE_TRIANGLES)
	var dverts := 0
	var body: StaticBody3D = null
	var collisions := 0
	var hvac_xforms: Array = []
	for b in buildings:
		dverts += _detail_building(dst, b, hvac_xforms)
		var poly: Array = b.get("poly", [])
		if poly.size() < 3:
			continue
		var min_x := INF; var min_z := INF; var max_x := -INF; var max_z := -INF
		for p in poly:
			min_x = minf(min_x, float(p[0])); max_x = maxf(max_x, float(p[0]))
			min_z = minf(min_z, float(p[1])); max_z = maxf(max_z, float(p[1]))
		var bw := max_x - min_x
		var bd := max_z - min_z
		if bw < 0.1 or bd < 0.1:
			continue
		if body == null:
			body = StaticBody3D.new()
			body.name = "BuildingCollision"
			root.add_child(body)
		var h := float(b.get("h", 3.0))
		var cs := CollisionShape3D.new()
		var shape := BoxShape3D.new()
		shape.size = Vector3(bw, h, bd)
		cs.shape = shape
		cs.position = Vector3((min_x + max_x) * 0.5, h * 0.5, (min_z + max_z) * 0.5)
		body.add_child(cs)
		collisions += 1
	if dverts > 0:
		var dmesh := dst.commit()
		var dmi := MeshInstance3D.new()
		dmi.mesh = dmesh
		dmi.material_override = _shared_opaque_material()
		root.add_child(dmi)

	var mm_count := 0
	if not hvac_xforms.is_empty():
		var mmi := PropMeshes.make_multimesh("rooftop_hvac", hvac_xforms)
		root.add_child(mmi)
		mm_count += hvac_xforms.size()

	var rverts := _build_road_markings(chunk, root)
	var everts := _build_elevated_roads(chunk, root)

	return {"quads": 0, "verts": dverts + rverts + everts, "buildings": buildings.size(),
		"mm_instances": mm_count, "collisions": collisions}


func _detail_building(st: SurfaceTool, b: Dictionary, hvac_xforms: Array) -> int:
	var poly: Array = b.get("poly", [])
	if poly.size() < 3:
		return 0
	var h := float(b.get("h", 3.0))
	var floors := maxi(1, int(b.get("floors", 1)))
	var floor_h := h / float(floors)
	var arch := String(b.get("arch", "GENERIC_UNKNOWN"))
	var roof := String(b.get("roof", "flat"))
	var feat: Array = b.get("feat", [])
	var bid := int(b.get("bid", 0))
	var ent: Dictionary = b.get("entrance", {})
	var ent_edge := int(ent.get("edge", -1))
	var ent_t := float(ent.get("t", 0.5))
	var ent_w := float(ent.get("w", 1.6))

	var is_storefront := ("storefront" in feat) and (arch == "SMALL_COMMERCIAL" or arch == "BIG_BOX_COMMERCIAL")

	var ring := PackedVector2Array()
	for p in poly:
		ring.append(Vector2(float(p[0]), float(p[1])))
	var n := ring.size()
	var verts := 0

	for i in range(n):
		var a := ring[i]
		var c := ring[(i + 1) % n]
		var seg := c - a
		var length := seg.length()
		if length <= 3.0:
			continue
		var dir := seg / length
		var nrm2 := Vector2(seg.y, -seg.x).normalized()
		var nrm3 := Vector3(nrm2.x, 0.0, nrm2.y)
		var is_entrance_edge := (i == ent_edge)

		for f in range(floors):
			var y0 := float(f) * floor_h
			if f == 0 and is_storefront:
				if is_entrance_edge:
					var band_h := floor_h * 1.3
					var p0 := a + nrm2 * 0.05
					var p1 := c + nrm2 * 0.05
					verts += _quad_v(st, Vector3(p0.x, y0 + 0.1, p0.y), Vector3(p1.x, y0 + 0.1, p1.y),
						Vector3(p1.x, y0 + band_h, p1.y), Vector3(p0.x, y0 + band_h, p0.y),
						nrm3, STOREFRONT_GLASS_COL)
					var door_center := a.lerp(c, ent_t)
					var half_w := ent_w * 0.5
					var d0 := door_center - dir * half_w + nrm2 * 0.06
					var d1 := door_center + dir * half_w + nrm2 * 0.06
					verts += _quad_v(st, Vector3(d0.x, 0.0, d0.y), Vector3(d1.x, 0.0, d1.y),
						Vector3(d1.x, 2.2, d1.y), Vector3(d0.x, 2.2, d0.y), nrm3, DOOR_COL)
				continue
			var win_h := floor_h * 0.55
			var win_y := y0 + floor_h * 0.3
			var n_windows := int(floor(length / 2.5))
			for wi in range(n_windows):
				var t := (float(wi) + 0.5) / float(n_windows)
				var center := a.lerp(c, t)
				var win_w := minf(1.2, length / float(n_windows) * 0.6)
				var half_w := win_w * 0.5
				var w0 := center - dir * half_w + nrm2 * 0.05
				var w1 := center + dir * half_w + nrm2 * 0.05
				verts += _quad_v(st, Vector3(w0.x, win_y, w0.y), Vector3(w1.x, win_y, w1.y),
					Vector3(w1.x, win_y + win_h, w1.y), Vector3(w0.x, win_y + win_h, w0.y),
					nrm3, GLASS_COL)

		if is_entrance_edge and not is_storefront:
			var dc := a.lerp(c, ent_t)
			var hw := ent_w * 0.5
			var e0 := dc - dir * hw + nrm2 * 0.06
			var e1 := dc + dir * hw + nrm2 * 0.06
			verts += _quad_v(st, Vector3(e0.x, 0.0, e0.y), Vector3(e1.x, 0.0, e1.y),
				Vector3(e1.x, 2.2, e1.y), Vector3(e0.x, 2.2, e0.y), nrm3, DOOR_COL)

	if roof == "pitched":
		verts += _pitched_roof(st, ring, h)
	elif "parapet" in feat:
		verts += _parapet(st, ring, h)

	if "rooftop_hvac" in feat:
		var min_x := INF; var min_z := INF; var max_x := -INF; var max_z := -INF
		for p2 in ring:
			min_x = minf(min_x, p2.x); max_x = maxf(max_x, p2.x)
			min_z = minf(min_z, p2.y); max_z = maxf(max_z, p2.y)
		var units := 1 + (_stable_hash(bid, 11) % 3)
		for u in range(units):
			var ux := lerpf(min_x + 1.5, max_x - 1.5, float(_stable_hash(bid, 13 + u) % 1000) / 1000.0)
			var uz := lerpf(min_z + 1.5, max_z - 1.5, float(_stable_hash(bid, 17 + u) % 1000) / 1000.0)
			hvac_xforms.append(Transform3D(Basis(), Vector3(ux, h, uz)))

	return verts


func _quad_v(st: SurfaceTool, p0: Vector3, p1: Vector3, p2: Vector3, p3: Vector3,
		nrm: Vector3, col: Color) -> int:
	st.set_color(col)
	for v in [p0, p1, p2, p0, p2, p3]:
		st.set_normal(nrm)
		st.add_vertex(v)
	return 6


func _pitched_roof(st: SurfaceTool, ring: PackedVector2Array, h: float) -> int:
	# Approximate gable over the footprint's axis-aligned bbox, shrunk to ~85%.
	var min_x := INF; var min_z := INF; var max_x := -INF; var max_z := -INF
	for p in ring:
		min_x = minf(min_x, p.x); max_x = maxf(max_x, p.x)
		min_z = minf(min_z, p.y); max_z = maxf(max_z, p.y)
	var cx := (min_x + max_x) * 0.5
	var cz := (min_z + max_z) * 0.5
	var hw := (max_x - min_x) * 0.5 * 0.85
	var hd := (max_z - min_z) * 0.5 * 0.85
	var ridge_h := h + maxf(hw, hd) * 0.35
	var along_x := hw >= hd     # ridge runs along the longer axis
	var verts := 0
	st.set_color(ROOF_COL)
	if along_x:
		var r0 := Vector3(cx - hw, ridge_h, cz)
		var r1 := Vector3(cx + hw, ridge_h, cz)
		var eaves := [
			Vector3(cx - hw, h, cz - hd), Vector3(cx + hw, h, cz - hd),
			Vector3(cx + hw, h, cz + hd), Vector3(cx - hw, h, cz + hd)]
		verts += _quad_v(st, eaves[0], eaves[1], r1, r0, Vector3.UP, ROOF_COL)
		verts += _quad_v(st, eaves[3], eaves[2], r1, r0, Vector3.UP, ROOF_COL)
		verts += _tri_v(st, eaves[0], eaves[3], r0, ROOF_COL)
		verts += _tri_v(st, eaves[1], eaves[2], r1, ROOF_COL)
	else:
		var r0b := Vector3(cx, ridge_h, cz - hd)
		var r1b := Vector3(cx, ridge_h, cz + hd)
		var eaves2 := [
			Vector3(cx - hw, h, cz - hd), Vector3(cx + hw, h, cz - hd),
			Vector3(cx + hw, h, cz + hd), Vector3(cx - hw, h, cz + hd)]
		verts += _quad_v(st, eaves2[0], eaves2[3], r1b, r0b, Vector3.UP, ROOF_COL)
		verts += _quad_v(st, eaves2[1], eaves2[2], r1b, r0b, Vector3.UP, ROOF_COL)
		verts += _tri_v(st, eaves2[0], eaves2[1], r0b, ROOF_COL)
		verts += _tri_v(st, eaves2[3], eaves2[2], r1b, ROOF_COL)
	return verts


func _tri_v(st: SurfaceTool, p0: Vector3, p1: Vector3, p2: Vector3, col: Color) -> int:
	st.set_color(col)
	var nrm := (p1 - p0).cross(p2 - p0).normalized()
	for v in [p0, p1, p2]:
		st.set_normal(nrm)
		st.add_vertex(v)
	return 3


func _parapet(st: SurfaceTool, ring: PackedVector2Array, h: float) -> int:
	var n := ring.size()
	var verts := 0
	st.set_color(PARAPET_COL)
	for i in range(n):
		var a := ring[i]
		var c := ring[(i + 1) % n]
		var nrm := Vector3((c.y - a.y), 0.0, -(c.x - a.x)).normalized()
		var a1 := Vector3(a.x, h, a.y)
		var c1 := Vector3(c.x, h, c.y)
		var a2 := Vector3(a.x, h + PARAPET_H, a.y)
		var c2 := Vector3(c.x, h + PARAPET_H, c.y)
		verts += _quad_v(st, a1, c1, c2, a2, nrm, PARAPET_COL)
	return verts


func _build_road_markings(chunk: Dictionary, root: Node3D) -> int:
	var roads: Array = chunk.get("roads", [])
	var any := false
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var verts := 0
	for r in roads:
		var markings := String(r.get("markings", "none"))
		if markings != "dashed_center":
			continue
		var pts_raw: Array = r.get("pts", [])
		if pts_raw.size() < 2:
			continue
		any = true
		var carriage_w := float(r.get("carriage_w", 6.0))
		var lanes := int(r.get("lanes", 2))
		verts += _dashed_line(st, pts_raw, 0.0, 0.15, 2.0, 3.0)
		if lanes >= 4:
			var half := carriage_w * 0.5 - 0.3
			verts += _dashed_line(st, pts_raw, half, 0.15, 999999.0, 0.0)
			verts += _dashed_line(st, pts_raw, -half, 0.15, 999999.0, 0.0)
	if not any:
		return 0
	var mesh := st.commit()
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.material_override = _shared_opaque_material()
	root.add_child(mi)
	return verts


func _dashed_line(st: SurfaceTool, pts_raw: Array, offset: float, width: float,
		dash_len: float, gap_len: float) -> int:
	var pts: Array = []
	for p in pts_raw:
		pts.append(Vector2(float(p[0]), float(p[1])))
	var verts := 0
	var period := dash_len + gap_len
	var dist0 := 0.0
	st.set_color(LANE_COL)
	for k in range(pts.size() - 1):
		var a: Vector2 = pts[k]
		var b: Vector2 = pts[k + 1]
		var d := b - a
		var seglen := d.length()
		if seglen < 0.001:
			continue
		var dir := d / seglen
		var n := d.orthogonal().normalized()
		var half_w := width * 0.5
		var idx := floori(dist0 / period)
		while true:
			var dash_start := float(idx) * period
			idx += 1
			if dash_start > dist0 + seglen:
				break
			var s := maxf(dash_start, dist0)
			var e := minf(dash_start + dash_len, dist0 + seglen)
			if e <= s:
				continue
			var pa := a + dir * (s - dist0) + n * offset
			var pb := a + dir * (e - dist0) + n * offset
			var p0 := pa - n * half_w
			var p1 := pb - n * half_w
			var p2 := pb + n * half_w
			var p3 := pa + n * half_w
			for v in [Vector3(p0.x, 0.06, p0.y), Vector3(p1.x, 0.06, p1.y), Vector3(p2.x, 0.06, p2.y),
					Vector3(p0.x, 0.06, p0.y), Vector3(p2.x, 0.06, p2.y), Vector3(p3.x, 0.06, p3.y)]:
				st.set_normal(Vector3.UP)
				st.add_vertex(v)
			verts += 6
		dist0 += seglen
	return verts


func _build_elevated_roads(chunk: Dictionary, root: Node3D) -> int:
	var roads: Array = chunk.get("roads", [])
	var any := false
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var verts := 0
	for r in roads:
		if not bool(r.get("elevated", false)):
			continue
		var pts_raw: Array = r.get("pts", [])
		if pts_raw.size() < 2:
			continue
		any = true
		var deck_w := maxf(6.0, float(r.get("carriage_w", 16.0)))
		var hw := deck_w * 0.5
		for k in range(pts_raw.size() - 1):
			var a := Vector2(float(pts_raw[k][0]), float(pts_raw[k][1]))
			var b := Vector2(float(pts_raw[k + 1][0]), float(pts_raw[k + 1][1]))
			var d := b - a
			var seglen := d.length()
			if seglen < 0.001:
				continue
			var n := d.orthogonal().normalized()
			verts += _slab(st, a, b, n, -hw, hw, DECK_Y - DECK_T, DECK_Y, DECK_COL)
			verts += _slab(st, a, b, n, hw - 0.4, hw, DECK_Y, DECK_Y + 1.0, BARRIER_COL)
			verts += _slab(st, a, b, n, -hw, -hw + 0.4, DECK_Y, DECK_Y + 1.0, BARRIER_COL)
			var steps: int = maxi(1, floori(seglen / 45.0))
			for s in range(steps):
				var t := (float(s) + 0.5) / float(steps)
				var c := a.lerp(b, t)
				verts += _pillar(st, c, 3.0, DECK_Y - DECK_T)
	if not any:
		return 0
	var mesh := st.commit()
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.material_override = _shared_opaque_material()
	root.add_child(mi)
	return verts


func _slab(st: SurfaceTool, a: Vector2, b: Vector2, n: Vector2,
		off0: float, off1: float, y0: float, y1: float, color: Color) -> int:
	st.set_color(color)
	var a0 := a + n * off0
	var a1 := a + n * off1
	var b0 := b + n * off0
	var b1 := b + n * off1
	var verts := 0
	verts += _tri_v(st, Vector3(a0.x, y1, a0.y), Vector3(a1.x, y1, a1.y), Vector3(b1.x, y1, b1.y), color)
	verts += _tri_v(st, Vector3(a0.x, y1, a0.y), Vector3(b1.x, y1, b1.y), Vector3(b0.x, y1, b0.y), color)
	var s1 := Vector3(n.x, 0, n.y)
	verts += _quad_v(st, Vector3(a1.x, y0, a1.y), Vector3(b1.x, y0, b1.y), Vector3(b1.x, y1, b1.y),
		Vector3(a1.x, y1, a1.y), s1, color)
	verts += _quad_v(st, Vector3(b0.x, y0, b0.y), Vector3(a0.x, y0, a0.y), Vector3(a0.x, y1, a0.y),
		Vector3(b0.x, y1, b0.y), -s1, color)
	return verts


func _pillar(st: SurfaceTool, c: Vector2, side: float, top: float) -> int:
	var verts := 0
	var h := side * 0.5
	var corners: Array = [Vector2(-h, -h), Vector2(h, -h), Vector2(h, h), Vector2(-h, h)]
	for i in range(4):
		var p: Vector2 = c + corners[i]
		var q: Vector2 = c + corners[(i + 1) % 4]
		var nrm := Vector3(q.x - p.x, 0, q.y - p.y).cross(Vector3.UP).normalized()
		verts += _quad_v(st, Vector3(p.x, 0, p.y), Vector3(q.x, 0, q.y),
			Vector3(q.x, top, q.y), Vector3(p.x, top, p.y), nrm, PILLAR_COL)
	return verts


func _tri(st: SurfaceTool, p0: Vector3, p1: Vector3, p2: Vector3, nrm: Vector3) -> void:
	for v in [p0, p1, p2]:
		st.set_normal(nrm)
		st.add_vertex(v)


# ------------------------------------------------------------------------- T3
func _build_t3(chunk: Dictionary, root: Node3D) -> Dictionary:
	# Group placements by "kind" (props/vehicles/trees), with vehicle kinds
	# further split by variant since PropMeshes bakes vehicle colour per mesh.
	var groups: Dictionary = {}   # "kind" or "kind:variant" -> {kind, variant, xforms:Array[Transform3D]}
	var lists := [chunk.get("props", []), chunk.get("vehicles", []), chunk.get("trees", [])]
	var vehicle_kinds := {"sedan": true, "suv": true, "pickup": true, "van": true, "box_truck": true}
	var total := 0
	for lst in lists:
		for row in lst:
			if row.size() != 5:
				continue
			var kind := String(row[0])
			var x := float(row[1])
			var z := float(row[2])
			var rot := float(row[3])
			var variant := int(row[4])
			var gkey := kind
			if vehicle_kinds.has(kind):
				gkey = "%s:%d" % [kind, variant]
			if not groups.has(gkey):
				groups[gkey] = {"kind": kind, "variant": variant, "xforms": []}
			var basis := Basis(Vector3.UP, deg_to_rad(rot))
			(groups[gkey]["xforms"] as Array).append(Transform3D(basis, Vector3(x, 0.0, z)))
			total += 1

	var mm_count := 0
	for gkey in groups.keys():
		var g: Dictionary = groups[gkey]
		var xforms: Array = g["xforms"]
		if xforms.is_empty():
			continue
		var mmi := PropMeshes.make_multimesh(String(g["kind"]), xforms, int(g["variant"]))
		root.add_child(mmi)
		mm_count += xforms.size()

	return {"quads": 0, "verts": 0, "buildings": 0, "mm_instances": mm_count, "collisions": 0}


# --------------------------------------------------------------- introspection
func resident_chunk_count() -> int:
	return _resident.size()


func build_ms_stats(tier: int) -> Dictionary:
	## min/avg/max/n over every _ensure_tier call recorded so far for `tier`
	## (see last_build_ms above) — the perf-certification harness's source of
	## per-chunk build-time numbers.
	var samples: Array = last_build_ms.get(tier, [])
	if samples.is_empty():
		return {"min": 0.0, "avg": 0.0, "max": 0.0, "n": 0}
	var mn: float = samples[0]
	var mx: float = samples[0]
	var sum := 0.0
	for v in samples:
		mn = minf(mn, v)
		mx = maxf(mx, v)
		sum += v
	return {"min": mn, "avg": sum / samples.size(), "max": mx, "n": samples.size()}


func total_mm_instances() -> int:
	## Sum of mm_instances across every resident tier stat — the live
	## MultiMesh instance count (props/vehicles/trees) at the current focus.
	var total := 0
	for rec in _resident.values():
		var stats: Dictionary = rec["stats"]
		for tier in stats.keys():
			total += int(stats[tier].get("mm_instances", 0))
	return total


func resident_node_count() -> int:
	var count := 0
	var stack: Array = [self]
	while not stack.is_empty():
		var n: Node = stack.pop_back()
		for c in n.get_children():
			count += 1
			stack.append(c)
	return count


func chunk_debug_hash(cx: int, cz: int) -> int:
	var key := _key(cx, cz)
	if not _resident.has(key):
		return 0
	var stats: Dictionary = _resident[key]["stats"]
	var h: int = 1469598103934665603
	for tier in [1, 2, 3]:
		if not stats.has(tier):
			continue
		var d: Dictionary = stats[tier]
		for field in ["quads", "verts", "buildings", "mm_instances", "collisions"]:
			var v := int(d.get(field, 0))
			h = (h ^ v) * 1099511628211
			h = h & 0x7FFFFFFFFFFFFFFF
	return h


func is_chunk_resident(cx: int, cz: int) -> bool:
	return _resident.has(_key(cx, cz))


func chunk_tier(cx: int, cz: int) -> int:
	## Highest resident tier for the chunk, or 0 if not resident.
	var key := _key(cx, cz)
	if not _resident.has(key):
		return 0
	var nodes: Dictionary = _resident[key]["nodes"]
	var best := 0
	for t in nodes.keys():
		best = maxi(best, int(t))
	return best
