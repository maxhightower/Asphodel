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
# Facade trim (protruding relief so faces catch light + cast shadow at iso scale).
const SILL_COL := Color(0.80, 0.79, 0.76)      # light sills / string courses
const FRAME_COL := Color(0.32, 0.31, 0.30)     # window headers / reveals
const SHUTTER_COLS := [
	Color(0.30, 0.36, 0.42), Color(0.34, 0.30, 0.26), Color(0.28, 0.40, 0.34),
	Color(0.42, 0.34, 0.30), Color(0.30, 0.30, 0.34),
]
const ROOF_COL := Color(0.32, 0.33, 0.36)
# Residential massing (porch, garage, chimney, patio) so houses read as volumes
# instead of flat extruded footprints.
const PORCH_ROOF_COL := Color(0.34, 0.30, 0.27)
const PORCH_POST_COL := Color(0.82, 0.80, 0.75)
const PLATFORM_COL := Color(0.68, 0.66, 0.62)
const GARAGE_COL := Color(0.60, 0.58, 0.55)
const CHIMNEY_COL := Color(0.40, 0.30, 0.26)
const PATIO_COL := Color(0.58, 0.56, 0.53)
const PARAPET_COL := Color(0.26, 0.27, 0.30)
const PARAPET_H := 0.8
const MECH_COL := Color(0.55, 0.56, 0.58)       # rooftop mechanical units
const PENTHOUSE_COL := Color(0.44, 0.45, 0.48)  # stair/lift penthouse
const LANE_COL := Color(0.90, 0.90, 0.85)
const DECK_COL := Color(0.32, 0.32, 0.35)
const PILLAR_COL := Color(0.42, 0.42, 0.45)
const BARRIER_COL := Color(0.72, 0.70, 0.62)
const DECK_Y := 7.0
const DECK_T := 0.7
# Continuous road/sidewalk ribbons drawn from the real polylines (with mitered
# joins) so curving streets read as smooth ribbons instead of the axis-aligned
# raster cells underneath. A raised curb gives a clear yard/street boundary.
const CURB_COL := Color(0.60, 0.60, 0.58)
const ROAD_RIBBON_Y := 0.035      # above the 0.02 raster ground, below markings (0.06)
const SIDEWALK_Y := 0.14          # raised sidewalk deck
const PATH_Y := 0.05

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
var _veg_region: String = "temperate"   # geographic biome for vegetation selection

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
	# Geographic vegetation region from the bundle bbox (lat/lon) — never the city
	# name. Drives which species scatter favours (Section 6 / Section 24).
	_veg_region = _derive_veg_region(bundle_dir)
	_ready_ok = _cols > 0 and _rows > 0
	return _ready_ok


## Coarse deterministic biome from the bundle's geographic bbox centroid. Pure
## geography (latitude + a continental-dryness proxy from longitude), so the same
## place always reads the same and no rule ever branches on a city name.
func _derive_veg_region(bundle_dir: String) -> String:
	var mpath := bundle_dir.path_join("meta.json")
	if not FileAccess.file_exists(mpath):
		return "temperate"
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(mpath))
	if not (parsed is Dictionary):
		return "temperate"
	var bbox: Array = (parsed as Dictionary).get("bbox", [])  # [S, W, N, E]
	if bbox.size() < 4:
		return "temperate"
	var lat := (float(bbox[0]) + float(bbox[2])) * 0.5
	var lon := (float(bbox[1]) + float(bbox[3])) * 0.5
	var alat := absf(lat)
	# dry interior/west (very rough continental proxy) vs humid; gulf/subtropical
	# vs temperate vs boreal by latitude band.
	if alat < 31.0:
		return "arid" if lon < -100.0 else "gulf"
	if alat < 37.0:
		return "arid" if lon < -103.0 else "subtropical"
	if alat < 49.0:
		return "temperate"
	return "boreal"


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
	# Roads and sidewalks are drawn as smooth continuous ribbons (see
	# _build_road_surfaces); erase their blocky raster cells by bleeding the
	# surrounding cover into them, so the ground under/around a ribbon matches its
	# neighbourhood and the green meets the ribbon on a smooth curve, not a grid.
	cells = _erase_paved_cells(cells)

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
			# Buildings paint as impervious hardscape; the surface-class id rides in
			# COLOR.a so the ground shader can treat asphalt/concrete/grass distinctly.
			var fam := S_OTHER_IMPERVIOUS if t == S_BUILDING else t
			var color: Color = SURFACE_COLORS[S_OTHER_IMPERVIOUS] if t == S_BUILDING \
				else (SURFACE_COLORS[t] if t < SURFACE_COLORS.size() else Color(1, 0, 1))
			var y := -0.15 if t == S_WATER else 0.02
			var x0 := origin.x + float(col) * CELL_M
			var x1 := origin.x + float(col2) * CELL_M
			var z0 := origin.y + float(row) * CELL_M
			var z1 := origin.y + float(row + 1) * CELL_M
			st.set_color(WorldMaterials.encode(color, fam))
			_tri(st, Vector3(x0, y, z0), Vector3(x1, y, z0), Vector3(x1, y, z1), Vector3.UP)
			_tri(st, Vector3(x0, y, z0), Vector3(x1, y, z1), Vector3(x0, y, z1), Vector3.UP)
			quads += 1
			col = col2
	var ground_mesh := st.commit()
	var mi := MeshInstance3D.new()
	mi.mesh = ground_mesh
	mi.material_override = WorldMaterials.ground_material()
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
		bmi.material_override = WorldMaterials.building_material()
		root.add_child(bmi)

	return {"quads": quads, "verts": quads * 6 + bverts, "buildings": buildings.size(),
		"mm_instances": 0, "collisions": 0}


func _erase_paved_cells(cells: PackedByteArray) -> PackedByteArray:
	## Replace S_ROAD / S_SIDEWALK cells with the nearest non-road, non-sidewalk,
	## non-building cover (grass, verge, parking, plaza…), defaulting to grass.
	## The smooth road/sidewalk ribbons are drawn on top, so this only governs what
	## shows at the ribbon's edge — giving a smooth green (or plaza) boundary.
	var out := cells.duplicate()
	for row in range(CELLS):
		for col in range(CELLS):
			var t := cells[row * CELLS + col]
			if t != S_ROAD and t != S_SIDEWALK:
				continue
			var fill := S_MAINTAINED_GRASS
			var found := false
			for d in range(1, 5):
				for dir in [Vector2i(d, 0), Vector2i(-d, 0), Vector2i(0, d), Vector2i(0, -d)]:
					var dv: Vector2i = dir
					var rr := row + dv.y
					var cc := col + dv.x
					if rr < 0 or rr >= CELLS or cc < 0 or cc >= CELLS:
						continue
					var nt := cells[rr * CELLS + cc]
					if nt != S_ROAD and nt != S_SIDEWALK and nt != S_BUILDING:
						fill = nt
						found = true
						break
				if found:
					break
			out[row * CELLS + col] = fill
	return out


## Observed appearance value (BuildingAppearanceV1) for section/field, or "" when
## absent. Only OBSERVED/DERIVED values are carried in the bundle; PROCEDURAL
## nulls read as "". (Package B / C)
static func _appearance_hex(b: Dictionary, section: String, fld: String) -> String:
	var ap: Dictionary = b.get("appearance", {})
	if ap.is_empty():
		return ""
	var sec: Dictionary = ap.get(section, {})
	var c: Dictionary = sec.get(fld, {})
	var v = c.get("value", null)
	return String(v) if v != null else ""


static func _is_hex6(s: String) -> bool:
	return s.length() == 7 and s.begins_with("#")


## Facade colour: an observed/derived appearance colour wins; otherwise the
## archetype base colour with a stable per-building tint (original behaviour).
func _facade_color(b: Dictionary, bid: int, arch: String) -> Color:
	var hex := _appearance_hex(b, "facade", "color")
	if _is_hex6(hex):
		return Color.html(hex)
	var base_col: Color = BUILDING_ARCH_COLORS.get(arch, BUILDING_ARCH_COLORS["GENERIC_UNKNOWN"])
	var tint := (float(_stable_hash(bid, 7) % 1000) / 1000.0 - 0.5) * 0.12
	return Color(clampf(base_col.r + tint, 0.0, 1.0),
		clampf(base_col.g + tint, 0.0, 1.0), clampf(base_col.b + tint, 0.0, 1.0))


## Material-family ids from the building's compiled appearance (facade/roof
## material). These drive the semantic building shader; a missing value falls back
## to a safe neutral-ish family.
static func _appearance_material(b: Dictionary, section: String) -> String:
	var ap: Dictionary = b.get("appearance", {})
	if ap.is_empty():
		return ""
	var sec: Dictionary = ap.get(section, {})
	var m: Dictionary = sec.get("material", {})
	var v = m.get("value", null)
	return String(v) if v != null else ""


static func _facade_family_of(b: Dictionary) -> int:
	return WorldMaterials.facade_family(_appearance_material(b, "facade"))


static func _roof_family_of(b: Dictionary) -> int:
	return WorldMaterials.roof_family(_appearance_material(b, "roof"))


func _mass_building(st: SurfaceTool, b: Dictionary) -> int:
	var poly: Array = b.get("poly", [])
	if poly.size() < 3:
		return 0
	var h := float(b.get("h", 3.0))
	var bid := int(b.get("bid", 0))
	var arch := String(b.get("arch", "GENERIC_UNKNOWN"))
	var col := _facade_color(b, bid, arch)

	var ring := PackedVector2Array()
	for p in poly:
		ring.append(Vector2(float(p[0]), float(p[1])))
	var n := ring.size()
	var verts := 0
	var facade_fam := _facade_family_of(b)
	var roof_fam := _roof_family_of(b)
	# Flat roof top — observed roof colour wins, else a darkened facade tone. The
	# roof material family rides in COLOR.a for the semantic shader.
	var rhex := _appearance_hex(b, "roof", "color")
	var roof_base: Color = Color.html(rhex) if _is_hex6(rhex) else col.darkened(0.15)
	st.set_color(WorldMaterials.encode(roof_base, roof_fam))
	var tris := Geometry2D.triangulate_polygon(ring)
	for i in range(0, tris.size(), 3):
		for k in [tris[i], tris[i + 1], tris[i + 2]]:
			st.set_normal(Vector3.UP)
			st.add_vertex(Vector3(ring[k].x, h, ring[k].y))
		verts += 3
	# Walls — facade material family in COLOR.a.
	st.set_color(WorldMaterials.encode(col, facade_fam))
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


## AssetCatalogV1 render-variant table (render_kind -> variant count), loaded once
## from the catalog JSON so the renderer never hardcodes how many variants a
## family has. Unknown kinds default to 1 (single mesh).
static var _render_variants_cache: Dictionary = {}
static var _render_variants_loaded := false


static func _render_variant_count(kind: String) -> int:
	if not _render_variants_loaded:
		_render_variants_loaded = true
		var f := FileAccess.open("res://catalog_v1.json", FileAccess.READ)
		if f != null:
			var doc: Variant = JSON.parse_string(f.get_as_text())
			if typeof(doc) == TYPE_DICTIONARY and doc.has("render_variants"):
				_render_variants_cache = doc["render_variants"]
	return int(_render_variants_cache.get(kind, 1))


func _pos_variant(x: float, z: float) -> int:
	## Deterministic per-instance variant index from a continuous position.
	return _stable_hash(int(round(x * 4.0)), int(round(z * 4.0)))


static func _stable_hash(a: int, b: int) -> int:
	var x: int = (a * 0x9E3779B1) ^ (b * 0x85EBCA6B)
	x = x & 0x7FFFFFFF
	x ^= (x >> 13)
	x = (x * 0x2545F491) & 0x7FFFFFFF
	return x


# ------------------------------------------------------------------------- T2
func _build_t2(chunk: Dictionary, root: Node3D) -> Dictionary:
	var buildings: Array = chunk.get("buildings", [])
	# Decode the land-cover raster once: building detail infers doors/garages from
	# adjacent pavement, and the road ribbons let driveways cut the sidewalk.
	var origin_arr: Array = chunk.get("origin", [0.0, 0.0])
	var origin := Vector2(float(origin_arr[0]), float(origin_arr[1]))
	var runs: Array = chunk.get("surface", [])
	var cells := _decode_rle(runs, CELLS * CELLS) if not runs.is_empty() else PackedByteArray()
	var dst := SurfaceTool.new()
	dst.begin(Mesh.PRIMITIVE_TRIANGLES)
	var dverts := 0
	var body: StaticBody3D = null
	var collisions := 0
	var hvac_xforms: Array = []
	for b in buildings:
		dverts += _detail_building(dst, b, hvac_xforms, cells, origin)
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
		dmi.material_override = WorldMaterials.building_material()
		root.add_child(dmi)

	var mm_count := 0
	if not hvac_xforms.is_empty():
		var mmi := PropMeshes.make_multimesh("rooftop_hvac", hvac_xforms)
		root.add_child(mmi)
		mm_count += hvac_xforms.size()

	var sverts := _build_road_surfaces(chunk, root, cells, origin)
	var rverts := _build_road_markings(chunk, root)
	var everts := _build_elevated_roads(chunk, root)
	var gverts := _build_ground_markings(chunk, root)

	return {"quads": 0, "verts": dverts + rverts + everts + sverts + gverts, "buildings": buildings.size(),
		"mm_instances": mm_count, "collisions": collisions}


func _detail_building(st: SurfaceTool, b: Dictionary, hvac_xforms: Array,
		cells: PackedByteArray, origin: Vector2) -> int:
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
	var is_residential := arch == "DETACHED_RESIDENTIAL" or arch == "MULTIFAMILY"
	var is_house := arch == "DETACHED_RESIDENTIAL"
	# Full glass curtain wall (usually tall towers): the facade shader already draws
	# a continuous mullion grid, so skip the punched-window quads and let the whole
	# surface read as glazing.
	var is_glass_facade := _facade_family_of(b) == WorldMaterials.B_GLASS_CURTAIN
	var shutter_col: Color = SHUTTER_COLS[_stable_hash(bid, 29) % SHUTTER_COLS.size()]
	# Per-house massing is picked deterministically so a subdivision reads as varied
	# homes (some with a porch, some a garage, etc.) instead of copy-paste — and so a
	# dense chunk isn't every-house-everything.
	var want_porch := is_house and (_stable_hash(bid, 41) % 100) < 62
	var want_garage := is_house and (_stable_hash(bid, 43) % 100) < 52
	var want_patio := is_house and (_stable_hash(bid, 47) % 100) < 45
	var want_chimney := is_house and (_stable_hash(bid, 53) % 100) < 58
	# The edge roughly across from the entrance gets a small rear patio slab.
	var back_edge := ((ent_edge + poly.size() / 2) % poly.size()) if ent_edge >= 0 else -1

	var ring := PackedVector2Array()
	for p in poly:
		ring.append(Vector2(float(p[0]), float(p[1])))
	var n := ring.size()
	var verts := 0

	# Read the ground just outside each wall: an abutting concrete patch
	# (OTHER_IMPERVIOUS) is a driveway/walkway/patio. The widest one becomes the
	# garage edge (houses), narrower isolated ones become side/back doors — so
	# openings line up with the pavement that leads to them.
	var edge_pav_frac := PackedFloat32Array()
	var edge_pav_t := PackedFloat32Array()
	edge_pav_frac.resize(n)
	edge_pav_t.resize(n)
	var garage_edge := -1
	var garage_frac := 0.0
	if not cells.is_empty():
		for i in range(n):
			var a := ring[i]
			var c := ring[(i + 1) % n]
			var seg := c - a
			var length := seg.length()
			edge_pav_t[i] = 0.5
			if length <= 3.0:
				continue
			var nrm2 := Vector2(seg.y, -seg.x).normalized()
			var hits := 0
			var tsum := 0.0
			var samples := 6
			for s in range(samples):
				var t := (float(s) + 0.5) / float(samples)
				var pnt := a.lerp(c, t) + nrm2 * 2.2
				if _surface_class(cells, origin, pnt.x, pnt.y) == S_OTHER_IMPERVIOUS:
					hits += 1
					tsum += t
			var frac := float(hits) / float(samples)
			edge_pav_frac[i] = frac
			if hits > 0:
				edge_pav_t[i] = tsum / float(hits)
			if is_house and frac > garage_frac and frac >= 0.34 and length >= 5.0:
				garage_frac = frac
				garage_edge = i

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
		# Facade relief (sills, shutters, ledges) is a close-up, human-scale detail
		# that matters on homes. Restricting it to low-rise residential edges keeps
		# it affordable — commercial mid-rises and towers would emit hundreds of
		# thousands of verts per chunk, so they keep cheap flat window quads, which
		# read fine at iso distance.
		var edge_relief := is_house and length <= 30.0

		# Openings on this edge: the entrance door; a garage on the driveway edge
		# (houses); and a secondary door where an isolated concrete walkway/patio
		# abuts a non-entrance wall.
		var has_garage := want_garage and (i == garage_edge) and length >= ent_w + 6.5
		# A door here if this is the entrance edge, or a modest pavement patch
		# (walkway) touches this edge but it isn't the driveway/garage edge.
		var side_door := (not is_entrance_edge) and (not has_garage) \
			and edge_pav_frac[i] > 0.0 and edge_pav_frac[i] < 0.5
		var door_here := is_entrance_edge or side_door
		var door_t: float = ent_t if is_entrance_edge else edge_pav_t[i]
		var door_lo := 0.0
		var door_hi := -1.0
		var gar_t := edge_pav_t[i] if has_garage else 0.5
		var gar_lo := 0.0
		var gar_hi := -1.0
		if door_here:
			var dt := (ent_w * 0.5 + 0.6) / length
			door_lo = door_t - dt
			door_hi = door_t + dt
		if has_garage:
			var gw := 2.8
			gar_t = clampf(gar_t, (gw * 0.5 + 0.4) / length, 1.0 - (gw * 0.5 + 0.4) / length)
			var gg := (gw * 0.5 + 0.4) / length
			gar_lo = gar_t - gg
			gar_hi = gar_t + gg

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
			if is_glass_facade:
				continue   # curtain wall: glazing is the facade shader, no punched windows
			var win_h := floor_h * 0.55
			var win_y := y0 + floor_h * 0.3
			# Punched openings, not full glazing: wider spacing (houses widest) so
			# facades read as walls with windows rather than glass boxes.
			var win_spacing := 4.2 if is_house else (3.6 if is_residential else 3.0)
			var n_windows := maxi(1, int(round(length / win_spacing)))
			var along3 := Vector3(dir.x, 0.0, dir.y)
			for wi in range(n_windows):
				var t := (float(wi) + 0.5) / float(n_windows)
				# Keep windows off the ground-floor door and garage openings.
				if f == 0 and ((t >= door_lo and t <= door_hi)
						or (has_garage and t >= gar_lo and t <= gar_hi)):
					continue
				var center := a.lerp(c, t)
				var win_w := minf(1.2, length / float(n_windows) * 0.6)
				var half_w := win_w * 0.5
				var w0 := center - dir * half_w + nrm2 * 0.05
				var w1 := center + dir * half_w + nrm2 * 0.05
				verts += _quad_v(st, Vector3(w0.x, win_y, w0.y), Vector3(w1.x, win_y, w1.y),
					Vector3(w1.x, win_y + win_h, w1.y), Vector3(w0.x, win_y + win_h, w0.y),
					nrm3, GLASS_COL)
				# --- Ground-floor flanking shutters on houses for residential
				# character. Deliberately lean (houses, ground floor only, 2 small
				# boxes/window) so dense subdivisions stay within frame budget. ---
				if not (edge_relief and f < 1):
					continue
				var cwin := Vector3(center.x, 0.0, center.y)
				var jy := win_y + win_h * 0.5
				verts += _facade_box(st, cwin + Vector3(0.0, jy, 0.0) + along3 * (half_w + 0.18) + nrm3 * 0.05,
					along3, nrm3, 0.10, 0.05, win_h * 0.5, shutter_col)
				verts += _facade_box(st, cwin + Vector3(0.0, jy, 0.0) - along3 * (half_w + 0.18) + nrm3 * 0.05,
					along3, nrm3, 0.10, 0.05, win_h * 0.5, shutter_col)

		var along3e := Vector3(dir.x, 0.0, dir.y)
		# Garage door on the driveway edge: a recessed panel with a raised frame.
		if has_garage:
			var gc := a.lerp(c, gar_t)
			var gc3 := Vector3(gc.x, 0.0, gc.y)
			var gh := 2.1
			var ghw := 1.4
			var gp0 := gc - dir * ghw + nrm2 * 0.02
			var gp1 := gc + dir * ghw + nrm2 * 0.02
			verts += _quad_v(st, Vector3(gp0.x, 0.05, gp0.y), Vector3(gp1.x, 0.05, gp1.y),
				Vector3(gp1.x, gh, gp1.y), Vector3(gp0.x, gh, gp0.y), nrm3, GARAGE_COL)
			verts += _facade_box(st, gc3 + Vector3(0.0, gh + 0.08, 0.0) + nrm3 * 0.05,
				along3e, nrm3, ghw + 0.12, 0.09, 0.08, FRAME_COL)
		# Entrance / secondary door where pavement leads to it.
		if door_here and not is_storefront:
			var dc := a.lerp(c, door_t)
			var hw := ent_w * 0.5
			var e0 := dc - dir * hw + nrm2 * 0.06
			var e1 := dc + dir * hw + nrm2 * 0.06
			verts += _quad_v(st, Vector3(e0.x, 0.0, e0.y), Vector3(e1.x, 0.0, e1.y),
				Vector3(e1.x, 2.2, e1.y), Vector3(e0.x, 2.2, e0.y), nrm3, DOOR_COL)
			# Front porch: a real covered volume (platform + posts + roof) at the
			# main entrance.
			if want_porch and is_entrance_edge:
				var pw := minf(ent_w + 2.6, length * 0.7)
				var pdepth := 2.2
				var dc3 := Vector3(dc.x, 0.0, dc.y)
				var pc := dc3 + nrm3 * (pdepth * 0.5)
				verts += _facade_box(st, pc + Vector3(0.0, 0.09, 0.0),
					along3e, nrm3, pw * 0.5, pdepth * 0.5, 0.09, PLATFORM_COL)
				verts += _facade_box(st, dc3 + nrm3 * (pdepth * 0.5) + Vector3(0.0, 2.5, 0.0),
					along3e, nrm3, pw * 0.5 + 0.25, pdepth * 0.5 + 0.25, 0.08, PORCH_ROOF_COL)
				for ps in [-1.0, 1.0]:
					var psf := float(ps)
					var post := dc3 + along3e * (psf * (pw * 0.5 - 0.15)) + nrm3 * (pdepth - 0.2)
					verts += _facade_box(st, post + Vector3(0.0, 1.28, 0.0),
						along3e, nrm3, 0.09, 0.09, 1.2, PORCH_POST_COL)

		# Rear patio slab: a low ground deck behind the house.
		if want_patio and i == back_edge and length > 4.0:
			var mid := a.lerp(c, 0.5)
			var mid3 := Vector3(mid.x, 0.0, mid.y)
			var patio_d := 2.6
			var patio_w := minf(4.0, length * 0.55)
			verts += _facade_box(st, mid3 + nrm3 * (patio_d * 0.5) + Vector3(0.0, 0.06, 0.0),
				Vector3(dir.x, 0.0, dir.y), nrm3, patio_w * 0.5, patio_d * 0.5, 0.06, PATIO_COL)

	# Package H: business signage (fascia/wall plaque/marquee/monument) tinted
	# from the building's fictional business identity. Non-residential only
	# (identity is absent on homes), a few quads each.
	verts += _render_signage(st, b, ring, floor_h, is_storefront, cells, origin)

	# Roof: elongated rectangles read best as a simple gable; square rectangles and
	# L/T/complex footprints get a hip roof that follows the real outline (so
	# complicated buildings still get a sloped roof); flat roofs get detailed.
	var roof_shape := "flat"
	if roof == "pitched":
		var roof_col := ROOF_COL
		match _stable_hash(bid, 23) % 5:
			0: roof_col = Color(0.30, 0.30, 0.34)   # charcoal
			1: roof_col = Color(0.36, 0.29, 0.25)   # brown shingle
			2: roof_col = Color(0.27, 0.31, 0.38)   # slate blue
			3: roof_col = Color(0.31, 0.34, 0.31)   # grey-green
			4: roof_col = Color(0.40, 0.32, 0.28)   # terracotta-ish
		var rhex := _appearance_hex(b, "roof", "color")   # observed roof colour wins
		if _is_hex6(rhex):
			roof_col = Color.html(rhex)
		# Roof material family in COLOR.a → asphalt courses / standing seam / tile.
		roof_col = WorldMaterials.encode(roof_col, _roof_family_of(b))
		var rect := _is_roughly_rectangular(ring)
		var oh := _obb_half(ring)
		var minhalf := minf(oh.x, oh.y)
		var aspect := maxf(oh.x, oh.y) / maxf(minhalf, 0.01)
		if rect and aspect >= 1.7:
			verts += _pitched_roof(st, ring, h, roof_col)
			roof_shape = "gable"
		else:
			var rise := clampf(minhalf * 0.85, 1.2, 4.5)
			var inset := clampf(minhalf * 0.5, 0.7, 3.0)
			var hv := _hip_roof(st, ring, h, rise, inset, roof_col)
			if hv > 0:
				verts += hv
				roof_shape = "hip"
			elif rect:
				verts += _pitched_roof(st, ring, h, roof_col)
				roof_shape = "gable"
			else:
				verts += _flat_roof_detail(st, ring, h, bid, not is_residential)
	else:
		verts += _flat_roof_detail(st, ring, h, bid, not is_residential)

	# Brick chimney poking through a house roof (only on the rectangular gables that
	# kept a pitched roof, so the OBB matches the ridge).
	if want_chimney and roof_shape != "flat":
		var cen := Vector2.ZERO
		for p in ring:
			cen += p
		cen /= float(ring.size())
		var axis := Vector2(1.0, 0.0)
		var best := 0.0
		for i2 in range(ring.size()):
			var e := ring[(i2 + 1) % ring.size()] - ring[i2]
			var l := e.length()
			if l > best:
				best = l
				axis = e / l
		var perp := Vector2(-axis.y, axis.x)
		var minu := INF; var maxu := -INF; var minv := INF; var maxv := -INF
		for p in ring:
			var d := p - cen
			var u := d.dot(axis); var v := d.dot(perp)
			minu = minf(minu, u); maxu = maxf(maxu, u)
			minv = minf(minv, v); maxv = maxf(maxv, v)
		var half_u := (maxu - minu) * 0.5
		var half_v := (maxv - minv) * 0.5
		var ridge_h := h + minf(half_u, half_v) * 0.7
		var side := 1.0 if (_stable_hash(bid, 31) % 2) == 0 else -1.0
		var cu := (minu + maxu) * 0.5 + (maxu - minu) * 0.24 * side
		var cv := (minv + maxv) * 0.5 + (maxv - minv) * 0.16
		var base_y := h - 0.3
		var top_y := ridge_h + 0.7
		var pos := cen + axis * cu + perp * cv
		verts += _facade_box(st, Vector3(pos.x, (base_y + top_y) * 0.5, pos.y),
			Vector3(axis.x, 0.0, axis.y), Vector3(perp.x, 0.0, perp.y),
			0.35, 0.35, (top_y - base_y) * 0.5, CHIMNEY_COL)

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


## An oriented box protruding from a wall, for facade trim (sills, headers, shutters,
## string courses). `center` is the box centre; `along` is the unit edge tangent and
## `out` the unit outward wall normal (both XZ). Half-sizes: hw along the edge, hd
## outward, hh vertical. Emits 6 faces with correct outward normals.
func _facade_box(st: SurfaceTool, center: Vector3, along: Vector3, out: Vector3,
		hw: float, hd: float, hh: float, col: Color) -> int:
	var up := Vector3(0.0, hh, 0.0)
	var a := along * hw
	var b := out * hd
	# 8 corners keyed (sa, sb, su)
	var ppp := center + a + b + up
	var ppm := center + a + b - up
	var pmp := center + a - b + up
	var pmm := center + a - b - up
	var mpp := center - a + b + up
	var mpm := center - a + b - up
	var mmp := center - a - b + up
	var mmm := center - a - b - up
	var verts := 0
	verts += _quad_v(st, mpm, ppm, ppp, mpp, out, col)          # outward (+b)
	verts += _quad_v(st, pmm, mmm, mmp, pmp, -out, col)         # inward (-b)
	verts += _quad_v(st, mmp, mpp, ppp, pmp, Vector3.UP, col)   # top
	verts += _quad_v(st, mmm, pmm, ppm, mpm, Vector3.DOWN, col) # bottom
	verts += _quad_v(st, pmm, ppm, ppp, pmp, along, col)        # +a end
	verts += _quad_v(st, mpm, mmm, mmp, mpp, -along, col)       # -a end
	return verts


## A palette colour from a business identity, or a fallback when absent/malformed.
static func _sign_hex(pal: Dictionary, key: String, fallback: Color) -> Color:
	var v: String = String(pal.get(key, ""))
	return Color.html(v) if _is_hex6(v) else fallback


## A small logo emblem on a sign face: an accent plate plus a cheap glyph mark so
## businesses read as distinct at iso scale. `c` is the plate centre, `along`/`out`
## the sign's tangent/outward unit vectors, `r` the plate half-size. Kept to a
## handful of quads (only non-residential buildings emit signage).
func _sign_emblem(st: SurfaceTool, c: Vector3, along: Vector3, out: Vector3,
		glyph: String, accent: Color, secondary: Color, r: float) -> int:
	var f := out * 0.03
	var up := Vector3(0.0, 1.0, 0.0)
	var verts := 0
	# accent plate
	var p0 := c + f - along * r - up * r
	var p1 := c + f + along * r - up * r
	var p2 := c + f + along * r + up * r
	var p3 := c + f - along * r + up * r
	verts += _quad_v(st, p0, p1, p2, p3, out, accent)
	var f2 := out * 0.05
	match glyph:
		"bars":
			for s in [-0.5, 0.5]:
				var sf := float(s)
				var b0 := c + f2 + along * (sf * r - r * 0.14) - up * r * 0.7
				var b1 := c + f2 + along * (sf * r + r * 0.14) - up * r * 0.7
				var b2 := c + f2 + along * (sf * r + r * 0.14) + up * r * 0.7
				var b3 := c + f2 + along * (sf * r - r * 0.14) + up * r * 0.7
				verts += _quad_v(st, b0, b1, b2, b3, out, secondary)
		"cross":
			var h0 := c + f2 - along * r * 0.7 - up * r * 0.18
			var h1 := c + f2 + along * r * 0.7 - up * r * 0.18
			var h2 := c + f2 + along * r * 0.7 + up * r * 0.18
			var h3 := c + f2 - along * r * 0.7 + up * r * 0.18
			verts += _quad_v(st, h0, h1, h2, h3, out, secondary)
			var v0 := c + f2 - along * r * 0.18 - up * r * 0.7
			var v1 := c + f2 + along * r * 0.18 - up * r * 0.7
			var v2 := c + f2 + along * r * 0.18 + up * r * 0.7
			var v3 := c + f2 - along * r * 0.18 + up * r * 0.7
			verts += _quad_v(st, v0, v1, v2, v3, out, secondary)
		"chevron", "triangle", "arch":
			var t0 := c + f2 - along * r * 0.7 - up * r * 0.5
			var t1 := c + f2 + along * r * 0.7 - up * r * 0.5
			var t2 := c + f2 + up * r * 0.6
			verts += _tri_v(st, t0, t1, t2, secondary)
		"ring", "disc":
			var g := r * 0.5
			var d0 := c + f2 - along * g - up * g
			var d1 := c + f2 + along * g - up * g
			var d2 := c + f2 + along * g + up * g
			var d3 := c + f2 - along * g + up * g
			verts += _quad_v(st, d0, d1, d2, d3, out, secondary)
		_:
			var g2 := r * 0.42
			var e0 := c + f2 - along * g2 - up * g2
			var e1 := c + f2 + along * g2 - up * g2
			var e2 := c + f2 + along * g2 + up * g2
			var e3 := c + f2 - along * g2 + up * g2
			verts += _quad_v(st, e0, e1, e2, e3, out, secondary)
	return verts


## Package H: building-integrated business signage. Reads the building's fictional
## business identity and tints sign hardware from its palette. Storefronts get a
## fascia band; other non-residential buildings get a wall plaque; big-box/pole
## and monument categories add a raised marquee or a ground monument where a
## frontage pad exists. All emitted into the shared building mesh (batching kept).
func _render_signage(st: SurfaceTool, b: Dictionary, ring: PackedVector2Array,
		floor_h: float, is_storefront: bool, cells: PackedByteArray,
		origin: Vector2) -> int:
	var ident: Dictionary = b.get("identity", {})
	if ident.is_empty():
		return 0
	var pal: Dictionary = ident.get("palette", {})
	var primary := _sign_hex(pal, "primary", Color(0.55, 0.30, 0.20))
	var secondary := _sign_hex(pal, "secondary", primary.lightened(0.25))
	var accent := _sign_hex(pal, "accent", Color(0.92, 0.92, 0.86))
	var glyph := String(ident.get("logo_glyph", "disc"))
	var sign_family := String(ident.get("sign_family", "wall_sign"))
	var h := float(b.get("h", 3.0))
	var n := ring.size()
	var ent: Dictionary = b.get("entrance", {})
	var ent_edge := int(ent.get("edge", -1))
	var ent_t := float(ent.get("t", 0.5))
	var ent_w := float(ent.get("w", 1.6))
	if ent_edge < 0 or ent_edge >= n:
		ent_edge = 0
	var a := ring[ent_edge]
	var c := ring[(ent_edge + 1) % n]
	var seg := c - a
	var length := seg.length()
	if length < 3.0:
		return 0
	var dir := seg / length
	var nrm2 := Vector2(seg.y, -seg.x).normalized()
	var nrm3 := Vector3(nrm2.x, 0.0, nrm2.y)
	var along3 := Vector3(dir.x, 0.0, dir.y)
	var center := a.lerp(c, ent_t)
	var verts := 0

	if is_storefront:
		# fascia band spanning the shopfront, just above the glazing.
		var inset := minf(0.7, length * 0.12)
		var band_h := clampf(floor_h * 0.5, 0.7, 1.1)
		var band_y := floor_h * 1.3 + 0.05 + band_h * 0.5
		var mid := a.lerp(c, 0.5)
		var fc := Vector3(mid.x, band_y, mid.y) + nrm3 * 0.10
		verts += _facade_box(st, fc, along3, nrm3, (length - 2.0 * inset) * 0.5,
			0.12, band_h * 0.5, primary)
		verts += _sign_emblem(st, fc + nrm3 * 0.14, along3, nrm3, glyph, accent,
			secondary, band_h * 0.30)
	else:
		# wall plaque above the entrance for offices/civic/industrial and
		# non-storefront commercial.
		var py := clampf(h * 0.5, 2.6, 4.2)
		var pw := clampf(ent_w * 1.4, 1.8, 3.2)
		var wc := Vector3(center.x, py, center.y) + nrm3 * 0.10
		verts += _facade_box(st, wc, along3, nrm3, pw * 0.5, 0.09, 0.45, primary)
		verts += _sign_emblem(st, wc + nrm3 * 0.12, along3, nrm3, glyph, accent,
			secondary, 0.30)

	# Big-box / pole categories: a raised parapet marquee above the entrance —
	# collision-free, reads as a tall storefront sign at distance.
	if sign_family == "pole_sign":
		var mw := clampf(length * 0.4, 2.4, 6.0)
		var my := h + 0.9
		var mc := Vector3(center.x, my, center.y) + nrm3 * 0.20
		verts += _facade_box(st, mc, along3, nrm3, mw * 0.5, 0.14, 0.9, primary)
		# short posts down to the parapet
		for s in [-1.0, 1.0]:
			var sf := float(s)
			var pc := Vector3(center.x, h + 0.45, center.y) + nrm3 * 0.20 \
				+ along3 * (sf * mw * 0.4)
			verts += _facade_box(st, pc, along3, nrm3, 0.08, 0.08, 0.45, secondary)
		verts += _sign_emblem(st, mc + nrm3 * 0.16, along3, nrm3, glyph, accent,
			secondary, 0.5)
	# Monument categories: a low ground sign on a frontage pad, only where the
	# ground just outside the entrance is a concrete apron (no road/lawn collide).
	elif sign_family == "monument_sign":
		var out_pt := center + nrm2 * 1.9
		if cells.is_empty() or _surface_class(cells, origin, out_pt.x, out_pt.y) == S_OTHER_IMPERVIOUS:
			var oc := Vector3(out_pt.x, 0.0, out_pt.y)
			verts += _facade_box(st, oc + Vector3(0.0, 0.12, 0.0), along3, nrm3,
				1.1, 0.35, 0.12, secondary)
			var panel := oc + Vector3(0.0, 0.85, 0.0)
			verts += _facade_box(st, panel, along3, nrm3, 1.1, 0.16, 0.7, primary)
			verts += _sign_emblem(st, panel - nrm3 * 0.18, along3, -nrm3, glyph,
				accent, secondary, 0.42)
			verts += _sign_emblem(st, panel + nrm3 * 0.18, along3, nrm3, glyph,
				accent, secondary, 0.42)
	return verts


func _pitched_roof(st: SurfaceTool, ring: PackedVector2Array, h: float,
		col: Color = ROOF_COL) -> int:
	# Gable built over the footprint's ORIENTED bounding box (aligned to the
	# building's longest edge) with a small eave overhang, so the roof follows a
	# rotated/angled footprint instead of an axis-aligned bbox that overhangs the
	# real walls. Ridge runs along the building's long axis.
	var n := ring.size()
	if n < 3:
		return 0
	# primary axis = direction of the longest edge
	var axis := Vector2(1.0, 0.0)
	var best_len := 0.0
	for i in range(n):
		var e := ring[(i + 1) % n] - ring[i]
		var l := e.length()
		if l > best_len:
			best_len = l
			axis = e / l
	var perp := Vector2(-axis.y, axis.x)
	var c := Vector2.ZERO
	for p in ring:
		c += p
	c /= float(n)
	var minu := INF; var maxu := -INF; var minv := INF; var maxv := -INF
	for p in ring:
		var d := p - c
		var u := d.dot(axis); var v := d.dot(perp)
		minu = minf(minu, u); maxu = maxf(maxu, u)
		minv = minf(minv, v); maxv = maxf(maxv, v)
	# small eave overhang past the walls
	var eave := 0.4
	minu -= eave; maxu += eave; minv -= eave; maxv += eave
	var half_u := (maxu - minu) * 0.5
	var half_v := (maxv - minv) * 0.5
	var midu := (minu + maxu) * 0.5
	var midv := (minv + maxv) * 0.5
	var ridge_h := h + minf(half_u, half_v) * 0.7
	var verts := 0
	if half_u >= half_v:
		# ridge along axis (u); slopes fall toward ±v
		var r0 := _obb_world(c, axis, perp, midu - half_u, midv, ridge_h)
		var r1 := _obb_world(c, axis, perp, midu + half_u, midv, ridge_h)
		var e0 := _obb_world(c, axis, perp, midu - half_u, midv - half_v, h)
		var e1 := _obb_world(c, axis, perp, midu + half_u, midv - half_v, h)
		var e2 := _obb_world(c, axis, perp, midu + half_u, midv + half_v, h)
		var e3 := _obb_world(c, axis, perp, midu - half_u, midv + half_v, h)
		verts += _quad_v(st, e0, e1, r1, r0, Vector3.UP, col)
		verts += _quad_v(st, e3, e2, r1, r0, Vector3.UP, col)
		verts += _tri_v(st, e0, e3, r0, col)
		verts += _tri_v(st, e1, e2, r1, col)
	else:
		# ridge along perp (v); slopes fall toward ±u
		var r0b := _obb_world(c, axis, perp, midu, midv - half_v, ridge_h)
		var r1b := _obb_world(c, axis, perp, midu, midv + half_v, ridge_h)
		var f0 := _obb_world(c, axis, perp, midu - half_u, midv - half_v, h)
		var f1 := _obb_world(c, axis, perp, midu + half_u, midv - half_v, h)
		var f2 := _obb_world(c, axis, perp, midu + half_u, midv + half_v, h)
		var f3 := _obb_world(c, axis, perp, midu - half_u, midv + half_v, h)
		verts += _quad_v(st, f0, f3, r1b, r0b, Vector3.UP, col)
		verts += _quad_v(st, f1, f2, r1b, r0b, Vector3.UP, col)
		verts += _tri_v(st, f0, f1, r0b, col)
		verts += _tri_v(st, f3, f2, r1b, col)
	return verts


func _obb_world(c: Vector2, axis: Vector2, perp: Vector2, u: float, v: float, y: float) -> Vector3:
	var w := c + axis * u + perp * v
	return Vector3(w.x, y, w.y)


func _is_roughly_rectangular(ring: PackedVector2Array) -> bool:
	## True when the polygon fills most of its oriented bounding box, i.e. a single
	## gable will sit on it without overhanging. Uses |shoelace area| / obb area.
	var n := ring.size()
	if n < 3:
		return false
	var area2 := 0.0
	for i in range(n):
		var a := ring[i]
		var b := ring[(i + 1) % n]
		area2 += a.x * b.y - b.x * a.y
	var poly_area := absf(area2) * 0.5
	# oriented bbox from the longest edge
	var axis := Vector2(1.0, 0.0)
	var best_len := 0.0
	for i in range(n):
		var e := ring[(i + 1) % n] - ring[i]
		var l := e.length()
		if l > best_len:
			best_len = l
			axis = e / l
	var perp := Vector2(-axis.y, axis.x)
	var minu := INF; var maxu := -INF; var minv := INF; var maxv := -INF
	for p in ring:
		var u := p.dot(axis); var v := p.dot(perp)
		minu = minf(minu, u); maxu = maxf(maxu, u)
		minv = minf(minv, v); maxv = maxf(maxv, v)
	var obb_area := maxf(maxu - minu, 0.01) * maxf(maxv - minv, 0.01)
	return poly_area / obb_area >= 0.82


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


## Half-extents of a footprint's oriented bounding box (u = longest-edge axis).
func _obb_half(ring: PackedVector2Array) -> Vector2:
	var n := ring.size()
	if n < 3:
		return Vector2(1.0, 1.0)
	var axis := Vector2(1.0, 0.0)
	var best := 0.0
	for i in range(n):
		var e := ring[(i + 1) % n] - ring[i]
		var l := e.length()
		if l > best:
			best = l
			axis = e / l
	var perp := Vector2(-axis.y, axis.x)
	var minu := INF; var maxu := -INF; var minv := INF; var maxv := -INF
	for p in ring:
		var u := p.dot(axis); var v := p.dot(perp)
		minu = minf(minu, u); maxu = maxf(maxu, u)
		minv = minf(minv, v); maxv = maxf(maxv, v)
	return Vector2((maxu - minu) * 0.5, (maxv - minv) * 0.5)


## Inset a polygon inward by `dist` metres along each vertex's angle bisector.
func _inset_ring(ring: PackedVector2Array, dist: float) -> PackedVector2Array:
	var n := ring.size()
	var out := PackedVector2Array()
	if n < 3:
		return out
	var area2 := 0.0
	for i in range(n):
		var a := ring[i]; var b := ring[(i + 1) % n]
		area2 += a.x * b.y - b.x * a.y
	var ccw := area2 > 0.0
	for i in range(n):
		var prev := ring[(i - 1 + n) % n]
		var cur := ring[i]
		var nxt := ring[(i + 1) % n]
		var din := cur - prev
		var dout := nxt - cur
		if din.length() < 0.0001 or dout.length() < 0.0001:
			out.append(cur)
			continue
		din = din.normalized(); dout = dout.normalized()
		var nin := Vector2(-din.y, din.x) if ccw else Vector2(din.y, -din.x)
		var nout := Vector2(-dout.y, dout.x) if ccw else Vector2(dout.y, -dout.x)
		var mm := nin + nout
		if mm.length() < 0.0001:
			out.append(cur + nout * dist)
			continue
		mm = mm.normalized()
		var denom := maxf(0.35, mm.dot(nout))
		out.append(cur + mm * (dist / denom))
	return out


## A hip roof that follows ANY footprint: slope every wall up to an inset ridge
## ring, then cap the ridge flat. Returns <= 0 if the inset collapsed/inverted so
## the caller can fall back. Works for rectangles (true hip) and L/T shapes alike.
func _hip_roof(st: SurfaceTool, ring: PackedVector2Array, h: float, rise: float,
		inset: float, col: Color) -> int:
	var n := ring.size()
	if n < 3:
		return -1
	var inner := _inset_ring(ring, inset)
	if inner.size() != n:
		return -1
	var oarea := 0.0
	var iarea := 0.0
	for i in range(n):
		oarea += ring[i].x * ring[(i + 1) % n].y - ring[(i + 1) % n].x * ring[i].y
		iarea += inner[i].x * inner[(i + 1) % n].y - inner[(i + 1) % n].x * inner[i].y
	if signf(iarea) != signf(oarea) or absf(iarea) * 0.5 < 1.0:
		return -1                                   # collapsed / self-intersected
	var ridge_y := h + rise
	var verts := 0
	for i in range(n):
		var o0 := ring[i]; var o1 := ring[(i + 1) % n]
		var i0 := inner[i]; var i1 := inner[(i + 1) % n]
		verts += _quad_auto(st, Vector3(o0.x, h, o0.y), Vector3(o1.x, h, o1.y),
			Vector3(i1.x, ridge_y, i1.y), Vector3(i0.x, ridge_y, i0.y), col)
	var top_col := col.lightened(0.05)
	var tris := Geometry2D.triangulate_polygon(inner)
	for k in range(0, tris.size(), 3):
		st.set_color(top_col)
		for m in [tris[k], tris[k + 1], tris[k + 2]]:
			st.set_normal(Vector3.UP)
			st.add_vertex(Vector3(inner[m].x, ridge_y, inner[m].y))
		verts += 3
	return verts


## A quad with an auto-computed (upward-biased) face normal.
func _quad_auto(st: SurfaceTool, p0: Vector3, p1: Vector3, p2: Vector3, p3: Vector3,
		col: Color) -> int:
	var nrm := (p1 - p0).cross(p2 - p0).normalized()
	if nrm.y < 0.0:
		nrm = -nrm
	return _quad_v(st, p0, p1, p2, p3, nrm, col)


## Detail a flat roof: a perimeter parapet plus (for non-residential) a few rooftop
## mechanical units and, on larger roofs, a stair penthouse — so flat tops aren't bare.
func _flat_roof_detail(st: SurfaceTool, ring: PackedVector2Array, h: float,
		bid: int, mech: bool) -> int:
	var n := ring.size()
	if n < 3:
		return 0
	var verts := 0
	var min_x := INF; var min_z := INF; var max_x := -INF; var max_z := -INF
	for p in ring:
		min_x = minf(min_x, p.x); max_x = maxf(max_x, p.x)
		min_z = minf(min_z, p.y); max_z = maxf(max_z, p.y)
	var area := (max_x - min_x) * (max_z - min_z)
	if area >= 20.0:
		verts += _parapet(st, ring, h)
	if not mech or area < 40.0:
		return verts
	var units := clampi(int(area / 220.0), 1, 4)
	var xa := Vector3(1.0, 0.0, 0.0)
	var za := Vector3(0.0, 0.0, 1.0)
	# Equipment is rejection-sampled INSIDE the real footprint polygon, not just
	# the AABB: an L-shaped / non-rectangular roof would otherwise place HVAC units
	# and penthouses out over thin air past the actual roof edge. Sampling stays
	# deterministic (stable-hash driven) so reloads reproduce the same layout.
	var placed := 0
	var attempt := 0
	while placed < units and attempt < units * 8:
		var fx := float(_stable_hash(bid, 61 + attempt * 7) % 1000) / 1000.0
		var fz := float(_stable_hash(bid, 62 + attempt * 7) % 1000) / 1000.0
		attempt += 1
		var ux := lerpf(min_x + 2.0, max_x - 2.0, fx)
		var uz := lerpf(min_z + 2.0, max_z - 2.0, fz)
		if not Geometry2D.is_point_in_polygon(Vector2(ux, uz), ring):
			continue
		verts += _facade_box(st, Vector3(ux, h + 0.45, uz), xa, za, 0.9, 0.65, 0.45, MECH_COL)
		placed += 1
	if area >= 300.0:
		var cx := (min_x + max_x) * 0.5
		var cz := (min_z + max_z) * 0.5
		var ok := Geometry2D.is_point_in_polygon(Vector2(cx, cz), ring)
		if not ok:
			# Concave footprint: the AABB centre fell outside the polygon. Find a
			# guaranteed-interior spot before dropping the penthouse.
			for k in range(24):
				var px := lerpf(min_x + 2.0, max_x - 2.0,
					float(_stable_hash(bid, 200 + k * 3) % 1000) / 1000.0)
				var pz := lerpf(min_z + 2.0, max_z - 2.0,
					float(_stable_hash(bid, 201 + k * 3) % 1000) / 1000.0)
				if Geometry2D.is_point_in_polygon(Vector2(px, pz), ring):
					cx = px; cz = pz; ok = true; break
		if ok:
			verts += _facade_box(st, Vector3(cx, h + 1.1, cz), xa, za, 1.5, 1.2, 1.1, PENTHOUSE_COL)
	return verts


## Continuous road/sidewalk/curb ribbons built from each road's real polyline
## with mitered joins, laid over the rasterized ground so curves read smoothly.
## Widths, curbs and sidewalks are data-driven (carriage_w / curb / sidewalk_w /
## verge_w from the world source), not tiles.
func _build_road_surfaces(chunk: Dictionary, root: Node3D,
		cells: PackedByteArray, origin: Vector2) -> int:
	var roads: Array = chunk.get("roads", [])
	if roads.is_empty():
		return 0
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var verts := 0
	var any := false
	for r in roads:
		if bool(r.get("elevated", false)):
			continue                                   # decks handled by _build_elevated_roads
		var pts_raw: Array = r.get("pts", [])
		if pts_raw.size() < 2:
			continue
		var pts: Array = []
		for p in pts_raw:
			pts.append(Vector2(float(p[0]), float(p[1])))
		if bool(r.get("path_only", false)):
			# Footpath/trail: a thin light ribbon, gently raised.
			var phw := maxf(0.6, float(r.get("carriage_w", 1.6)) * 0.5)
			var pl := _offset_polyline(pts, -phw)
			var pr := _offset_polyline(pts, phw)
			verts += _ribbon_flat(st, pl, pr, PATH_Y, WorldMaterials.encode(SURFACE_COLORS[S_SIDEWALK], S_SIDEWALK))
			any = true
			continue
		var carriage_w := float(r.get("carriage_w", 6.0))
		if carriage_w < 0.5:
			continue
		var hw := carriage_w * 0.5
		var edge_l := _offset_polyline(pts, -hw)
		var edge_r := _offset_polyline(pts, hw)
		verts += _ribbon_flat(st, edge_l, edge_r, ROAD_RIBBON_Y, WorldMaterials.encode(SURFACE_COLORS[S_ROAD], S_ROAD))
		any = true
		var has_curb := bool(r.get("curb", false))
		var sidewalk_w := float(r.get("sidewalk_w", 0.0))
		var verge_w := float(r.get("verge_w", 0.0))
		if not has_curb and sidewalk_w <= 0.0:
			continue
		# Curb + sidewalk on both sides, drawn per segment so a driveway/apron
		# crossing (an impervious patch under the sidewalk band) interrupts the curb
		# and sidewalk — the driveway reads as running unbroken from road to garage.
		var swidth: float = sidewalk_w if sidewalk_w > 0.0 else 1.5
		for side in [-1.0, 1.0]:
			var sidef := float(side)
			var edge := edge_r if sidef > 0.0 else edge_l
			var inner := _offset_polyline(pts, sidef * (hw + verge_w))
			var outer := _offset_polyline(pts, sidef * (hw + verge_w + swidth))
			for i in range(pts.size() - 1):
				var pa: Vector2 = pts[i]
				var pb: Vector2 = pts[i + 1]
				var d := pb - pa
				if d.length() < 0.0001:
					continue
				var sn := Vector2(d.y, -d.x).normalized() * sidef
				var samp := (pa + pb) * 0.5 + sn * (hw + verge_w + swidth * 0.5)
				var sc := _surface_class(cells, origin, samp.x, samp.y)
				if sc == S_OTHER_IMPERVIOUS or sc == S_PARKING:
					continue                                # driveway cuts through here
				var nrm3 := Vector3(sn.x, 0.0, sn.y)
				var e0: Vector2 = edge[i]
				var e1: Vector2 = edge[i + 1]
				var in0: Vector2 = inner[i]
				var in1: Vector2 = inner[i + 1]
				var ou0: Vector2 = outer[i]
				var ou1: Vector2 = outer[i + 1]
				var curb_c := WorldMaterials.encode(CURB_COL, S_OTHER_IMPERVIOUS)
				var walk_c := WorldMaterials.encode(SURFACE_COLORS[S_SIDEWALK], S_SIDEWALK)
				if has_curb:
					verts += _quad_v(st, Vector3(e0.x, ROAD_RIBBON_Y, e0.y),
						Vector3(e1.x, ROAD_RIBBON_Y, e1.y), Vector3(e1.x, SIDEWALK_Y, e1.y),
						Vector3(e0.x, SIDEWALK_Y, e0.y), nrm3, curb_c)
				verts += _quad_v(st, Vector3(in0.x, SIDEWALK_Y, in0.y),
					Vector3(ou0.x, SIDEWALK_Y, ou0.y), Vector3(ou1.x, SIDEWALK_Y, ou1.y),
					Vector3(in1.x, SIDEWALK_Y, in1.y), Vector3.UP, walk_c)
				verts += _quad_v(st, Vector3(ou0.x, 0.03, ou0.y),
					Vector3(ou1.x, 0.03, ou1.y), Vector3(ou1.x, SIDEWALK_Y, ou1.y),
					Vector3(ou0.x, SIDEWALK_Y, ou0.y), nrm3, curb_c)
	if not any:
		return 0
	var mesh := st.commit()
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.material_override = WorldMaterials.ground_material()
	root.add_child(mi)
	return verts


## Offset a polyline sideways by `offset` metres (right-hand normal is +) with
## mitered joins, so parallel ribbon edges stay continuous around bends.
func _offset_polyline(pts: Array, offset: float) -> Array:
	var out: Array = []
	var n := pts.size()
	for i in range(n):
		var p: Vector2 = pts[i]
		var nin := Vector2.ZERO
		var nout := Vector2.ZERO
		if i > 0:
			var din: Vector2 = (pts[i] - pts[i - 1])
			if din.length() > 0.0001:
				din = din.normalized()
				nin = Vector2(din.y, -din.x)
		if i < n - 1:
			var dout: Vector2 = (pts[i + 1] - pts[i])
			if dout.length() > 0.0001:
				dout = dout.normalized()
				nout = Vector2(dout.y, -dout.x)
		var m: Vector2
		if nin == Vector2.ZERO:
			m = nout
		elif nout == Vector2.ZERO:
			m = nin
		else:
			var mm := (nin + nout)
			if mm.length() < 0.0001:
				m = nout
			else:
				mm = mm.normalized()
				var denom := maxf(0.35, mm.dot(nout))   # clamp miter length at sharp bends
				m = mm / denom
		out.append(p + m * offset)
	return out


## Flat strip between two equal-length polylines at height `y`.
func _ribbon_flat(st: SurfaceTool, left: Array, right: Array, y: float, col: Color) -> int:
	var n := mini(left.size(), right.size())
	var verts := 0
	for i in range(n - 1):
		var l0: Vector2 = left[i]
		var l1: Vector2 = left[i + 1]
		var r0: Vector2 = right[i]
		var r1: Vector2 = right[i + 1]
		verts += _quad_v(st, Vector3(l0.x, y, l0.y), Vector3(r0.x, y, r0.y),
			Vector3(r1.x, y, r1.y), Vector3(l1.x, y, l1.y), Vector3.UP, col)
	return verts


## Vertical strip along a single polyline from y0 to y1 (curb faces / sidewalk drops).
func _ribbon_wall(st: SurfaceTool, poly: Array, y0: float, y1: float, col: Color) -> int:
	var n := poly.size()
	var verts := 0
	for i in range(n - 1):
		var a: Vector2 = poly[i]
		var b: Vector2 = poly[i + 1]
		var seg := b - a
		if seg.length() < 0.0001:
			continue
		var nrm2 := seg.orthogonal().normalized()
		var nrm3 := Vector3(nrm2.x, 0.0, nrm2.y)
		verts += _quad_v(st, Vector3(a.x, y0, a.y), Vector3(b.x, y0, b.y),
			Vector3(b.x, y1, b.y), Vector3(a.x, y1, a.y), nrm3, col)
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


## Painted ground markings (parking stalls, crosswalks, stop bars, loading zones)
## batched into a single thin mesh per chunk — the compiled `ground_markings`
## stream: records of [x, z, heading_deg, length, kind]. A whole parking field of
## stall stripes therefore costs one MeshInstance, so lots read as laid-out parking
## instead of a blank polygon (P0-D5).
func _build_ground_markings(chunk: Dictionary, root: Node3D) -> int:
	var marks: Array = chunk.get("ground_markings", [])
	if marks.is_empty():
		return 0
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var verts := 0
	var y := 0.05                                  # just above the parking surface (0.02)
	for m in marks:
		if not (m is Array) or (m as Array).size() < 5:
			continue
		var x := float(m[0])
		var z := float(m[1])
		var heading := deg_to_rad(float(m[2]))
		var length := float(m[3])
		var kind := String(m[4])
		var width := 0.12
		var col := LANE_COL
		match kind:
			"crosswalk": width = 0.5
			"stop_bar": width = 0.4
			"accessible": width = 0.16; col = Color(0.52, 0.72, 0.95)
			"loading_zone": width = 0.16; col = Color(0.92, 0.80, 0.32)
			_: pass                                # parking_stall: thin off-white line
		var dir := Vector2(cos(heading), sin(heading))
		var nrm := Vector2(-dir.y, dir.x)
		var hl := length * 0.5
		var hw := width * 0.5
		var c := Vector2(x, z)
		var a0 := c - dir * hl - nrm * hw
		var a1 := c + dir * hl - nrm * hw
		var a2 := c + dir * hl + nrm * hw
		var a3 := c - dir * hl + nrm * hw
		st.set_color(col)
		for v in [Vector3(a0.x, y, a0.y), Vector3(a1.x, y, a1.y), Vector3(a2.x, y, a2.y),
				Vector3(a0.x, y, a0.y), Vector3(a2.x, y, a2.y), Vector3(a3.x, y, a3.y)]:
			st.set_normal(Vector3.UP)
			st.add_vertex(v)
		verts += 6
	if verts == 0:
		return 0
	var mesh := st.commit()
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.material_override = _shared_opaque_material()
	root.add_child(mi)
	return verts


func _dashed_line(st: SurfaceTool, pts_raw: Array, offset: float, width: float,
		dash_len: float, gap_len: float, y_level: float = 0.06) -> int:
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
			for v in [Vector3(p0.x, y_level, p0.y), Vector3(p1.x, y_level, p1.y), Vector3(p2.x, y_level, p2.y),
					Vector3(p0.x, y_level, p0.y), Vector3(p2.x, y_level, p2.y), Vector3(p3.x, y_level, p3.y)]:
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
		# Lane markings ON the deck surface (freeways read as freeways at iso scale):
		# a dashed centre line, plus lane divider lines across the carriageway.
		verts += _dashed_line(st, pts_raw, 0.0, 0.2, 3.0, 4.0, DECK_Y + 0.02)
		var lanes := int(r.get("lanes", 4))
		if lanes >= 4:
			var lane_w := deck_w / float(lanes)
			var li := 1
			while li < lanes:
				var off := -hw + lane_w * float(li)
				verts += _dashed_line(st, pts_raw, off, 0.15, 4.0, 6.0, DECK_Y + 0.02)
				li += 1
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
	# Decode the land-cover raster once (shared by fence-on-road culling and the
	# vegetation scatter below).
	var origin_arr: Array = chunk.get("origin", [0.0, 0.0])
	var origin := Vector2(float(origin_arr[0]), float(origin_arr[1]))
	var runs: Array = chunk.get("surface", [])
	var cells := _decode_rle(runs, CELLS * CELLS) if not runs.is_empty() else PackedByteArray()
	# Yard fences must stop at the property line, not march across the carriageway.
	var yard_fence := {"wood_fence": true, "chainlink_fence": true}
	var vehicle_kinds := {"sedan": true, "suv": true, "pickup": true, "van": true,
		"box_truck": true, "jeep": true, "sports_car": true,
		"semi_truck": true, "oil_tanker": true}
	# Kinds whose per-instance `variant` selects a distinct baked mesh (vehicle colour
	# or foliage colour), so they must be grouped by kind:variant.
	var variant_kinds := {"sedan": true, "suv": true, "pickup": true, "van": true,
		"box_truck": true, "jeep": true, "sports_car": true,
		"semi_truck": true, "oil_tanker": true,
		"tree_round": true, "tree_oak": true, "tree_conical": true,
		"tree_columnar": true, "tree_palm": true, "tree_willow": true, "bush_round": true, "bush_low": true,
		"tree_magnolia": true, "tree_crape_myrtle": true, "tree_baldcypress": true,
		"hedge": true, "flowering_shrub": true, "tall_grass": true, "native_scrub": true,
		"wood_fence": true}                        # fence STYLE rides in the baked variant
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
			# Drop yard fences that reach past the property line onto the sidewalk,
			# carriageway or parking apron — they should stop at the sidewalk edge.
			if yard_fence.has(kind):
				var sc := _surface_class(cells, origin, x, z)
				if sc == S_ROAD or sc == S_PARKING or sc == S_SIDEWALK:
					continue
			# Resolve the render variant via AssetCatalogV1. Vehicles/foliage carry a
			# baked data variant (colour); other families with >1 catalog variant get
			# a deterministic position-derived variant so repeated street props are
			# not identical placeholders. One MultiMesh per kind:variant preserves
			# batching.
			var rv := _render_variant_count(kind)
			if not variant_kinds.has(kind) and rv > 1:
				variant = _pos_variant(x, z) % rv
			var gkey := kind
			if variant_kinds.has(kind) or rv > 1:
				gkey = "%s:%d" % [kind, variant]
			if not groups.has(gkey):
				groups[gkey] = {"kind": kind, "variant": variant, "xforms": []}
			# The compiler's heading is +Z-forward (atan2(dx,dz)); every directional
			# prop mesh (vehicles, fences, guardrails, benches) is built with its
			# length on +X, so correct by -90 deg. Radial props (bins/poles/trees)
			# are unaffected by the extra yaw.
			var basis := Basis(Vector3.UP, deg_to_rad(rot) - PI * 0.5)
			# Grammar-placed trees also get per-species age/proportion variation so
			# they match the scattered ones (bushes/props unaffected).
			if kind.begins_with("tree_"):
				var tsh := _stable_hash(int(round(x * 4.0)), int(round(z * 4.0)))
				basis = basis.scaled(_tree_scale(kind, 1.0, tsh))
			(groups[gkey]["xforms"] as Array).append(Transform3D(basis, Vector3(x, 0.0, z)))
			total += 1

	# Presentation-only vegetation scatter driven by the chunk's land-cover raster:
	# trees on canopy cells, bushes on rough vegetation, occasional lawn trees. This
	# fills the world with greenery without any tile authority — positions are
	# continuous (cell centre + deterministic jitter) and resolve back to metres.
	_scatter_vegetation(chunk, groups, cells, origin)

	var shadow_kinds := {"sedan": true, "suv": true, "pickup": true, "van": true,
		"box_truck": true, "jeep": true, "sports_car": true,
		"semi_truck": true, "oil_tanker": true,
		"tree_round": true, "tree_oak": true, "tree_conical": true,
		"tree_columnar": true, "tree_palm": true, "tree_willow": true,
		"tree_magnolia": true, "tree_crape_myrtle": true, "tree_baldcypress": true}
	var mm_count := 0
	for gkey in groups.keys():
		var g: Dictionary = groups[gkey]
		var xforms: Array = g["xforms"]
		if xforms.is_empty():
			continue
		var kind_s := String(g["kind"])
		var mmi := PropMeshes.make_multimesh(kind_s, xforms, int(g["variant"]),
			shadow_kinds.has(kind_s))
		root.add_child(mmi)
		mm_count += xforms.size()

	return {"quads": 0, "verts": 0, "buildings": 0, "mm_instances": mm_count, "collisions": 0}


func _surface_class(cells: PackedByteArray, origin: Vector2, wx: float, wz: float) -> int:
	## Land-cover class at a continuous world position (or -1 out of chunk / no raster).
	if cells.is_empty():
		return -1
	var col := int((wx - origin.x) / CELL_M)
	var row := int((wz - origin.y) / CELL_M)
	if col < 0 or col >= CELLS or row < 0 or row >= CELLS:
		return -1
	return cells[row * CELLS + col]


func _near_building(cells: PackedByteArray, row: int, col: int, radius: int) -> bool:
	## True if any raster cell within `radius` cells of (row,col) is a building —
	## used to keep tree canopies from overhanging/clipping into walls.
	for dr in range(-radius, radius + 1):
		var rr := row + dr
		if rr < 0 or rr >= CELLS:
			continue
		for dc in range(-radius, radius + 1):
			var cc := col + dc
			if cc < 0 or cc >= CELLS:
				continue
			if cells[rr * CELLS + cc] == S_BUILDING:
				return true
	return false


func _scatter_vegetation(chunk: Dictionary, groups: Dictionary,
		cells: PackedByteArray, origin: Vector2) -> void:
	if cells.is_empty():
		return
	var cx := int(chunk.get("cx", 0))
	var cz := int(chunk.get("cz", 0))
	# Deterministic per-cell placement so reloads don't flicker. One candidate per
	# STEP*STEP block of cells keeps density sane (STEP*CELL_M metres apart).
	# Species mix is conditioned on the geographic biome (region) + land cover, so
	# a Gulf city favours live oak / magnolia / palm / bald cypress while a
	# temperate one favours pines / elms — driven by geography, never city name.
	var veg := _region_veg(_veg_region)
	var canopy: Array = veg["canopy"]
	var lawn: Array = veg["lawn"]
	var rough: Array = veg["rough"]
	var STEP := 3
	for row in range(0, CELLS, STEP):
		for col in range(0, CELLS, STEP):
			var t := cells[row * CELLS + col]
			var hsh := _stable_hash(cx * 131071 + row, cz * 8191 + col)
			var kind := ""
			# `base` is a gentle ≤1.0 cover trim (canopy = full mature stature, yard/
			# rough a touch smaller). It is NOT a size multiplier — overall size comes
			# from the age tier in _tree_scale, which caps at ~1.25×. Cover chiefly
			# controls density (the modulo gates below) and species mix.
			var base := 1.0
			if t == S_TREE_CANOPY:
				kind = canopy[hsh % canopy.size()]
				base = 1.0
			elif t == S_ROUGH_VEGETATION:
				if (hsh % 3) != 0:
					continue
				kind = rough[hsh % rough.size()]
				base = 0.8
			elif t == S_MAINTAINED_GRASS:
				if (hsh % 6) != 0:
					continue                            # sparse lawn/yard trees
				kind = lawn[hsh % lawn.size()]
				base = 0.9
			else:
				continue
			var variant := (hsh >> 3) % 5
			# continuous jitter within the block, deterministic (kept modest so trees
			# don't wander out of their vegetation cell into a road or building).
			var jx := (float(hsh % 1000) / 1000.0 - 0.5) * CELL_M * float(STEP - 1)
			var jz := (float((hsh >> 10) % 1000) / 1000.0 - 0.5) * CELL_M * float(STEP - 1)
			var wx := origin.x + (float(col) + 0.5) * CELL_M + jx
			var wz := origin.y + (float(row) + 0.5) * CELL_M + jz
			var fcol := int((wx - origin.x) / CELL_M)
			var frow := int((wz - origin.y) / CELL_M)
			if fcol < 0 or fcol >= CELLS or frow < 0 or frow >= CELLS:
				continue
			# Hard final-surface rejection: after jitter the candidate may have moved
			# off its vegetation cell. Vegetation must never land on pavement, water or
			# a building footprint (the earlier comment claimed this but the check was
			# missing — trees could end up standing in a road or on a roof).
			var fclass := int(cells[frow * CELLS + fcol])
			if fclass == S_ROAD or fclass == S_SIDEWALK or fclass == S_PARKING \
					or fclass == S_BUILDING or fclass == S_WATER:
				continue
			var is_tree := kind.begins_with("tree_")
			var yaw := float(hsh % 360)
			var scl := _tree_scale(kind, base, hsh)
			# Building clearance scales with the actual crown radius so a broad live
			# oak stays further from walls than a slim cypress, instead of a fixed
			# two-cell check for every species.
			var clearance := 1
			if is_tree:
				var crown_r := _crown_radius_m(kind) * maxf(scl.x, scl.z)
				clearance = clampi(int(ceil(crown_r / CELL_M)), 1, 3)
			if _near_building(cells, frow, fcol, clearance):
				continue
			var gkey := "%s:%d" % [kind, variant]
			if not groups.has(gkey):
				groups[gkey] = {"kind": kind, "variant": variant, "xforms": []}
			var basis := Basis(Vector3.UP, deg_to_rad(yaw)).scaled(scl)
			(groups[gkey]["xforms"] as Array).append(Transform3D(basis, Vector3(wx, 0.0, wz)))


## Region-conditioned vegetation palettes (weighted by repetition). Keys:
## canopy (tree-canopy cells), lawn (maintained grass), rough (rough vegetation /
## ground cover). Species are the geographic mix for the biome; every kind is a
## real PropMeshes builder.
func _region_veg(region: String) -> Dictionary:
	match region:
		"gulf":
			return {
				"canopy": ["tree_oak", "tree_oak", "tree_magnolia", "tree_magnolia",
					"tree_round", "tree_palm", "tree_palm", "tree_baldcypress",
					"tree_willow"],
				"lawn": ["tree_oak", "tree_crape_myrtle", "tree_crape_myrtle",
					"tree_palm", "tree_round", "tree_magnolia"],
				"rough": ["bush_round", "bush_low", "native_scrub", "tall_grass",
					"flowering_shrub", "hedge"],
			}
		"subtropical":
			return {
				"canopy": ["tree_oak", "tree_oak", "tree_round", "tree_round",
					"tree_magnolia", "tree_conical", "tree_crape_myrtle", "tree_palm"],
				"lawn": ["tree_oak", "tree_crape_myrtle", "tree_round",
					"tree_columnar", "tree_magnolia"],
				"rough": ["bush_round", "bush_low", "native_scrub", "tall_grass",
					"flowering_shrub", "hedge"],
			}
		"arid":
			return {
				"canopy": ["tree_round", "tree_conical", "tree_columnar",
					"tree_crape_myrtle", "native_scrub"],
				"lawn": ["tree_crape_myrtle", "tree_round", "tree_columnar"],
				"rough": ["native_scrub", "native_scrub", "tall_grass", "bush_low"],
			}
		"boreal":
			return {
				"canopy": ["tree_conical", "tree_conical", "tree_conical",
					"tree_columnar", "tree_round"],
				"lawn": ["tree_conical", "tree_columnar", "tree_round"],
				"rough": ["bush_round", "bush_low", "native_scrub", "tall_grass"],
			}
		_:  # temperate
			return {
				"canopy": ["tree_round", "tree_round", "tree_conical", "tree_conical",
					"tree_oak", "tree_columnar", "tree_willow"],
				"lawn": ["tree_round", "tree_conical", "tree_columnar",
					"tree_crape_myrtle"],
				"rough": ["bush_round", "bush_low", "hedge", "flowering_shrub",
					"tall_grass"],
			}


## Tree scale = age-tier size × per-species proportion, with `base` a gentle ≤1.0
## cover trim (never an inflator). The prop meshes are authored at *mature*
## dimensions (a live-oak crown is already ~5.4 m across at scale 1.0), so the age
## tier is the ONLY overall-size multiplier — the old model compounded a cover
## scale (up to 2.2) × age × species and produced ~3.4× house-sized canopies.
## The tier ranges below already carry the ±10–15% individual variance the design
## calls for. Bushes/shrubs stay near-uniform. `hsh` is the placement's stable hash.
func _tree_scale(kind: String, base: float, hsh: int) -> Vector3:
	if not kind.begins_with("tree_"):
		var bv := 0.9 + float(hsh % 100) / 100.0 * 0.2   # 0.90–1.10, near-uniform
		return Vector3(base * bv, base * bv, base * bv)
	var age := float((hsh >> 12) % 1000) / 1000.0
	var t := float((hsh >> 22) % 1000) / 1000.0          # within-tier interpolation
	var sz := 1.0                                        # overall size factor
	if age < 0.16:
		sz = lerpf(0.35, 0.50, t)    # sapling
	elif age < 0.44:
		sz = lerpf(0.60, 0.80, t)    # young
	elif age < 0.82:
		sz = lerpf(0.90, 1.10, t)    # mature
	else:
		sz = lerpf(1.10, 1.25, t)    # old (capped — never overwhelms a house lot)
	var spw := 1.0   # species width bias
	var sph := 1.0   # species height bias
	match kind:
		"tree_conical": spw = 0.90; sph = 1.18       # loblolly pine: tall
		"tree_columnar": spw = 0.72; sph = 1.24      # cypress/poplar: slim spire
		"tree_oak": spw = 1.24; sph = 0.90           # live oak: broad, low
		"tree_willow": spw = 1.06; sph = 1.02        # willow: full rounded
		"tree_palm": spw = 0.95; sph = 1.12          # palm: tall trunk
		"tree_magnolia": spw = 1.08; sph = 0.96      # magnolia: dense, low
		"tree_baldcypress": spw = 0.82; sph = 1.20   # bald cypress: tall, narrow
		"tree_crape_myrtle": spw = 0.9; sph = 0.85   # crape myrtle: small ornamental
		_: pass                                      # tree_round: balanced
	return Vector3(base * sz * spw, base * sz * sph, base * sz * spw)


## Approximate mature crown radius (metres, at scale 1.0) per species, taken from
## the authored prop-mesh half-widths. Used to size building clearance so a broad
## live oak keeps further from walls than a slim columnar cypress.
func _crown_radius_m(kind: String) -> float:
	match kind:
		"tree_oak": return 2.7
		"tree_round": return 1.6
		"tree_willow": return 1.9
		"tree_magnolia": return 1.7
		"tree_conical": return 2.3
		"tree_baldcypress": return 2.0
		"tree_columnar": return 0.95
		"tree_palm": return 2.6
		"tree_crape_myrtle": return 1.0
		_: return 1.5


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
