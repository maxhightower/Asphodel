extends Node3D

## Site-detail layer — the procedural "stuff between the buildings" that turns a
## grid of masses into a lived-in city: parking lots, scattered trees and bushes,
## fences along property lines, and ground-cover patches that break up the flat
## terrain. Pure presentation (like the capsule crowd and the traffic): it never
## feeds the authoritative Python simulation.
##
## Everything is placed against a coarse OCCUPANCY GRID rasterised from the real
## building footprints and road corridors, so props land in genuine open space —
## never inside a wall or on a street. Deterministic from `seed`, batched into a
## few MultiMeshes / ArrayMeshes so thousands of props cost a handful of draws.

const FREE := 0
const BUILDING := 1
const ROAD := 2
const USED := 3            # claimed by a parking lot / fence footprint

# Prop budgets (city-wide caps so a huge bundle stays cheap). Candidates are
# collected across the WHOLE map by probability, then stride-thinned down to these
# caps, so props stay evenly spread instead of piling up wherever the scan starts.
const MAX_TREES := 8000
const MAX_BUSHES := 7000
const MAX_PATCHES := 8000
const MAX_LOTS := 400
# Per-free-cell placement probabilities (before thinning).
const P_TREE := 0.06
const P_BUSH := 0.05
const P_PATCH := 0.09
const P_LOT := 0.5

var _rng := RandomNumberGenerator.new()
var _cols := 0
var _rows := 0
var _ox := 0.0
var _oz := 0.0
var _cell := 6.0
var _occ: PackedByteArray = PackedByteArray()


func build(bounds: Rect2, footprints: Array, roads: Dictionary, seed: int) -> void:
	_rng.seed = seed
	_init_grid(bounds)
	_mark_buildings(footprints)
	_mark_roads(roads)
	_build_parking_lots()
	_build_greenery()
	_build_fences()
	_build_ground_patches()


# --------------------------------------------------------------- occupancy grid
func _init_grid(b: Rect2) -> void:
	_ox = b.position.x
	_oz = b.position.y
	# Adaptive cell size: keep the grid under ~1.2M cells however big the city is.
	_cell = 6.0
	while (b.size.x / _cell + 1.0) * (b.size.y / _cell + 1.0) > 1_200_000.0:
		_cell *= 1.5
	_cols = int(ceil(b.size.x / _cell)) + 1
	_rows = int(ceil(b.size.y / _cell)) + 1
	_occ = PackedByteArray()
	_occ.resize(_cols * _rows)          # zero-filled == FREE


func _in(cx: int, cz: int) -> bool:
	return cx >= 0 and cx < _cols and cz >= 0 and cz < _rows


func _occ_get(cx: int, cz: int) -> int:
	if not _in(cx, cz):
		return BUILDING                 # off-map reads as blocked
	return _occ[cz * _cols + cx]


func _occ_set(cx: int, cz: int, v: int) -> void:
	if _in(cx, cz):
		_occ[cz * _cols + cx] = v


func _cx_of(x: float) -> int:
	return int(floor((x - _ox) / _cell))


func _cz_of(z: float) -> int:
	return int(floor((z - _oz) / _cell))


func _cell_centre(cx: int, cz: int) -> Vector2:
	return Vector2(_ox + (float(cx) + 0.5) * _cell, _oz + (float(cz) + 0.5) * _cell)


func _mark_buildings(footprints: Array) -> void:
	for b in footprints:
		var poly: Array = b.get("poly", [])
		if poly.size() < 3:
			continue
		var min_x := INF; var min_z := INF; var max_x := -INF; var max_z := -INF
		for p in poly:
			min_x = minf(min_x, float(p[0])); max_x = maxf(max_x, float(p[0]))
			min_z = minf(min_z, float(p[1])); max_z = maxf(max_z, float(p[1]))
		# Mark the footprint AABB plus a one-cell skirt (no props hard against walls).
		var c0x := _cx_of(min_x) - 1; var c1x := _cx_of(max_x) + 1
		var c0z := _cz_of(min_z) - 1; var c1z := _cz_of(max_z) + 1
		for cz in range(c0z, c1z + 1):
			for cx in range(c0x, c1x + 1):
				_occ_set(cx, cz, BUILDING)


func _mark_roads(roads: Dictionary) -> void:
	for pl in roads.get("polylines", []):
		var pts: Array = pl.get("points", [])
		if pts.size() < 2:
			continue
		var cls := String(pl.get("class", ""))
		# Corridor half-width mirrors street_world's roadway+sidewalk extents.
		var half := 10.0
		if cls == "primary":
			half = 11.0
		elif cls == "motorway" or cls == "trunk":
			half = 11.0
		else:
			half = 8.0
		for k in range(pts.size() - 1):
			var a := Vector2(float(pts[k][0]), float(pts[k][1]))
			var b := Vector2(float(pts[k + 1][0]), float(pts[k + 1][1]))
			_stamp_segment(a, b, half)


func _stamp_segment(a: Vector2, b: Vector2, half: float) -> void:
	# Mark every cell within `half` of the segment as ROAD (walk it in ~cell steps
	# and stamp a small disk at each sample).
	var seglen := a.distance_to(b)
	var steps := maxi(1, int(ceil(seglen / _cell)))
	var rad := int(ceil(half / _cell))
	for s in range(steps + 1):
		var p := a.lerp(b, float(s) / float(steps))
		var bx := _cx_of(p.x); var bz := _cz_of(p.y)
		for dz in range(-rad, rad + 1):
			for dx in range(-rad, rad + 1):
				if _occ_get(bx + dx, bz + dz) == FREE:
					_occ_set(bx + dx, bz + dz, ROAD)


# ------------------------------------------------------------------ parking lots
func _build_parking_lots() -> void:
	# Find rectangular runs of FREE cells adjacent to a road and pave them: dark
	# asphalt slab, white stall stripes, and a wheel-stop kerb. One batched mesh.
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var lots := 0
	# Lot footprint in cells (roughly 7x5 cells -> ~40x30 m).
	var lw := 7
	var lh := 5
	# Scan the WHOLE map (so lots spread everywhere), paving a probabilistic subset
	# of the valid road-adjacent openings up to the cap.
	var cz := 1
	while cz < _rows - lh and lots < MAX_LOTS:
		var cx := 1
		while cx < _cols - lw and lots < MAX_LOTS:
			if _rect_free(cx, cz, lw, lh) and _touches_road(cx, cz, lw, lh):
				if _rng.randf() < P_LOT:
					_pave_lot(st, cx, cz, lw, lh)
					for z2 in range(cz, cz + lh):
						for x2 in range(cx, cx + lw):
							_occ_set(x2, z2, USED)
					lots += 1
				cx += lw
			else:
				cx += 2
		cz += 3
	if lots == 0:
		return
	var mat := StandardMaterial3D.new()
	mat.vertex_color_use_as_albedo = true
	mat.roughness = 0.95
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	var mi := MeshInstance3D.new()
	mi.mesh = st.commit()
	mi.material_override = mat
	add_child(mi)


func _rect_free(cx: int, cz: int, w: int, h: int) -> bool:
	for z2 in range(cz, cz + h):
		for x2 in range(cx, cx + w):
			if _occ_get(x2, z2) != FREE:
				return false
	return true


func _touches_road(cx: int, cz: int, w: int, h: int) -> bool:
	# A parking lot must border a street (its entrance). Scan the ring around it.
	for x2 in range(cx - 1, cx + w + 1):
		if _occ_get(x2, cz - 1) == ROAD or _occ_get(x2, cz + h) == ROAD:
			return true
	for z2 in range(cz - 1, cz + h + 1):
		if _occ_get(cx - 1, z2) == ROAD or _occ_get(cx + w, z2) == ROAD:
			return true
	return false


const LOT_ASPHALT := Color(0.16, 0.16, 0.18)
const LOT_STRIPE := Color(0.85, 0.85, 0.72)
const LOT_KERB := Color(0.55, 0.55, 0.53)
const LOT_Y := 0.06


func _pave_lot(st: SurfaceTool, cx: int, cz: int, w: int, h: int) -> void:
	var a := _cell_centre(cx, cz) - Vector2(_cell * 0.5, _cell * 0.5)
	var x0 := a.x
	var z0 := a.y
	var x1 := x0 + float(w) * _cell
	var z1 := z0 + float(h) * _cell
	# Asphalt pad.
	st.set_color(LOT_ASPHALT)
	_flat_quad(st, Vector2(x0, z0), Vector2(x1, z0), Vector2(x1, z1), Vector2(x0, z1), LOT_Y)
	# Perimeter wheel-stop kerb (a thin raised lip).
	st.set_color(LOT_KERB)
	var t := 0.4
	_flat_ring(st, x0, z0, x1, z1, t, LOT_Y + 0.12)
	# Parking-stall stripes: rows of short white lines, cars nose-to-nose down the
	# middle. Stalls run along X, split by a central drive aisle.
	st.set_color(LOT_STRIPE)
	var stall := 2.6
	var mid := (z0 + z1) * 0.5
	var depth := 5.0
	var x := x0 + 0.6
	while x < x1 - 0.4:
		_stripe(st, Vector2(x, mid - depth), Vector2(x, mid - 0.6), 0.15, LOT_Y + 0.02)
		_stripe(st, Vector2(x, mid + 0.6), Vector2(x, mid + depth), 0.15, LOT_Y + 0.02)
		x += stall


func _flat_ring(st: SurfaceTool, x0: float, z0: float, x1: float, z1: float,
		t: float, y: float) -> void:
	_flat_quad(st, Vector2(x0, z0), Vector2(x1, z0), Vector2(x1, z0 + t), Vector2(x0, z0 + t), y)
	_flat_quad(st, Vector2(x0, z1 - t), Vector2(x1, z1 - t), Vector2(x1, z1), Vector2(x0, z1), y)
	_flat_quad(st, Vector2(x0, z0), Vector2(x0 + t, z0), Vector2(x0 + t, z1), Vector2(x0, z1), y)
	_flat_quad(st, Vector2(x1 - t, z0), Vector2(x1, z0), Vector2(x1, z1), Vector2(x1 - t, z1), y)


func _stripe(st: SurfaceTool, a: Vector2, b: Vector2, w: float, y: float) -> void:
	var d := b - a
	if d.length() < 0.001:
		return
	var n := d.orthogonal().normalized() * (w * 0.5)
	_flat_quad(st, a - n, b - n, b + n, a + n, y)


func _flat_quad(st: SurfaceTool, p0: Vector2, p1: Vector2, p2: Vector2, p3: Vector2, y: float) -> void:
	for v in [p0, p1, p2, p0, p2, p3]:
		st.set_normal(Vector3.UP)
		st.add_vertex(Vector3(v.x, y, v.y))


# --------------------------------------------------------------------- greenery
func _build_greenery() -> void:
	# Trees + bushes scattered in FREE cells. Trees carry baked vertex colours
	# (brown trunk + green crown) so ONE MultiMesh draws the lot; a few crown
	# tints add variety. Bushes are a second, smaller MultiMesh.
	var tree_slots: Array[Vector2] = []
	var bush_slots: Array[Vector2] = []
	# Collect candidates across the WHOLE map by probability (even spread), jittered
	# off the cell centre so they don't sit on an obvious grid.
	for cz in range(0, _rows):
		for cx in range(0, _cols):
			if _occ_get(cx, cz) != FREE:
				continue
			var r := _rng.randf()
			if r < P_TREE:
				var c := _cell_centre(cx, cz)
				c += Vector2(_rng.randf() - 0.5, _rng.randf() - 0.5) * (_cell * 0.7)
				tree_slots.append(c)
			elif r < P_TREE + P_BUSH:
				var c2 := _cell_centre(cx, cz)
				c2 += Vector2(_rng.randf() - 0.5, _rng.randf() - 0.5) * (_cell * 0.8)
				bush_slots.append(c2)
	tree_slots = _thin(tree_slots, MAX_TREES)
	bush_slots = _thin(bush_slots, MAX_BUSHES)
	if not tree_slots.is_empty():
		_scatter(_tree_mesh(), tree_slots, 0.75, 1.5, true)
	if not bush_slots.is_empty():
		_scatter(_bush_mesh(), bush_slots, 0.7, 1.4, false)


func _thin(slots: Array[Vector2], cap: int) -> Array[Vector2]:
	# Keep at most `cap` evenly spaced entries (uniform stride preserves the spatial
	# spread; a plain truncation would keep only one corner of the map).
	if slots.size() <= cap:
		return slots
	var stride := int(ceil(float(slots.size()) / float(cap)))
	var out: Array[Vector2] = []
	var i := 0
	while i < slots.size():
		out.append(slots[i])
		i += stride
	return out


func _scatter(mesh: Mesh, slots: Array[Vector2], smin: float, smax: float,
		tall: bool) -> void:
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.mesh = mesh
	mm.instance_count = slots.size()
	for i in range(slots.size()):
		var s := smin + (smax - smin) * _rng.randf()
		var yaw := _rng.randf() * TAU
		var basis := Basis(Vector3.UP, yaw).scaled(Vector3(s, s * (1.0 if tall else 0.85), s))
		var p: Vector2 = slots[i]
		mm.set_instance_transform(i, Transform3D(basis, Vector3(p.x, 0.0, p.y)))
	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	add_child(mmi)


func _tree_mesh() -> Mesh:
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	_box(st, Vector3(0, 1.1, 0), Vector3(0.35, 2.2, 0.35), Color(0.34, 0.24, 0.16))
	# Two stacked crowns for a rounder canopy.
	_octa(st, Vector3(0, 3.3, 0), 1.7, 1.9, Color(0.24, 0.44, 0.22))
	_octa(st, Vector3(0, 4.4, 0), 1.15, 1.5, Color(0.28, 0.5, 0.26))
	var m := StandardMaterial3D.new()
	m.vertex_color_use_as_albedo = true
	m.roughness = 0.9
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	var mesh := st.commit()
	mesh.surface_set_material(0, m)
	return mesh


func _bush_mesh() -> Mesh:
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	_octa(st, Vector3(0, 0.5, 0), 0.9, 0.9, Color(0.26, 0.42, 0.22))
	var m := StandardMaterial3D.new()
	m.vertex_color_use_as_albedo = true
	m.roughness = 0.95
	m.cull_mode = BaseMaterial3D.CULL_DISABLED
	var mesh := st.commit()
	mesh.surface_set_material(0, m)
	return mesh


func _box(st: SurfaceTool, c: Vector3, size: Vector3, col: Color) -> void:
	st.set_color(col)
	var h := size * 0.5
	var corners := [
		c + Vector3(-h.x, -h.y, -h.z), c + Vector3(h.x, -h.y, -h.z),
		c + Vector3(h.x, -h.y, h.z), c + Vector3(-h.x, -h.y, h.z),
		c + Vector3(-h.x, h.y, -h.z), c + Vector3(h.x, h.y, -h.z),
		c + Vector3(h.x, h.y, h.z), c + Vector3(-h.x, h.y, h.z)]
	var faces := [[0, 1, 2, 3], [7, 6, 5, 4], [4, 5, 1, 0],
		[6, 7, 3, 2], [5, 6, 2, 1], [7, 4, 0, 3]]
	var nrms := [Vector3.DOWN, Vector3.UP, Vector3.FORWARD,
		Vector3.BACK, Vector3.RIGHT, Vector3.LEFT]
	for fi in range(faces.size()):
		var f: Array = faces[fi]
		var nrm: Vector3 = nrms[fi]
		for k in [f[0], f[1], f[2], f[0], f[2], f[3]]:
			st.set_normal(nrm)
			st.add_vertex(corners[k])


func _octa(st: SurfaceTool, c: Vector3, r: float, up: float, col: Color) -> void:
	# A squashed octahedron crown: a top apex, a shallow bottom apex, and a
	# 4-vertex equator, 8 triangles.
	st.set_color(col)
	var top := c + Vector3(0, up, 0)
	var bot := c + Vector3(0, -up * 0.5, 0)
	var mid := [c + Vector3(r, 0, 0), c + Vector3(0, 0, r),
		c + Vector3(-r, 0, 0), c + Vector3(0, 0, -r)]
	for i in range(4):
		var a: Vector3 = mid[i]
		var b: Vector3 = mid[(i + 1) % 4]
		_ntri(st, top, a, b)
		_ntri(st, bot, b, a)


func _ntri(st: SurfaceTool, p0: Vector3, p1: Vector3, p2: Vector3) -> void:
	var nrm := (p1 - p0).cross(p2 - p0).normalized()
	for v in [p0, p1, p2]:
		st.set_normal(nrm)
		st.add_vertex(v)


# ------------------------------------------------------------------------ fences
const FENCE_COL := Color(0.5, 0.44, 0.36)
const FENCE_H := 1.1


func _build_fences() -> void:
	# Run a low fence along the boundary between open yard cells and building
	# cells: a FREE cell that sits directly beside a BUILDING cell gets a fence
	# panel on that shared edge, reading as a property line. Batched into one mesh.
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var panels := 0
	var cap := 9000
	for cz in range(0, _rows):
		for cx in range(0, _cols):
			if _occ_get(cx, cz) != FREE:
				continue
			if _rng.randf() > 0.35:
				continue                # only some parcels are fenced
			# Check the 4 orthogonal neighbours; fence the edge facing a building.
			if _occ_get(cx + 1, cz) == BUILDING:
				_fence_edge(st, cx, cz, Vector2(1, 0))
				panels += 1
			elif _occ_get(cx, cz + 1) == BUILDING:
				_fence_edge(st, cx, cz, Vector2(0, 1))
				panels += 1
			if panels >= cap:
				break
		if panels >= cap:
			break
	if panels == 0:
		return
	var mat := StandardMaterial3D.new()
	mat.vertex_color_use_as_albedo = true
	mat.roughness = 0.9
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	var mi := MeshInstance3D.new()
	mi.mesh = st.commit()
	mi.material_override = mat
	add_child(mi)


func _fence_edge(st: SurfaceTool, cx: int, cz: int, dir: Vector2) -> void:
	# A thin vertical panel along the cell edge in `dir` (a unit +x or +z step).
	var c := _cell_centre(cx, cz)
	var half := _cell * 0.5
	var along := Vector2(dir.y, dir.x)         # perpendicular to dir = edge run
	var edge := c + dir * half
	var a := edge - along * half
	var b := edge + along * half
	st.set_color(FENCE_COL)
	var y0 := 0.0
	var y1 := FENCE_H
	var nrm := Vector3(dir.x, 0, dir.y)
	# Two-sided panel (cull disabled), a single quad.
	var pa0 := Vector3(a.x, y0, a.y)
	var pb0 := Vector3(b.x, y0, b.y)
	var pb1 := Vector3(b.x, y1, b.y)
	var pa1 := Vector3(a.x, y1, a.y)
	for v in [pa0, pb0, pb1, pa0, pb1, pa1]:
		st.set_normal(nrm)
		st.add_vertex(v)


# ----------------------------------------------------------------- ground patches
func _build_ground_patches() -> void:
	# Flat colour patches (dirt, dry grass, darker turf) scattered in open cells so
	# the terrain isn't a single uniform green. One MultiMesh of a flat quad, tinted
	# per instance.
	var slots: Array[Vector2] = []
	for cz in range(0, _rows):
		for cx in range(0, _cols):
			if _occ_get(cx, cz) != FREE:
				continue
			if _rng.randf() < P_PATCH:
				slots.append(_cell_centre(cx, cz))
	slots = _thin(slots, MAX_PATCHES)
	if slots.is_empty():
		return
	var quad := PlaneMesh.new()
	quad.size = Vector2(_cell * 1.3, _cell * 1.3)
	var mat := StandardMaterial3D.new()
	mat.vertex_color_use_as_albedo = true
	mat.roughness = 1.0
	quad.material = mat
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.use_colors = true
	mm.mesh = quad
	mm.instance_count = slots.size()
	var palette := [Color(0.30, 0.28, 0.20), Color(0.34, 0.36, 0.24),
		Color(0.20, 0.26, 0.18), Color(0.38, 0.36, 0.28)]
	for i in range(slots.size()):
		var p: Vector2 = slots[i]
		var s := 0.7 + 0.7 * _rng.randf()
		var yaw := _rng.randf() * TAU
		var basis := Basis(Vector3.UP, yaw).scaled(Vector3(s, 1.0, s))
		# Float a hair above the ground plane (y=0) to avoid z-fighting.
		mm.set_instance_transform(i, Transform3D(basis, Vector3(p.x, 0.03, p.y)))
		mm.set_instance_color(i, palette[_rng.randi() % palette.size()])
	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	add_child(mmi)
