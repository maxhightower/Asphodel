class_name PropMeshes
extends RefCounted

## Low-poly procedural prop mesh library — mailboxes, bins, poles, vehicles,
## trees and the like. Every mesh is built once with SurfaceTool, cached by
## "kind:variant", and shared across every MultiMesh/MeshInstance3D that wants
## it. Purely a geometry factory: it never adds itself to a scene tree (that's
## `make_multimesh`'s job, or the caller wiring up a MeshInstance3D directly).
##
## Conventions:
##   - Origin is at ground centre: y = 0 sits on the ground plane, +Z is the
##     prop's "forward" (a car's nose, a sign's face, etc.).
##   - All colour comes from per-vertex colour (st.set_color) + a shared
##     StandardMaterial3D with vertex_color_use_as_albedo — no textures.
##   - Normals are always computed with SurfaceTool.generate_normals() at the
##     end of a build, never set by hand, so every helper only has to get
##     vertex WINDING right (see _box/_cylinder/_cone below).
##   - Materials use CULL_DISABLED (matches site_detail.gd / street_world.gd)
##     so a stray reversed face still renders instead of vanishing.


# ------------------------------------------------------------------- caching
static var _mesh_cache: Dictionary = {}    # "kind:variant" -> ArrayMesh
static var _mat_opaque: StandardMaterial3D = null
static var _mat_glass: StandardMaterial3D = null


static func _opaque_material() -> StandardMaterial3D:
	if _mat_opaque == null:
		_mat_opaque = StandardMaterial3D.new()
		_mat_opaque.vertex_color_use_as_albedo = true
		_mat_opaque.roughness = 0.9
		_mat_opaque.cull_mode = BaseMaterial3D.CULL_DISABLED
	return _mat_opaque


static var _mat_vehicle: StandardMaterial3D = null


static func _vehicle_material() -> StandardMaterial3D:
	# Matte stylized car paint: no metallic, high roughness — the old glossy/metallic
	# finish put a blown-out specular hotspot on every roof. A low specular keeps a
	# faint satin sheen without the plastic shine. Back-face culled (vehicle meshes
	# are closed + correctly wound) so interior faces don't wash out the shading.
	if _mat_vehicle == null:
		_mat_vehicle = StandardMaterial3D.new()
		_mat_vehicle.vertex_color_use_as_albedo = true
		_mat_vehicle.roughness = 0.7
		_mat_vehicle.metallic = 0.0
		_mat_vehicle.metallic_specular = 0.2
		# Double-sided: the bodies are built from many boxes, round wheels and glass
		# panels, so a stray interior/back face never punches a hole.
		_mat_vehicle.cull_mode = BaseMaterial3D.CULL_DISABLED
	return _mat_vehicle


static func _glass_material() -> StandardMaterial3D:
	# Shared semi-transparent material for the chainlink-fence mesh panel.
	if _mat_glass == null:
		_mat_glass = StandardMaterial3D.new()
		_mat_glass.vertex_color_use_as_albedo = true
		_mat_glass.roughness = 0.9
		_mat_glass.cull_mode = BaseMaterial3D.CULL_DISABLED
		_mat_glass.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		_mat_glass.albedo_color = Color(1.0, 1.0, 1.0, 0.35)
	return _mat_glass


## Every kind `_build` has an explicit case for. Anything outside this set draws
## the magenta unknown-asset box, so the catalog-conformance gate asserts every
## placed/catalogued render kind is in here (no silent magenta in the field).
const SUPPORTED_KINDS := [
	"mailbox", "garbage_bin", "recycling_bin", "fire_hydrant", "utility_pole",
	"streetlight", "traffic_sign", "traffic_signal", "guardrail", "bollard",
	"transformer_box", "utility_cabinet", "ac_condenser", "rooftop_hvac",
	"dumpster", "parking_stop", "bench", "bus_shelter", "wood_fence",
	"chainlink_fence", "pallet", "road_barrier",
	"sedan", "suv", "pickup", "van", "box_truck", "jeep", "sports_car",
	"semi_truck", "oil_tanker",
	"tree_round", "tree_oak", "tree_conical", "tree_columnar", "tree_palm",
	"tree_willow", "bush_round", "bush_low",
	"tree_magnolia", "tree_crape_myrtle", "tree_baldcypress",
	"hedge", "flowering_shrub", "tall_grass", "native_scrub",
]


static func is_supported(kind: String) -> bool:
	return kind in SUPPORTED_KINDS


## Returns a cached ArrayMesh for `kind` (see the match in `_build` for the
## full list of supported kinds). `variant` selects a distinct baked mesh for
## vehicles, foliage, and the street families that expose variants; other kinds
## ignore it but it still participates in the cache key.
static func get_mesh(kind: String, variant: int = 0) -> Mesh:
	var key := "%s:%d" % [kind, variant]
	if _mesh_cache.has(key):
		return _mesh_cache[key]
	var mesh := _build(kind, variant)
	_mesh_cache[key] = mesh
	return mesh


## Builds a MultiMeshInstance3D drawing `kind` at every Transform3D in
## `transforms`, in one draw call. Shadows are off (small/cheap props).
static func make_multimesh(kind: String, transforms: Array, variant: int = 0,
		cast_shadow: bool = false) -> MultiMeshInstance3D:
	var mesh := get_mesh(kind, variant)
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.mesh = mesh
	mm.instance_count = transforms.size()
	for i in range(transforms.size()):
		mm.set_instance_transform(i, transforms[i])
	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	mmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_ON if cast_shadow \
		else GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	return mmi


# ------------------------------------------------------------------ dispatch
static func _build(kind: String, variant: int) -> ArrayMesh:
	if kind == "chainlink_fence":
		return _build_chainlink_fence()

	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	match kind:
		"mailbox":
			_build_mailbox(st, variant)
		"garbage_bin":
			_build_bin(st, variant, [Color(0.09, 0.22, 0.12), Color(0.20, 0.20, 0.22),
				Color(0.15, 0.22, 0.34)])
		"recycling_bin":
			_build_bin(st, variant, [Color(0.10, 0.16, 0.32), Color(0.13, 0.30, 0.42),
				Color(0.55, 0.50, 0.12)])
		"fire_hydrant":
			_build_fire_hydrant(st, variant)
		"utility_pole":
			_build_utility_pole(st)
		"streetlight":
			_build_streetlight(st, variant)
		"traffic_sign":
			_build_traffic_sign(st)
		"traffic_signal":
			_build_traffic_signal(st)
		"guardrail":
			_build_guardrail(st)
		"bollard":
			_build_bollard(st, variant)
		"transformer_box":
			_build_transformer_box(st, variant)
		"utility_cabinet":
			_build_utility_cabinet(st, variant)
		"ac_condenser":
			_build_ac_condenser(st)
		"rooftop_hvac":
			_box(st, Vector3(0.0, 0.5, 0.0), Vector3(2.0, 1.0, 1.5), Color(0.55, 0.56, 0.58))
		"dumpster":
			_build_dumpster(st, variant)
		"parking_stop":
			_box(st, Vector3(0.0, 0.075, 0.0), Vector3(1.8, 0.15, 0.15), Color(0.6, 0.6, 0.58))
		"bench":
			_build_bench(st, variant)
		"bus_shelter":
			_build_bus_shelter(st)
		"wood_fence":
			_build_wood_fence(st, variant)
		"pallet":
			_build_pallet(st)
		"road_barrier":
			_build_road_barrier(st)
		"sedan", "suv", "pickup", "van", "box_truck", "jeep", "sports_car", \
		"semi_truck", "oil_tanker":
			_build_vehicle(st, kind, variant)
		"tree_round":
			_build_tree_round(st, variant)
		"tree_oak":
			_build_tree_oak(st, variant)
		"tree_conical":
			_build_tree_conical(st, variant)
		"tree_columnar":
			_build_tree_columnar(st, variant)
		"tree_palm":
			_build_tree_palm(st, variant)
		"tree_willow":
			_build_tree_willow(st, variant)
		"bush_round":
			_build_bush_round(st, variant)
		"bush_low":
			_build_bush_low(st, variant)
		"tree_magnolia":
			_build_tree_magnolia(st, variant)
		"tree_crape_myrtle":
			_build_tree_crape_myrtle(st, variant)
		"tree_baldcypress":
			_build_tree_baldcypress(st, variant)
		"hedge":
			_build_hedge(st, variant)
		"flowering_shrub":
			_build_flowering_shrub(st, variant)
		"tall_grass":
			_build_tall_grass(st, variant)
		"native_scrub":
			_build_native_scrub(st, variant)
		_:
			# Unknown kind: an obvious magenta box rather than a silent crash.
			_box(st, Vector3(0.0, 0.5, 0.0), Vector3(0.5, 1.0, 0.5), Color(1.0, 0.0, 1.0))
	st.generate_normals()
	var mesh := st.commit()
	var vehicle_kinds := {"sedan": true, "suv": true, "pickup": true, "van": true,
		"box_truck": true, "jeep": true, "sports_car": true,
		"semi_truck": true, "oil_tanker": true}
	mesh.surface_set_material(0, _vehicle_material() if vehicle_kinds.has(kind) else _opaque_material())
	return mesh


# ------------------------------------------------------------- geometry core
## An axis-aligned box centred at `center`. Winding is the same proven table
## used by site_detail.gd's `_box` (front = -Z, back = +Z, right = +X,
## left = -X), so generate_normals() yields outward normals.
static func _box(st: SurfaceTool, center: Vector3, size: Vector3, color: Color) -> void:
	st.set_color(color)
	var h := size * 0.5
	var c0 := center + Vector3(-h.x, -h.y, -h.z)
	var c1 := center + Vector3(h.x, -h.y, -h.z)
	var c2 := center + Vector3(h.x, -h.y, h.z)
	var c3 := center + Vector3(-h.x, -h.y, h.z)
	var c4 := center + Vector3(-h.x, h.y, -h.z)
	var c5 := center + Vector3(h.x, h.y, -h.z)
	var c6 := center + Vector3(h.x, h.y, h.z)
	var c7 := center + Vector3(-h.x, h.y, h.z)
	var faces := [
		[c0, c1, c2, c3],   # bottom
		[c7, c6, c5, c4],   # top
		[c4, c5, c1, c0],   # front (-Z)
		[c6, c7, c3, c2],   # back (+Z)
		[c5, c6, c2, c1],   # right (+X)
		[c7, c4, c0, c3],   # left (-X)
	]
	for f in faces:
		var p0: Vector3 = f[0]
		var p1: Vector3 = f[1]
		var p2: Vector3 = f[2]
		var p3: Vector3 = f[3]
		st.add_vertex(p0); st.add_vertex(p1); st.add_vertex(p2)
		st.add_vertex(p0); st.add_vertex(p2); st.add_vertex(p3)


## A cylinder standing on `base` (its bottom-centre), radius/height in metres,
## `segs` sides. Caps are optional flat fans (open-ended is fine per spec).
static func _cylinder(st: SurfaceTool, base: Vector3, radius: float, height: float,
		segs: int, color: Color, cap_top: bool = true, cap_bottom: bool = false) -> void:
	st.set_color(color)
	var top_c := base + Vector3(0.0, height, 0.0)
	for i in range(segs):
		var a0 := TAU * float(i) / float(segs)
		var a1 := TAU * float(i + 1) / float(segs)
		var b0 := base + Vector3(cos(a0) * radius, 0.0, sin(a0) * radius)
		var b1 := base + Vector3(cos(a1) * radius, 0.0, sin(a1) * radius)
		var t0 := b0 + Vector3(0.0, height, 0.0)
		var t1 := b1 + Vector3(0.0, height, 0.0)
		st.add_vertex(b0); st.add_vertex(t0); st.add_vertex(t1)
		st.add_vertex(b0); st.add_vertex(t1); st.add_vertex(b1)
		if cap_top:
			st.add_vertex(top_c); st.add_vertex(t1); st.add_vertex(t0)
		if cap_bottom:
			st.add_vertex(base); st.add_vertex(b0); st.add_vertex(b1)


## A cone standing on `base` (its bottom-centre circle), apex at `base.y + height`.
static func _cone(st: SurfaceTool, base: Vector3, radius: float, height: float,
		segs: int, color: Color, cap_bottom: bool = true) -> void:
	st.set_color(color)
	var apex := base + Vector3(0.0, height, 0.0)
	for i in range(segs):
		var a0 := TAU * float(i) / float(segs)
		var a1 := TAU * float(i + 1) / float(segs)
		var b0 := base + Vector3(cos(a0) * radius, 0.0, sin(a0) * radius)
		var b1 := base + Vector3(cos(a1) * radius, 0.0, sin(a1) * radius)
		st.add_vertex(b0); st.add_vertex(apex); st.add_vertex(b1)
		if cap_bottom:
			st.add_vertex(base); st.add_vertex(b0); st.add_vertex(b1)


static func _tjit(seed: int, i: int, amp: float) -> float:
	var h := (seed * 73856093) ^ (i * 19349663)
	h = (h ^ (h >> 13)) & 0x7fffffff
	return (float(h % 1000) / 1000.0 - 0.5) * 2.0 * amp


## A low-poly faceted foliage lobe — an irregular ellipsoid. `radius` is per-axis;
## a small deterministic per-vertex jitter (keyed on `seed`) breaks the sphere into
## facets so canopies read as foliage rather than boxes or perfect balls. About
## lat*lon*2 triangles (default 6x3 -> ~36), so a broadleaf tree built from a few
## lobes stays well under the ~180-tri budget. Wound outward for correct flat
## normals; the foliage material is double-sided so there are never holes.
static func _faceted_ellipsoid(st: SurfaceTool, center: Vector3, radius: Vector3,
		color: Color, seed: int = 0, lon: int = 5, lat: int = 3) -> void:
	st.set_color(color)
	var amp := 0.18
	var grid: Array = []
	for i in range(lat + 1):
		var row: Array = []
		var theta := PI * float(i) / float(lat)
		var cy := cos(theta)
		var sr := sin(theta)
		for j in range(lon):
			if i == 0 or i == lat:
				var py0 := cy * radius.y * (1.0 + _tjit(seed, i * 131, amp))
				row.append(center + Vector3(0.0, py0, 0.0))
			else:
				var phi := TAU * float(j) / float(lon)
				var jr := 1.0 + _tjit(seed, i * 97 + j * 7, amp)
				var px := cos(phi) * sr * radius.x * jr
				var pz := sin(phi) * sr * radius.z * jr
				var py := cy * radius.y * (1.0 + _tjit(seed, i * 31 + j * 3, amp * 0.5))
				row.append(center + Vector3(px, py, pz))
		grid.append(row)
	for i in range(lat):
		for j in range(lon):
			var j2 := (j + 1) % lon
			var a: Vector3 = grid[i][j]
			var b: Vector3 = grid[i][j2]
			var c: Vector3 = grid[i + 1][j]
			var d: Vector3 = grid[i + 1][j2]
			st.add_vertex(a); st.add_vertex(c); st.add_vertex(d)
			st.add_vertex(a); st.add_vertex(d); st.add_vertex(b)


## A single flat two-sided quad (its own two triangles), useful for thin
## rails/panels where a full box would be overkill. `p0..p3` must wind CCW
## as seen from the side the normal should face; cull is disabled anyway so
## a reversed panel still renders, just from generate_normals()'s call.
static func _quad(st: SurfaceTool, p0: Vector3, p1: Vector3, p2: Vector3, p3: Vector3, color: Color) -> void:
	st.set_color(color)
	st.add_vertex(p0); st.add_vertex(p1); st.add_vertex(p2)
	st.add_vertex(p0); st.add_vertex(p2); st.add_vertex(p3)


# ------------------------------------------------------------------- street furniture
static func _build_mailbox(st: SurfaceTool, variant := 0) -> void:
	var posts := [Color(0.30, 0.30, 0.33), Color(0.34, 0.28, 0.22),
		Color(0.42, 0.42, 0.44), Color(0.50, 0.42, 0.32)]
	var boxes := [Color(0.22, 0.26, 0.34), Color(0.55, 0.14, 0.12),
		Color(0.20, 0.20, 0.22), Color(0.35, 0.36, 0.40)]
	var pc: Color = posts[variant % posts.size()]
	var bc: Color = boxes[variant % boxes.size()]
	match variant % 4:
		0:
			_cylinder(st, Vector3.ZERO, 0.04, 1.0, 6, pc, true, false)
			_box(st, Vector3(0.0, 1.075, 0.05), Vector3(0.16, 0.15, 0.38), bc)
		1:
			_cylinder(st, Vector3.ZERO, 0.045, 1.15, 6, pc, true, false)
			_box(st, Vector3(0.0, 1.24, 0.06), Vector3(0.20, 0.20, 0.46), bc)
		2:
			_box(st, Vector3(0.0, 0.55, 0.0), Vector3(0.10, 1.1, 0.10), pc)
			_box(st, Vector3(0.0, 1.15, 0.0), Vector3(0.42, 0.60, 0.34), bc)
		3:
			_box(st, Vector3(0.0, 0.5, 0.0), Vector3(0.34, 1.0, 0.34), pc)
			_box(st, Vector3(0.0, 1.12, 0.06), Vector3(0.22, 0.16, 0.40), bc)


static func _build_bin(st: SurfaceTool, variant := 0, bodies := []) -> void:
	var body_col: Color = bodies[variant % bodies.size()] if bodies else Color(0.2, 0.2, 0.22)
	var lip_col := body_col.lightened(0.12)
	match variant % 3:
		0:
			_box(st, Vector3(0.0, 0.5, 0.0), Vector3(0.6, 1.0, 0.6), body_col)
			_box(st, Vector3(0.0, 1.02, 0.0), Vector3(0.66, 0.08, 0.66), lip_col)
		1:
			_box(st, Vector3(0.0, 0.58, 0.0), Vector3(0.52, 1.16, 0.56), body_col)
			_box(st, Vector3(0.0, 1.18, -0.02), Vector3(0.56, 0.08, 0.5), lip_col)
		2:
			_cylinder(st, Vector3(0.0, 0.0, 0.0), 0.32, 0.9, 10, body_col, false, false)
			_cylinder(st, Vector3(0.0, 0.9, 0.0), 0.35, 0.08, 10, lip_col, false, true)


static func _build_fire_hydrant(st: SurfaceTool, variant := 0) -> void:
	var bodies := [Color(0.55, 0.12, 0.10), Color(0.70, 0.58, 0.10), Color(0.70, 0.72, 0.74)]
	var col: Color = bodies[variant % bodies.size()]
	var dark := col.darkened(0.35)
	_cylinder(st, Vector3(0.0, 0.0, 0.0), 0.17, 0.08, 8, dark, false, true)   # base flange
	_cylinder(st, Vector3(0.0, 0.08, 0.0), 0.14, 0.55, 8, col, false, false)
	_cone(st, Vector3(0.0, 0.63, 0.0), 0.16, 0.17, 8, col, false)
	_box(st, Vector3(0.16, 0.40, 0.0), Vector3(0.10, 0.10, 0.10), dark)      # left nozzle
	_box(st, Vector3(-0.16, 0.40, 0.0), Vector3(0.10, 0.10, 0.10), dark)     # right nozzle


static func _build_utility_pole(st: SurfaceTool) -> void:
	var wood := Color(0.35, 0.26, 0.16)
	var metal := Color(0.30, 0.30, 0.32)
	_cylinder(st, Vector3.ZERO, 0.125, 9.0, 6, wood, true, false)
	_box(st, Vector3(0.0, 8.3, 0.0), Vector3(1.6, 0.1, 0.1), metal)
	_box(st, Vector3(-0.6, 8.15, 0.0), Vector3(0.08, 0.2, 0.08), Color(0.55, 0.52, 0.48))
	_box(st, Vector3(0.6, 8.15, 0.0), Vector3(0.08, 0.2, 0.08), Color(0.55, 0.52, 0.48))


static func _build_streetlight(st: SurfaceTool, variant := 0) -> void:
	var col := Color(0.22, 0.23, 0.25)
	var head := Color(0.15, 0.16, 0.18)
	match variant % 3:
		0:
			_cylinder(st, Vector3.ZERO, 0.08, 6.0, 6, col, true, false)
			_box(st, Vector3(0.7, 5.95, 0.0), Vector3(1.4, 0.08, 0.08), col)
			_box(st, Vector3(1.4, 5.78, 0.0), Vector3(0.30, 0.22, 0.30), head)
		1:
			_cylinder(st, Vector3.ZERO, 0.09, 4.6, 6, col, true, false)
			_box(st, Vector3(0.0, 4.78, 0.0), Vector3(0.34, 0.30, 0.34), head)
		2:
			_cylinder(st, Vector3.ZERO, 0.09, 6.6, 6, col, true, false)
			for s in [-1.0, 1.0]:
				var sf := float(s)
				_box(st, Vector3(0.6 * sf, 6.55, 0.0), Vector3(1.2, 0.08, 0.08), col)
				_box(st, Vector3(1.2 * sf, 6.4, 0.0), Vector3(0.28, 0.20, 0.28), head)


static func _build_utility_cabinet(st: SurfaceTool, variant := 0) -> void:
	var cols := [Color(0.45, 0.46, 0.48), Color(0.50, 0.52, 0.48), Color(0.38, 0.40, 0.44)]
	var c: Color = cols[variant % cols.size()]
	var sizes := [Vector3(0.6, 1.2, 0.4), Vector3(0.9, 1.4, 0.5), Vector3(0.45, 1.0, 0.35)]
	var sz: Vector3 = sizes[variant % sizes.size()]
	_box(st, Vector3(0.0, sz.y * 0.5, 0.0), sz, c)
	_box(st, Vector3(0.0, sz.y + 0.03, 0.0), Vector3(sz.x + 0.06, 0.06, sz.z + 0.06), c.darkened(0.2))


static func _build_traffic_sign(st: SurfaceTool) -> void:
	var post_col := Color(0.42, 0.42, 0.44)
	var plate_col := Color(0.85, 0.85, 0.80)
	_cylinder(st, Vector3.ZERO, 0.045, 2.2, 6, post_col, true, false)
	_box(st, Vector3(0.0, 1.9, 0.03), Vector3(0.6, 0.6, 0.04), plate_col)


static func _build_traffic_signal(st: SurfaceTool) -> void:
	var dark := Color(0.14, 0.14, 0.16)
	_cylinder(st, Vector3.ZERO, 0.09, 4.5, 6, dark, true, false)
	_box(st, Vector3(1.4, 4.35, 0.0), Vector3(2.8, 0.09, 0.09), dark)
	_box(st, Vector3(2.7, 4.05, 0.0), Vector3(0.32, 0.85, 0.30), dark)
	_box(st, Vector3(2.7, 4.30, 0.16), Vector3(0.16, 0.16, 0.05), Color(0.65, 0.10, 0.08))
	_box(st, Vector3(2.7, 4.05, 0.16), Vector3(0.16, 0.16, 0.05), Color(0.65, 0.55, 0.08))
	_box(st, Vector3(2.7, 3.80, 0.16), Vector3(0.16, 0.16, 0.05), Color(0.10, 0.45, 0.15))


static func _build_guardrail(st: SurfaceTool) -> void:
	var post_col := Color(0.4, 0.4, 0.42)
	var rail_col := Color(0.55, 0.55, 0.53)
	_box(st, Vector3(-1.0, 0.35, 0.0), Vector3(0.08, 0.7, 0.08), post_col)
	_box(st, Vector3(1.0, 0.35, 0.0), Vector3(0.08, 0.7, 0.08), post_col)
	_box(st, Vector3(0.0, 0.55, 0.0), Vector3(2.0, 0.18, 0.06), rail_col)


static func _build_bollard(st: SurfaceTool, variant := 0) -> void:
	var cols := [Color(0.12, 0.12, 0.14), Color(0.72, 0.20, 0.06), Color(0.72, 0.72, 0.10)]
	var col: Color = cols[variant % cols.size()]
	match variant % 3:
		0:
			_cylinder(st, Vector3.ZERO, 0.10, 0.85, 8, col, false, true)
			_cone(st, Vector3(0.0, 0.85, 0.0), 0.10, 0.05, 8, col, false)
		1:
			_cylinder(st, Vector3.ZERO, 0.09, 0.95, 8, col, false, true)
			_cylinder(st, Vector3(0.0, 0.95, 0.0), 0.11, 0.06, 8, col.lightened(0.3), false, true)
		2:
			_box(st, Vector3(0.0, 0.4, 0.0), Vector3(0.18, 0.8, 0.18), col)
			_box(st, Vector3(0.0, 0.83, 0.0), Vector3(0.22, 0.06, 0.22), col.lightened(0.2))


static func _build_transformer_box(st: SurfaceTool, variant := 0) -> void:
	var cols := [Color(0.55, 0.62, 0.52), Color(0.48, 0.50, 0.52)]
	var col: Color = cols[variant % cols.size()]
	var w := 1.2 if variant % 2 == 0 else 1.5
	_box(st, Vector3(0.0, 0.5, 0.0), Vector3(w, 1.0, 1.0), col)
	_box(st, Vector3(0.0, 1.03, 0.0), Vector3(w + 0.04, 0.06, 1.04), col.darkened(0.2))


static func _build_ac_condenser(st: SurfaceTool) -> void:
	var col := Color(0.72, 0.72, 0.70)
	var top := Color(0.52, 0.52, 0.50)
	_box(st, Vector3(0.0, 0.35, 0.0), Vector3(0.8, 0.7, 0.8), col)
	_box(st, Vector3(0.0, 0.72, 0.0), Vector3(0.82, 0.06, 0.82), top)


static func _build_dumpster(st: SurfaceTool, variant := 0) -> void:
	var cols := [Color(0.08, 0.20, 0.11), Color(0.20, 0.12, 0.10), Color(0.16, 0.18, 0.30)]
	var col: Color = cols[variant % cols.size()]
	var lid := col.lightened(0.10)
	var w := 1.8 if variant % 2 == 0 else 2.2
	_box(st, Vector3(0.0, 0.65, 0.0), Vector3(w, 1.3, 1.2), col)
	_box(st, Vector3(0.0, 1.36, 0.0), Vector3(w + 0.05, 0.12, 1.25), lid)
	_box(st, Vector3(0.0, 1.48, 0.0), Vector3(0.20, 0.12, 1.25), lid.darkened(0.1))


static func _build_bench(st: SurfaceTool, variant := 0) -> void:
	var woods := [Color(0.45, 0.30, 0.16), Color(0.30, 0.32, 0.34), Color(0.22, 0.34, 0.24)]
	var wood: Color = woods[variant % woods.size()]
	var metal := Color(0.20, 0.20, 0.22)
	var length := 1.6 if variant % 2 == 0 else 2.0
	_box(st, Vector3(0.0, 0.45, 0.0), Vector3(length, 0.05, 0.4), wood)
	_box(st, Vector3(0.0, 0.75, -0.17), Vector3(length, 0.35, 0.05), wood)
	_box(st, Vector3(-length * 0.44, 0.225, 0.0), Vector3(0.08, 0.45, 0.36), metal)
	_box(st, Vector3(length * 0.44, 0.225, 0.0), Vector3(0.08, 0.45, 0.36), metal)


static func _build_bus_shelter(st: SurfaceTool) -> void:
	var frame := Color(0.32, 0.34, 0.36)
	var roof := Color(0.24, 0.25, 0.28)
	var hx := 1.5
	var hz := 0.6
	var h := 2.2
	for sx in [-1.0, 1.0]:
		for sz in [-1.0, 1.0]:
			_box(st, Vector3(sx * hx, h * 0.5, sz * hz), Vector3(0.08, h, 0.08), frame)
	_box(st, Vector3(0.0, h + 0.1, 0.0), Vector3(3.0, 0.1, 1.2), roof)
	_box(st, Vector3(0.0, 0.15, -hz), Vector3(3.0, 0.3, 0.06), frame)   # low back sill


## Residential fence panel (2 m wide, along X). `variant` selects the style so a
## yard can pick a consistent look: 0 picket, 1 privacy board, 2 split rail,
## 3 wrought iron. One panel is baked per style (MultiMesh), so a whole fence run
## of one style is a single draw.
static func _build_wood_fence(st: SurfaceTool, variant: int = 0) -> void:
	match ((variant % 4) + 4) % 4:
		1:  # privacy — a tall solid board panel with a capped top rail
			var pp := Color(0.42, 0.31, 0.19)
			var brd := Color(0.54, 0.41, 0.27)
			_box(st, Vector3(-1.0, 0.9, 0.0), Vector3(0.17, 1.8, 0.17), pp.darkened(0.12))
			_box(st, Vector3(1.0, 0.9, 0.0), Vector3(0.17, 1.8, 0.17), pp.darkened(0.12))
			_box(st, Vector3(0.0, 0.88, 0.0), Vector3(2.0, 1.66, 0.07), brd)          # solid boards
			_box(st, Vector3(0.0, 1.76, 0.0), Vector3(2.02, 0.12, 0.12), pp)          # top cap
			for i in range(6):                                                        # board seams
				_box(st, Vector3(-0.83 + float(i) * 0.33, 0.88, 0.045),
					Vector3(0.05, 1.5, 0.02), brd.darkened(0.14))
		2:  # split rail — chunky posts + two open rails (rustic ranch)
			var wd := Color(0.46, 0.37, 0.27)
			_box(st, Vector3(-1.0, 0.58, 0.0), Vector3(0.2, 1.16, 0.2), wd.darkened(0.1))
			_box(st, Vector3(1.0, 0.58, 0.0), Vector3(0.2, 1.16, 0.2), wd.darkened(0.1))
			_box(st, Vector3(0.0, 0.44, 0.0), Vector3(2.0, 0.13, 0.11), wd)
			_box(st, Vector3(0.0, 0.86, 0.0), Vector3(2.0, 0.13, 0.11), wd.lerp(Color.WHITE, 0.05))
		3:  # wrought iron — thin vertical bars, top/bottom rails, spear tops
			var iron := Color(0.11, 0.11, 0.13)
			_box(st, Vector3(-1.0, 0.72, 0.0), Vector3(0.12, 1.48, 0.12), iron)
			_box(st, Vector3(1.0, 0.72, 0.0), Vector3(0.12, 1.48, 0.12), iron)
			_box(st, Vector3(0.0, 0.32, 0.0), Vector3(2.0, 0.06, 0.06), iron)
			_box(st, Vector3(0.0, 1.18, 0.0), Vector3(2.0, 0.06, 0.06), iron)
			var nbar := 11
			for i in range(nbar):
				var bx := -0.9 + float(i) * (1.8 / float(nbar - 1))
				_box(st, Vector3(bx, 0.74, 0.0), Vector3(0.04, 1.4, 0.04), iron)
				_box(st, Vector3(bx, 1.42, 0.0), Vector3(0.055, 0.14, 0.055), iron)   # spear tip
		_:  # 0 picket (the classic)
			var post := Color(0.34, 0.24, 0.14)
			var rail := Color(0.46, 0.33, 0.19)
			var plank := Color(0.57, 0.42, 0.25)
			_box(st, Vector3(-1.0, 0.62, 0.0), Vector3(0.15, 1.24, 0.15), post)
			_box(st, Vector3(1.0, 0.62, 0.0), Vector3(0.15, 1.24, 0.15), post)
			_box(st, Vector3(0.0, 0.35, -0.02), Vector3(2.0, 0.11, 0.08), rail)
			_box(st, Vector3(0.0, 0.92, -0.02), Vector3(2.0, 0.11, 0.08), rail)
			var pickets := 9
			for i in range(pickets):
				var x := -0.88 + float(i) * (1.76 / float(pickets - 1))
				_box(st, Vector3(x, 0.60, 0.04), Vector3(0.13, 1.16, 0.06), plank)


static func _build_chainlink_fence() -> ArrayMesh:
	# Frame (opaque surface 0): two posts + a top rail.
	var post_col := Color(0.5, 0.5, 0.52)
	var st_frame := SurfaceTool.new()
	st_frame.begin(Mesh.PRIMITIVE_TRIANGLES)
	_box(st_frame, Vector3(-1.0, 0.9, 0.0), Vector3(0.09, 1.8, 0.09), post_col)
	_box(st_frame, Vector3(1.0, 0.9, 0.0), Vector3(0.09, 1.8, 0.09), post_col)
	_box(st_frame, Vector3(0.0, 1.78, 0.0), Vector3(2.0, 0.07, 0.07), post_col)   # top rail
	_box(st_frame, Vector3(0.0, 0.10, 0.0), Vector3(2.0, 0.06, 0.06), post_col)   # bottom rail
	st_frame.generate_normals()

	# Mesh panel (transparent surface 1): a single thin double-sided slab.
	var mesh_col := Color(0.55, 0.55, 0.55, 0.35)
	var st_panel := SurfaceTool.new()
	st_panel.begin(Mesh.PRIMITIVE_TRIANGLES)
	_box(st_panel, Vector3(0.0, 0.9, 0.0), Vector3(1.96, 1.76, 0.02), mesh_col)
	st_panel.generate_normals()

	var mesh := ArrayMesh.new()
	st_frame.commit(mesh)
	mesh.surface_set_material(0, _opaque_material())
	st_panel.commit(mesh)
	mesh.surface_set_material(1, _glass_material())
	return mesh


static func _build_pallet(st: SurfaceTool) -> void:
	var col := Color(0.55, 0.42, 0.26)
	# Three block "feet" support the deck.
	for x in [-0.5, 0.0, 0.5]:
		_box(st, Vector3(x, 0.05, 0.0), Vector3(0.15, 0.10, 1.2), col.darkened(0.1))
	# Deck slats laid crosswise on top.
	for i in range(5):
		var z := -0.48 + float(i) * 0.24
		_box(st, Vector3(0.0, 0.13, z), Vector3(1.2, 0.04, 0.18), col)


static func _build_road_barrier(st: SurfaceTool) -> void:
	var orange := Color(0.85, 0.35, 0.05)
	var white := Color(0.85, 0.85, 0.80)
	_box(st, Vector3(0.0, 0.4, 0.0), Vector3(1.5, 0.8, 0.5), orange)
	_box(st, Vector3(0.0, 0.45, 0.0), Vector3(1.44, 0.18, 0.51), white)


# ------------------------------------------------------------------------- vehicles
const VEHICLE_COLORS := [
	Color(0.55, 0.10, 0.10),   # muted red
	Color(0.14, 0.15, 0.18),   # near-black
	Color(0.72, 0.72, 0.70),   # silver
	Color(0.16, 0.26, 0.42),   # navy
	Color(0.40, 0.40, 0.40),   # gunmetal grey
]
const WHEEL_COLOR := Color(0.05, 0.05, 0.06)


static func _vehicle_color(variant: int) -> Color:
	var i := variant % VEHICLE_COLORS.size()
	if i < 0:
		i += VEHICLE_COLORS.size()
	return VEHICLE_COLORS[i]


## A round wheel: a Z-axis barrel (a tyre lying across the car) with dark side
## discs and a lighter hub, its bottom on the ground. `cx`,`cz` = axle centre,
## `r` = radius, `w` = width.
static func _wheel(st: SurfaceTool, cx: float, cz: float, r: float, w: float) -> void:
	var segs := 10
	var hw := w * 0.5
	var y := r
	var c0 := Vector3(cx, y, cz - hw)
	var c1 := Vector3(cx, y, cz + hw)
	var hub := Color(0.28, 0.29, 0.32)
	for i in range(segs):
		var a0 := TAU * float(i) / float(segs)
		var a1 := TAU * float(i + 1) / float(segs)
		var d0 := Vector2(cos(a0) * r, sin(a0) * r)
		var d1 := Vector2(cos(a1) * r, sin(a1) * r)
		var p0 := Vector3(cx + d0.x, y + d0.y, cz - hw)
		var p1 := Vector3(cx + d1.x, y + d1.y, cz - hw)
		var p2 := Vector3(cx + d1.x, y + d1.y, cz + hw)
		var p3 := Vector3(cx + d0.x, y + d0.y, cz + hw)
		st.set_color(WHEEL_COLOR)
		st.add_vertex(p0); st.add_vertex(p1); st.add_vertex(p2)
		st.add_vertex(p0); st.add_vertex(p2); st.add_vertex(p3)
		# side discs, hub-coloured near the axle
		st.set_color(hub if (i % 2 == 0) else WHEEL_COLOR)
		st.add_vertex(c0); st.add_vertex(p1); st.add_vertex(p0)
		st.add_vertex(c1); st.add_vertex(p3); st.add_vertex(p2)


static func _axles(st: SurfaceTool, xf: float, xr: float, zc: float, r: float, w: float) -> void:
	for x in [xf, xr]:
		_wheel(st, x, zc, r, w)
		_wheel(st, x, -zc, r, w)


## A raked glazing panel (windshield / backlight) spanning the full width ±zc,
## sloping from (xb, yb) at the belt up to (xt, yt) at the roof.
static func _rake(st: SurfaceTool, xb: float, yb: float, xt: float, yt: float,
		zc: float, col: Color) -> void:
	_quad(st, Vector3(xb, yb, -zc), Vector3(xb, yb, zc),
		Vector3(xt, yt, zc), Vector3(xt, yt, -zc), col)


## Head/tail light pair on the front (+X) or rear (-X) face at height y.
static func _lights(st: SurfaceTool, x: float, y: float, zc: float, col: Color) -> void:
	_box(st, Vector3(x, y, zc), Vector3(0.08, 0.16, 0.34), col)
	_box(st, Vector3(x, y, -zc), Vector3(0.08, 0.16, 0.34), col)


## A conventional (long-hood) semi tractor: chassis rail, hood, tall sleeper cab
## with a raked screen + aero roof fairing, twin exhaust stacks and the fifth-wheel
## coupling plate. Front bumper at x≈8.2; the trailer/tank mounts around x≈4.3.
## Shared by the 18-wheeler and the oil tanker.
static func _tractor(st: SurfaceTool, col: Color, glass: Color, trim: Color) -> void:
	var flight := Color(0.93, 0.90, 0.74)
	_box(st, Vector3(5.6, 0.9, 0.0), Vector3(5.6, 0.24, 1.2), trim)     # chassis rail
	_box(st, Vector3(7.15, 1.2, 0.0), Vector3(1.9, 1.1, 2.34), col)     # hood
	_box(st, Vector3(8.2, 0.92, 0.0), Vector3(0.24, 0.9, 2.5), trim)    # front bumper
	_box(st, Vector3(8.06, 1.3, 0.0), Vector3(0.12, 0.9, 1.9), trim.darkened(0.2))  # grille
	_lights(st, 8.2, 1.05, 0.98, flight)                                # headlamps
	_box(st, Vector3(5.75, 2.15, 0.0), Vector3(1.9, 2.9, 2.42), col)    # tall sleeper cab
	_box(st, Vector3(6.68, 2.55, 0.0), Vector3(0.12, 1.35, 2.0), glass) # windshield
	_box(st, Vector3(5.8, 2.5, 1.2), Vector3(1.25, 0.95, 0.04), glass)  # side glass
	_box(st, Vector3(5.8, 2.5, -1.2), Vector3(1.25, 0.95, 0.04), glass)
	_box(st, Vector3(5.15, 3.55, 0.0), Vector3(1.35, 0.5, 2.24), col)   # roof aero fairing
	_cylinder(st, Vector3(4.85, 0.9, 1.05), 0.1, 2.9, 6, trim, true, false)   # exhaust stacks
	_cylinder(st, Vector3(4.85, 0.9, -1.05), 0.1, 2.9, 6, trim, true, false)
	_box(st, Vector3(4.35, 1.05, 0.0), Vector3(1.4, 0.24, 1.6), trim)   # fifth-wheel plate


## Big-rig running gear: front steer axle + tractor drive tandem (dual) + trailer
## tandem (dual) = 18 wheels. `rear_ax` are the two trailer axle x positions.
static func _rig_wheels(st: SurfaceTool, rear_ax: Array) -> void:
	var r := 0.5
	var w := 0.32
	_wheel(st, 7.4, 1.08, r, w)                     # steer
	_wheel(st, 7.4, -1.08, r, w)
	for ax in [5.0, 4.15]:                          # drive tandem, dual wheels
		for zc in [1.16, 0.82, -0.82, -1.16]:
			_wheel(st, ax, zc, r, w)
	for ax in rear_ax:                              # trailer tandem, dual wheels
		for zc in [1.16, 0.82, -0.82, -1.16]:
			_wheel(st, ax, zc, r, w)


## A horizontal tank barrel along X (the tanker trailer), radius `r`, axis at
## height `cy`, capped at both ends.
static func _tank(st: SurfaceTool, x0: float, x1: float, cy: float, r: float, col: Color) -> void:
	st.set_color(col)
	var segs := 12
	var c0 := Vector3(x0, cy, 0.0)
	var c1 := Vector3(x1, cy, 0.0)
	for i in range(segs):
		var a0 := TAU * float(i) / float(segs)
		var a1 := TAU * float(i + 1) / float(segs)
		var p0 := Vector3(x0, cy + cos(a0) * r, sin(a0) * r)
		var p1 := Vector3(x0, cy + cos(a1) * r, sin(a1) * r)
		var q0 := Vector3(x1, cy + cos(a0) * r, sin(a0) * r)
		var q1 := Vector3(x1, cy + cos(a1) * r, sin(a1) * r)
		st.add_vertex(p0); st.add_vertex(q0); st.add_vertex(q1)
		st.add_vertex(p0); st.add_vertex(q1); st.add_vertex(p1)
		st.add_vertex(c0); st.add_vertex(p1); st.add_vertex(p0)   # end caps
		st.add_vertex(c1); st.add_vertex(q0); st.add_vertex(q1)


static func _build_vehicle(st: SurfaceTool, kind: String, variant: int) -> void:
	var col := _vehicle_color(variant)
	var glass := Color(0.11, 0.13, 0.17)
	var trim := col.darkened(0.42)                 # bumpers, rocker, cladding
	var flight := Color(0.93, 0.90, 0.74)          # headlights
	var rlight := Color(0.58, 0.09, 0.08)          # tail lights
	match kind:
		"sedan":
			# 3-box saloon: low hood, raised cabin, separate boot. Head/tail lights
			# and bumpers make front vs rear unmistakable.
			var zc := 0.80
			_axles(st, 1.35, -1.4, zc, 0.34, 0.24)
			_box(st, Vector3(0.0, 0.5, 0.0), Vector3(4.5, 0.30, 1.66), trim)     # rocker
			_box(st, Vector3(-0.1, 0.80, 0.0), Vector3(4.3, 0.34, 1.72), col)    # lower body / doors
			_box(st, Vector3(1.45, 0.94, 0.0), Vector3(1.7, 0.22, 1.66), col)    # hood (low, front)
			_box(st, Vector3(-1.55, 1.0, 0.0), Vector3(1.4, 0.26, 1.66), col)    # boot (rear, a touch higher)
			_box(st, Vector3(-0.25, 1.24, 0.0), Vector3(1.5, 0.5, 1.56), glass)  # greenhouse glass
			_box(st, Vector3(-0.3, 1.44, 0.0), Vector3(1.35, 0.1, 1.5), col)     # roof
			_rake(st, 0.62, 1.02, 0.45, 1.44, 0.76, glass)                       # windshield
			_rake(st, -1.05, 1.06, -0.9, 1.44, 0.76, glass)                      # rear window
			_box(st, Vector3(2.28, 0.62, 0.0), Vector3(0.16, 0.3, 1.7), trim)    # front bumper
			_box(st, Vector3(-2.28, 0.66, 0.0), Vector3(0.16, 0.3, 1.7), trim)   # rear bumper
			_lights(st, 2.29, 0.78, 0.6, flight)
			_lights(st, -2.29, 0.86, 0.62, rlight)
		"sports_car":
			# low + wide, long bonnet, cabin pushed right back, stubby tail.
			var zc := 0.86
			_axles(st, 1.5, -1.45, zc, 0.36, 0.28)
			_box(st, Vector3(0.0, 0.42, 0.0), Vector3(4.4, 0.30, 1.86), col)     # low wide body
			_box(st, Vector3(0.0, 0.24, 0.0), Vector3(4.2, 0.14, 1.9), trim)     # splitter/rocker
			_box(st, Vector3(1.35, 0.6, 0.0), Vector3(1.9, 0.2, 1.78), col)      # long low bonnet
			_box(st, Vector3(-1.4, 0.66, 0.0), Vector3(1.4, 0.26, 1.8), col)     # short rear deck
			_box(st, Vector3(-0.6, 0.88, 0.0), Vector3(1.2, 0.36, 1.62), glass)  # low cabin glass
			_box(st, Vector3(-0.7, 1.04, 0.0), Vector3(0.9, 0.08, 1.5), col)     # low roof
			_rake(st, 0.2, 0.7, -0.15, 1.06, 0.72, glass)                        # steep windscreen
			_rake(st, -1.25, 0.78, -1.05, 1.05, 0.72, glass)                     # fastback rear
			_box(st, Vector3(-2.15, 0.9, 0.0), Vector3(0.1, 0.12, 1.4), trim)    # rear spoiler lip
			_box(st, Vector3(2.22, 0.5, 0.0), Vector3(0.14, 0.22, 1.82), trim)   # front splitter
			_lights(st, 2.2, 0.6, 0.66, flight)
			_lights(st, -2.18, 0.78, 0.62, rlight)
		"jeep":
			# tall, boxy, upright — flat vertical windscreen, flat roof to the tail,
			# chunky tyres, round headlamps, tailgate-mounted spare.
			var zc := 0.86
			_axles(st, 1.4, -1.45, zc, 0.46, 0.30)
			_box(st, Vector3(0.0, 0.78, 0.0), Vector3(4.1, 0.72, 1.9), col)      # tall body
			_box(st, Vector3(0.0, 0.4, 0.0), Vector3(3.9, 0.22, 1.96), trim)     # sill/cladding
			_box(st, Vector3(1.55, 0.98, 0.0), Vector3(1.0, 0.5, 1.86), col)     # short flat bonnet
			_box(st, Vector3(-0.25, 1.5, 0.0), Vector3(2.6, 0.72, 1.66), glass)  # tall upright cabin glass
			_box(st, Vector3(-0.25, 1.82, 0.0), Vector3(2.7, 0.1, 1.8), col)     # flat roof (to the tail)
			_box(st, Vector3(1.02, 1.5, 0.0), Vector3(0.12, 0.72, 1.72), glass)  # near-vertical windscreen
			_box(st, Vector3(-2.05, 0.95, 0.0), Vector3(0.12, 0.9, 1.7), col)    # flat tailgate
			_wheel(st, -2.18, 0.0, 0.4, 0.22)                                    # spare on the tailgate
			_box(st, Vector3(2.12, 0.7, 0.0), Vector3(0.16, 0.5, 1.9), trim)     # brush bumper
			# round headlamps
			for zz in [0.6, -0.6]:
				_cylinder(st, Vector3(2.16, 0.95, zz), 0.13, 0.06, 8, flight, true, false)
			_lights(st, -2.13, 1.05, 0.66, rlight)
		"suv":
			# tall wagon: hood, big glasshouse, sloped tailgate.
			var zc := 0.84
			_axles(st, 1.5, -1.5, zc, 0.42, 0.26)
			_box(st, Vector3(0.0, 0.58, 0.0), Vector3(4.7, 0.4, 1.86), col)      # body
			_box(st, Vector3(0.0, 0.34, 0.0), Vector3(4.5, 0.2, 1.9), trim)      # cladding
			_box(st, Vector3(1.55, 0.85, 0.0), Vector3(1.6, 0.22, 1.8), col)     # hood
			_box(st, Vector3(-0.4, 1.2, 0.0), Vector3(3.0, 0.56, 1.66), glass)   # long glasshouse
			_box(st, Vector3(-0.4, 1.5, 0.0), Vector3(2.8, 0.1, 1.72), col)      # roof
			_rake(st, 0.9, 0.97, 0.6, 1.5, 0.78, glass)                          # windshield
			_rake(st, -1.85, 0.78, -1.7, 1.5, 0.78, glass)                       # sloped tailgate glass
			_box(st, Vector3(2.28, 0.6, 0.0), Vector3(0.16, 0.34, 1.8), trim)
			_box(st, Vector3(-2.32, 0.62, 0.0), Vector3(0.14, 0.36, 1.8), trim)
			_lights(st, 2.29, 0.82, 0.62, flight)
			_lights(st, -2.32, 0.95, 0.64, rlight)
		"pickup":
			var zc := 0.82
			_axles(st, 1.45, -1.45, zc, 0.42, 0.26)
			_box(st, Vector3(0.2, 0.56, 0.0), Vector3(5.1, 0.4, 1.8), col)       # frame/body
			_box(st, Vector3(0.2, 0.32, 0.0), Vector3(4.9, 0.2, 1.84), trim)     # rocker
			_box(st, Vector3(1.7, 0.86, 0.0), Vector3(1.5, 0.26, 1.76), col)     # hood
			_box(st, Vector3(0.55, 1.16, 0.0), Vector3(1.5, 0.5, 1.66), glass)   # cab glass
			_box(st, Vector3(0.5, 1.42, 0.0), Vector3(1.4, 0.1, 1.6), col)       # cab roof
			_rake(st, 1.2, 0.95, 1.0, 1.42, 0.76, glass)                         # windshield
			# open bed behind the cab
			_box(st, Vector3(-1.4, 0.82, 0.0), Vector3(2.9, 0.14, 1.7), col.darkened(0.1))  # bed floor
			_box(st, Vector3(-1.4, 1.06, 0.82), Vector3(2.9, 0.48, 0.12), col)              # bed wall
			_box(st, Vector3(-1.4, 1.06, -0.82), Vector3(2.9, 0.48, 0.12), col)
			_box(st, Vector3(-2.85, 1.04, 0.0), Vector3(0.12, 0.44, 1.72), col)             # tailgate
			_box(st, Vector3(2.5, 0.62, 0.0), Vector3(0.16, 0.36, 1.82), trim)
			_lights(st, 2.51, 0.82, 0.64, flight)
			_lights(st, -2.9, 0.96, 0.66, rlight)
		"van":
			# tall one-box: stubby raked nose, tall slab body, window band.
			var zc := 0.86
			_axles(st, 1.6, -1.55, zc, 0.4, 0.24)
			_box(st, Vector3(-0.2, 1.05, 0.0), Vector3(4.6, 1.5, 1.94), col)     # tall body
			_box(st, Vector3(-0.2, 0.36, 0.0), Vector3(4.5, 0.24, 1.98), trim)  # rocker
			_box(st, Vector3(2.05, 0.7, 0.0), Vector3(0.7, 0.5, 1.9), col)      # short nose
			_rake(st, 2.4, 0.95, 2.0, 1.7, 0.86, glass)                         # steep windscreen
			_box(st, Vector3(0.5, 1.42, 0.97), Vector3(2.2, 0.44, 0.03), glass) # side window band
			_box(st, Vector3(0.5, 1.42, -0.97), Vector3(2.2, 0.44, 0.03), glass)
			_box(st, Vector3(-2.52, 1.0, 0.0), Vector3(0.08, 1.3, 1.86), col)   # rear doors
			_box(st, Vector3(2.42, 0.55, 0.0), Vector3(0.14, 0.34, 1.92), trim)
			_lights(st, 2.42, 0.7, 0.7, flight)
			_lights(st, -2.55, 1.35, 0.66, rlight)
		"box_truck":
			var zc := 1.0
			_axles(st, 2.0, -1.6, zc, 0.44, 0.3)
			_box(st, Vector3(1.95, 0.95, 0.0), Vector3(1.5, 1.3, 2.05), col)     # cab
			_rake(st, 2.55, 1.1, 2.25, 1.95, 0.95, glass)                        # cab windshield
			_box(st, Vector3(2.05, 1.42, 0.97), Vector3(0.9, 0.5, 0.03), glass)  # cab side windows
			_box(st, Vector3(2.05, 1.42, -0.97), Vector3(0.9, 0.5, 0.03), glass)
			_box(st, Vector3(-0.95, 1.8, 0.0), Vector3(4.3, 2.9, 2.2), col.lerp(Color.WHITE, 0.12))  # cargo box
			_box(st, Vector3(2.7, 0.5, 0.0), Vector3(0.14, 0.4, 2.0), trim)
			_lights(st, 2.71, 0.7, 0.75, flight)
		"semi_truck":
			# 18-wheeler: conventional tractor + a long dry-van trailer on tandem axles.
			_rig_wheels(st, [-6.4, -7.4])
			_tractor(st, col, glass, trim)
			var tcol: Color = Color(0.85, 0.85, 0.87).lerp(col, 0.08)     # trailer skin (mostly neutral)
			_box(st, Vector3(-1.7, 2.25, 0.0), Vector3(12.4, 2.9, 2.5), tcol)     # trailer box
			_box(st, Vector3(-1.7, 0.82, 0.0), Vector3(12.0, 0.26, 1.2), trim)    # trailer frame
			_box(st, Vector3(-7.85, 2.2, 0.0), Vector3(0.12, 2.7, 2.46), tcol.darkened(0.1))  # rear doors
			_box(st, Vector3(-7.9, 0.7, 0.0), Vector3(0.16, 0.5, 2.3), trim)      # rear underride bar
			_box(st, Vector3(4.05, 0.6, 0.0), Vector3(0.1, 0.7, 0.7), trim)       # landing gear
			_lights(st, -7.9, 0.85, 1.0, rlight)
		"oil_tanker":
			# tractor + a polished cylindrical tank trailer with a walkway + dome hatch.
			_rig_wheels(st, [-6.4, -7.4])
			_tractor(st, col, glass, trim)
			var tank: Color = Color(0.80, 0.81, 0.83)                    # brushed steel
			_box(st, Vector3(-1.8, 0.9, 0.0), Vector3(12.2, 0.5, 1.1), trim)      # tank frame
			_tank(st, -7.9, 4.3, 2.15, 1.2, tank)                        # tank barrel
			_box(st, Vector3(-1.8, 3.4, 0.0), Vector3(10.5, 0.08, 0.5), trim)     # top walkway
			_cylinder(st, Vector3(-1.0, 3.32, 0.0), 0.22, 0.32, 8, trim, true, false)   # dome/manhole
			_cylinder(st, Vector3(2.4, 3.32, 0.0), 0.18, 0.28, 8, trim, true, false)
			_box(st, Vector3(-8.0, 1.4, 0.0), Vector3(0.12, 2.2, 2.0), tank.darkened(0.05))  # rear head shield
			_box(st, Vector3(-8.05, 0.7, 0.0), Vector3(0.16, 0.5, 2.1), trim)     # rear underride
			_lights(st, -8.05, 0.85, 0.9, rlight)


# ------------------------------------------------------------------------ vegetation
# Canopy greens keyed by variant so a scatter can mix foliage colour cheaply
# (get_mesh caches per kind:variant, so each colour is one shared mesh).
const TREE_GREENS := [
	Color(0.20, 0.38, 0.19), Color(0.26, 0.44, 0.22), Color(0.16, 0.34, 0.18),
	Color(0.32, 0.46, 0.22), Color(0.22, 0.40, 0.26),
]
const TRUNK_COL := Color(0.34, 0.24, 0.16)


static func _leaf(variant: int, shift: float = 0.0) -> Color:
	var base: Color = TREE_GREENS[((variant % TREE_GREENS.size()) + TREE_GREENS.size()) % TREE_GREENS.size()]
	if shift != 0.0:
		base = base.lerp(Color.WHITE, shift) if shift > 0.0 else base.darkened(-shift)
	return base


## Large broadleaf: a chunky multi-blob canopy on a stout trunk (the default
## street/yard tree). Bigger than before so trees read at isometric distance.
## Rounded shade tree (pecan / cedar elm) — a full ball canopy of overlapping
## lobes on a clear trunk.
static func _build_tree_round(st: SurfaceTool, variant: int = 0) -> void:
	_cylinder(st, Vector3.ZERO, 0.22, 3.0, 6, TRUNK_COL, false, false)
	var c := _leaf(variant)
	# a rounded ball crown from a few overlapping faceted lobes on a clear trunk
	_faceted_ellipsoid(st, Vector3(0.0, 4.1, 0.0), Vector3(1.9, 2.0, 1.9), c.darkened(0.07), 21)
	_faceted_ellipsoid(st, Vector3(0.8, 4.5, 0.2), Vector3(1.3, 1.3, 1.3), c, 22)
	_faceted_ellipsoid(st, Vector3(-0.7, 4.4, -0.3), Vector3(1.2, 1.2, 1.3), c.lerp(Color.WHITE, 0.06), 23)
	_faceted_ellipsoid(st, Vector3(0.1, 5.2, 0.4), Vector3(1.1, 1.1, 1.1), c.lerp(Color.WHITE, 0.11), 24)


## Live oak — short thick trunk and a broad, low, spreading crown (the classic
## Gulf-coast silhouette): wider than tall, many lobes at similar height.
static func _build_tree_oak(st: SurfaceTool, variant: int = 0) -> void:
	# Short thick trunk, then a very broad, low, irregular crown built from wide
	# flattened lobes at similar height (the live-oak silhouette: wider than tall).
	_cylinder(st, Vector3.ZERO, 0.38, 2.2, 8, TRUNK_COL.darkened(0.05), false, false)
	var c := _leaf(variant)
	_faceted_ellipsoid(st, Vector3(0.0, 3.1, 0.0), Vector3(3.0, 1.7, 3.0), c.darkened(0.09), 11)
	_faceted_ellipsoid(st, Vector3(2.0, 3.3, 0.4), Vector3(2.0, 1.4, 2.0), c, 12)
	_faceted_ellipsoid(st, Vector3(-1.9, 3.2, -0.5), Vector3(2.0, 1.4, 2.1), c.lerp(Color.WHITE, 0.05), 13)
	_faceted_ellipsoid(st, Vector3(0.3, 3.6, 2.0), Vector3(1.8, 1.3, 1.8), c.lerp(Color.WHITE, 0.03), 14)
	_faceted_ellipsoid(st, Vector3(-0.3, 3.7, -2.0), Vector3(1.7, 1.3, 1.8), c.darkened(0.04), 15)


## Loblolly pine — tall bare trunk, several stacked conical tiers of decreasing
## radius with gaps between them (a real pine, not a teardrop).
static func _build_tree_conical(st: SurfaceTool, variant: int = 0) -> void:
	var trunk := TRUNK_COL.darkened(0.10)
	_cylinder(st, Vector3.ZERO, 0.18, 3.2, 6, trunk, false, false)
	var leaf := _leaf(variant).darkened(0.04)
	# (base_radius, base_y, height) per tier
	_cone(st, Vector3(0.0, 2.4, 0.0), 2.3, 2.4, 9, leaf, true)
	_cone(st, Vector3(0.0, 4.0, 0.0), 1.9, 2.2, 9, leaf.lerp(Color.WHITE, 0.03), false)
	_cone(st, Vector3(0.0, 5.4, 0.0), 1.4, 2.0, 9, leaf.lerp(Color.WHITE, 0.06), false)
	_cone(st, Vector3(0.0, 6.7, 0.0), 0.9, 1.8, 9, leaf.lerp(Color.WHITE, 0.09), false)


## Narrow columnar (Italian cypress / poplar) — a slim tapered spire.
static func _build_tree_columnar(st: SurfaceTool, variant: int = 0) -> void:
	_cylinder(st, Vector3.ZERO, 0.16, 1.2, 6, TRUNK_COL.darkened(0.05), false, false)
	var leaf := _leaf(variant).darkened(0.03)
	_cone(st, Vector3(0.0, 1.1, 0.0), 0.95, 5.2, 8, leaf, true)
	_cone(st, Vector3(0.0, 4.6, 0.0), 0.6, 3.2, 8, leaf.lerp(Color.WHITE, 0.05), false)


## Willow — rounded crown on a clear trunk with long drooping fronds hanging from
## the canopy edge (unmistakable weeping silhouette).
static func _build_tree_willow(st: SurfaceTool, variant: int = 0) -> void:
	_cylinder(st, Vector3.ZERO, 0.26, 3.2, 6, TRUNK_COL, false, false)
	var c := _leaf(variant, 0.08)   # willows read lighter / yellow-green
	_faceted_ellipsoid(st, Vector3(0.0, 4.2, 0.0), Vector3(2.0, 1.6, 2.0), c.darkened(0.05), 41)
	_faceted_ellipsoid(st, Vector3(0.0, 4.9, 0.0), Vector3(1.3, 1.1, 1.3), c.lerp(Color.WHITE, 0.06), 42)
	# drooping fronds around the crown edge
	for k in range(12):
		var a := TAU * float(k) / 12.0
		var r := 1.9
		var top := Vector3(cos(a) * r, 4.3, sin(a) * r)
		var bot := top + Vector3(cos(a) * 0.5, -2.8, sin(a) * 0.5)
		var side := Vector3(-sin(a), 0.0, cos(a)) * 0.32
		_quad(st, top - side, top + side, bot + side * 0.6, bot - side * 0.6,
			c.lerp(Color.WHITE, 0.03))


## Palm — a leaning trunk topped with radiating fronds (Houston flavour).
static func _build_tree_palm(st: SurfaceTool, variant: int = 0) -> void:
	var trunk := Color(0.40, 0.32, 0.20)
	# a few stacked segments give a slight taper/lean
	for i in range(5):
		var y := float(i) * 1.3
		var off := float(i) * 0.12
		_cylinder(st, Vector3(off, y, 0.0), 0.20 - float(i) * 0.02, 1.35, 6, trunk, false, false)
	var top := Vector3(0.6, 6.5, 0.0)
	var frond := _leaf(variant, 0.08)
	for k in range(7):
		var a := TAU * float(k) / 7.0
		var dir := Vector3(cos(a), -0.15, sin(a))
		var tip := top + dir * 2.6 + Vector3(0.0, 0.2, 0.0)
		var side := Vector3(-sin(a), 0.0, cos(a)) * 0.35
		_quad(st, top - side, top + side, tip + side * 0.25, tip - side * 0.25, frond)


static func _build_bush_round(st: SurfaceTool, variant: int = 0) -> void:
	var leaf := _leaf(variant, 0.02)
	_faceted_ellipsoid(st, Vector3(0.0, 0.55, 0.0), Vector3(0.72, 0.6, 0.72), leaf, 61, 6, 2)
	_faceted_ellipsoid(st, Vector3(0.18, 0.95, -0.1), Vector3(0.5, 0.42, 0.5), leaf.lerp(Color.WHITE, 0.06), 62, 6, 2)


static func _build_bush_low(st: SurfaceTool, variant: int = 0) -> void:
	var leaf := _leaf(variant, 0.03)
	_box(st, Vector3(0.0, 0.35, 0.0), Vector3(1.6, 0.7, 0.9), leaf)


## Southern magnolia — dense, dark, glossy broadleaf; rounded compact crown low
## to the ground on a short trunk.
static func _build_tree_magnolia(st: SurfaceTool, variant: int = 0) -> void:
	_cylinder(st, Vector3.ZERO, 0.26, 1.6, 6, TRUNK_COL.darkened(0.1), false, false)
	var c := _leaf(variant, -0.06)   # darker green
	# dense, compact, roughly pyramidal crown (taller than wide), low branching
	_faceted_ellipsoid(st, Vector3(0.0, 2.9, 0.0), Vector3(1.7, 2.0, 1.7), c.darkened(0.05), 31)
	_faceted_ellipsoid(st, Vector3(0.4, 3.8, 0.2), Vector3(1.2, 1.5, 1.2), c, 32)
	_faceted_ellipsoid(st, Vector3(-0.3, 3.9, -0.2), Vector3(1.1, 1.3, 1.1), c.lerp(Color.WHITE, 0.03), 33)
	_faceted_ellipsoid(st, Vector3(0.0, 4.7, 0.0), Vector3(0.8, 1.0, 0.8), c.lerp(Color.WHITE, 0.05), 34)


## Crape myrtle — small multi-stem ornamental with an airy rounded head; blooms
## give a pink/white tint on some variants.
static func _build_tree_crape_myrtle(st: SurfaceTool, variant: int = 0) -> void:
	var trunk := Color(0.55, 0.45, 0.38)
	for sx in [-0.18, 0.0, 0.18]:
		_cylinder(st, Vector3(sx, 0.0, sx * 0.5), 0.06, 2.2, 5, trunk, false, false)
	var bloom := [Color(0.72, 0.45, 0.6), Color(0.85, 0.82, 0.86), Color(0.6, 0.5, 0.66)]
	var c: Color = _leaf(variant, 0.02).lerp(bloom[variant % bloom.size()], 0.5)
	# small, airy, multi-stem head — obviously much smaller than a live oak
	_faceted_ellipsoid(st, Vector3(0.0, 2.7, 0.0), Vector3(1.0, 1.1, 1.0), c.darkened(0.04), 51)
	_faceted_ellipsoid(st, Vector3(0.35, 3.1, 0.15), Vector3(0.8, 0.8, 0.8), c, 52)
	_faceted_ellipsoid(st, Vector3(-0.35, 3.2, -0.15), Vector3(0.7, 0.75, 0.7), c.lerp(Color.WHITE, 0.06), 53)


## Bald cypress — tall wetland conifer: straight trunk, narrow feathery conical
## crown that broadens near the base (riparian).
static func _build_tree_baldcypress(st: SurfaceTool, variant: int = 0) -> void:
	_cylinder(st, Vector3.ZERO, 0.28, 3.4, 6, TRUNK_COL.darkened(0.08), false, false)
	var leaf := _leaf(variant, 0.04).lerp(Color(0.6, 0.62, 0.4), 0.25)  # feathery yellow-green
	_cone(st, Vector3(0.0, 2.6, 0.0), 2.0, 2.6, 9, leaf, true)
	_cone(st, Vector3(0.0, 4.4, 0.0), 1.5, 2.4, 9, leaf.lerp(Color.WHITE, 0.04), false)
	_cone(st, Vector3(0.0, 6.0, 0.0), 1.0, 2.2, 9, leaf.lerp(Color.WHITE, 0.08), false)


## Clipped hedge — a low boxy run of dense foliage (property lines, borders).
static func _build_hedge(st: SurfaceTool, variant: int = 0) -> void:
	var leaf := _leaf(variant, -0.02)
	_box(st, Vector3(0.0, 0.55, 0.0), Vector3(2.0, 1.1, 0.8), leaf.darkened(0.04))
	_box(st, Vector3(0.0, 1.05, 0.0), Vector3(1.94, 0.2, 0.74), leaf.lerp(Color.WHITE, 0.05))


## Flowering shrub — a rounded bush dotted with small blossoms.
static func _build_flowering_shrub(st: SurfaceTool, variant: int = 0) -> void:
	var leaf := _leaf(variant, 0.0)
	_box(st, Vector3(0.0, 0.5, 0.0), Vector3(1.3, 1.0, 1.3), leaf)
	var bloom: Color = [Color(0.85, 0.4, 0.5), Color(0.9, 0.85, 0.5), Color(0.7, 0.5, 0.8)][variant % 3]
	for p in [Vector3(0.4, 1.0, 0.2), Vector3(-0.3, 0.95, -0.35), Vector3(0.1, 1.05, -0.2),
			Vector3(-0.35, 1.0, 0.3)]:
		_box(st, p, Vector3(0.28, 0.22, 0.28), bloom)


## Tall grass tuft — a few crossed upright blades (ditches / rough ground).
static func _build_tall_grass(st: SurfaceTool, variant: int = 0) -> void:
	var g := _leaf(variant, 0.06).lerp(Color(0.7, 0.68, 0.4), 0.3)
	for a in [0.0, 0.7, 1.5, 2.3, 3.0]:
		var dx := cos(a) * 0.12
		var dz := sin(a) * 0.12
		_quad(st, Vector3(-0.05, 0.0, 0.0), Vector3(0.05, 0.0, 0.0),
			Vector3(dx + 0.03, 1.1, dz), Vector3(dx - 0.03, 1.1, dz), g)


## Native scrub — a low sprawling irregular clump of dry brush.
static func _build_native_scrub(st: SurfaceTool, variant: int = 0) -> void:
	var g := _leaf(variant, -0.04).lerp(Color(0.5, 0.5, 0.34), 0.35)
	_box(st, Vector3(0.0, 0.3, 0.0), Vector3(1.5, 0.6, 1.4), g.darkened(0.05))
	_box(st, Vector3(0.4, 0.5, -0.2), Vector3(0.9, 0.5, 0.9), g)
	_box(st, Vector3(-0.4, 0.45, 0.3), Vector3(0.8, 0.45, 0.8), g.lerp(Color.WHITE, 0.04))
