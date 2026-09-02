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
	# Glossier + slightly metallic so car bodies catch light instead of reading as
	# flat matte boxes. Back-face culled (vehicle meshes are closed + correctly wound)
	# so interior faces don't wash out the shading.
	if _mat_vehicle == null:
		_mat_vehicle = StandardMaterial3D.new()
		_mat_vehicle.vertex_color_use_as_albedo = true
		_mat_vehicle.roughness = 0.4
		_mat_vehicle.metallic = 0.35
		_mat_vehicle.cull_mode = BaseMaterial3D.CULL_BACK
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


## Returns a cached ArrayMesh for `kind` (see the match in `_build` for the
## full list of supported kinds). `variant` only affects vehicle body colour;
## non-vehicle kinds ignore it but it still participates in the cache key.
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
			_build_mailbox(st)
		"garbage_bin":
			_build_bin(st, Color(0.09, 0.22, 0.12), Color(0.14, 0.30, 0.17))
		"recycling_bin":
			_build_bin(st, Color(0.10, 0.16, 0.32), Color(0.15, 0.23, 0.42))
		"fire_hydrant":
			_build_fire_hydrant(st)
		"utility_pole":
			_build_utility_pole(st)
		"streetlight":
			_build_streetlight(st)
		"traffic_sign":
			_build_traffic_sign(st)
		"traffic_signal":
			_build_traffic_signal(st)
		"guardrail":
			_build_guardrail(st)
		"bollard":
			_build_bollard(st)
		"transformer_box":
			_build_transformer_box(st)
		"utility_cabinet":
			_box(st, Vector3(0.0, 0.6, 0.0), Vector3(0.6, 1.2, 0.4), Color(0.45, 0.46, 0.48))
		"ac_condenser":
			_build_ac_condenser(st)
		"rooftop_hvac":
			_box(st, Vector3(0.0, 0.5, 0.0), Vector3(2.0, 1.0, 1.5), Color(0.55, 0.56, 0.58))
		"dumpster":
			_build_dumpster(st)
		"parking_stop":
			_box(st, Vector3(0.0, 0.075, 0.0), Vector3(1.8, 0.15, 0.15), Color(0.6, 0.6, 0.58))
		"bench":
			_build_bench(st)
		"bus_shelter":
			_build_bus_shelter(st)
		"wood_fence":
			_build_wood_fence(st)
		"pallet":
			_build_pallet(st)
		"road_barrier":
			_build_road_barrier(st)
		"sedan", "suv", "pickup", "van", "box_truck":
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
		"bush_round":
			_build_bush_round(st, variant)
		"bush_low":
			_build_bush_low(st, variant)
		_:
			# Unknown kind: an obvious magenta box rather than a silent crash.
			_box(st, Vector3(0.0, 0.5, 0.0), Vector3(0.5, 1.0, 0.5), Color(1.0, 0.0, 1.0))
	st.generate_normals()
	var mesh := st.commit()
	var vehicle_kinds := {"sedan": true, "suv": true, "pickup": true, "van": true, "box_truck": true}
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


## A single flat two-sided quad (its own two triangles), useful for thin
## rails/panels where a full box would be overkill. `p0..p3` must wind CCW
## as seen from the side the normal should face; cull is disabled anyway so
## a reversed panel still renders, just from generate_normals()'s call.
static func _quad(st: SurfaceTool, p0: Vector3, p1: Vector3, p2: Vector3, p3: Vector3, color: Color) -> void:
	st.set_color(color)
	st.add_vertex(p0); st.add_vertex(p1); st.add_vertex(p2)
	st.add_vertex(p0); st.add_vertex(p2); st.add_vertex(p3)


# ------------------------------------------------------------------- street furniture
static func _build_mailbox(st: SurfaceTool) -> void:
	var post_col := Color(0.30, 0.30, 0.33)
	var box_col := Color(0.22, 0.26, 0.34)
	_cylinder(st, Vector3.ZERO, 0.04, 1.0, 6, post_col, true, false)
	_box(st, Vector3(0.0, 1.075, 0.05), Vector3(0.16, 0.15, 0.38), box_col)


static func _build_bin(st: SurfaceTool, body_col: Color, lip_col: Color) -> void:
	_box(st, Vector3(0.0, 0.5, 0.0), Vector3(0.6, 1.0, 0.6), body_col)
	_box(st, Vector3(0.0, 1.02, 0.0), Vector3(0.66, 0.08, 0.66), lip_col)


static func _build_fire_hydrant(st: SurfaceTool) -> void:
	var col := Color(0.55, 0.12, 0.10)
	var dark := Color(0.35, 0.08, 0.07)
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


static func _build_streetlight(st: SurfaceTool) -> void:
	var col := Color(0.22, 0.23, 0.25)
	_cylinder(st, Vector3.ZERO, 0.08, 6.0, 6, col, true, false)
	_box(st, Vector3(0.7, 5.95, 0.0), Vector3(1.4, 0.08, 0.08), col)
	_box(st, Vector3(1.4, 5.78, 0.0), Vector3(0.30, 0.22, 0.30), Color(0.15, 0.16, 0.18))


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


static func _build_bollard(st: SurfaceTool) -> void:
	var col := Color(0.12, 0.12, 0.14)
	_cylinder(st, Vector3.ZERO, 0.10, 0.85, 8, col, false, true)
	_cone(st, Vector3(0.0, 0.85, 0.0), 0.10, 0.05, 8, col, false)


static func _build_transformer_box(st: SurfaceTool) -> void:
	var col := Color(0.55, 0.62, 0.52)
	_box(st, Vector3(0.0, 0.5, 0.0), Vector3(1.2, 1.0, 1.0), col)
	_box(st, Vector3(0.0, 1.03, 0.0), Vector3(1.24, 0.06, 1.04), col.darkened(0.2))


static func _build_ac_condenser(st: SurfaceTool) -> void:
	var col := Color(0.72, 0.72, 0.70)
	var top := Color(0.52, 0.52, 0.50)
	_box(st, Vector3(0.0, 0.35, 0.0), Vector3(0.8, 0.7, 0.8), col)
	_box(st, Vector3(0.0, 0.72, 0.0), Vector3(0.82, 0.06, 0.82), top)


static func _build_dumpster(st: SurfaceTool) -> void:
	var col := Color(0.08, 0.20, 0.11)
	var lid := Color(0.12, 0.26, 0.15)
	_box(st, Vector3(0.0, 0.65, 0.0), Vector3(1.8, 1.3, 1.2), col)
	_box(st, Vector3(0.0, 1.36, 0.0), Vector3(1.85, 0.12, 1.25), lid)
	_box(st, Vector3(0.0, 1.48, 0.0), Vector3(0.20, 0.12, 1.25), lid.darkened(0.1))


static func _build_bench(st: SurfaceTool) -> void:
	var wood := Color(0.45, 0.30, 0.16)
	var metal := Color(0.20, 0.20, 0.22)
	_box(st, Vector3(0.0, 0.45, 0.0), Vector3(1.6, 0.05, 0.4), wood)
	_box(st, Vector3(0.0, 0.75, -0.17), Vector3(1.6, 0.35, 0.05), wood)
	_box(st, Vector3(-0.7, 0.225, 0.0), Vector3(0.08, 0.45, 0.36), metal)
	_box(st, Vector3(0.7, 0.225, 0.0), Vector3(0.08, 0.45, 0.36), metal)


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


static func _build_wood_fence(st: SurfaceTool) -> void:
	var post := Color(0.4, 0.28, 0.16)
	var plank := Color(0.55, 0.40, 0.24)
	_box(st, Vector3(-1.0, 0.6, 0.0), Vector3(0.10, 1.2, 0.10), post)
	_box(st, Vector3(1.0, 0.6, 0.0), Vector3(0.10, 1.2, 0.10), post)
	for i in range(4):
		var y := 0.18 + float(i) * 0.28
		_box(st, Vector3(0.0, y, 0.0), Vector3(2.0, 0.20, 0.04), plank)


static func _build_chainlink_fence() -> ArrayMesh:
	# Frame (opaque surface 0): two posts + a top rail.
	var post_col := Color(0.5, 0.5, 0.52)
	var st_frame := SurfaceTool.new()
	st_frame.begin(Mesh.PRIMITIVE_TRIANGLES)
	_box(st_frame, Vector3(-1.0, 0.9, 0.0), Vector3(0.06, 1.8, 0.06), post_col)
	_box(st_frame, Vector3(1.0, 0.9, 0.0), Vector3(0.06, 1.8, 0.06), post_col)
	_box(st_frame, Vector3(0.0, 1.8, 0.0), Vector3(2.0, 0.05, 0.05), post_col)
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


static func _wheels(st: SurfaceTool, xs: Array, z: float, y: float, size: Vector3) -> void:
	for x in xs:
		_box(st, Vector3(x, y, z), size, WHEEL_COLOR)
		_box(st, Vector3(x, y, -z), size, WHEEL_COLOR)


static func _build_vehicle(st: SurfaceTool, kind: String, variant: int) -> void:
	var col := _vehicle_color(variant)
	var glass := Color(0.18, 0.20, 0.24)
	match kind:
		"sedan":
			_box(st, Vector3(0.0, 0.45, 0.0), Vector3(4.5, 0.7, 1.8), col)
			_box(st, Vector3(-0.2, 0.95, 0.0), Vector3(2.2, 0.55, 1.5), glass.lerp(col, 0.4))
			_wheels(st, [-1.5, 1.5], 0.85, 0.20, Vector3(0.4, 0.4, 0.28))
		"suv":
			_box(st, Vector3(0.0, 0.5, 0.0), Vector3(4.8, 1.0, 1.9), col)
			_box(st, Vector3(-0.1, 1.35, 0.0), Vector3(4.0, 0.9, 1.85), col.lerp(Color.WHITE, 0.05))
			_wheels(st, [-1.7, 1.7], 0.9, 0.225, Vector3(0.45, 0.45, 0.30))
		"pickup":
			_box(st, Vector3(0.0, 0.35, 0.0), Vector3(5.2, 0.6, 1.85), col.darkened(0.1))
			_box(st, Vector3(-1.2, 1.0, 0.0), Vector3(2.0, 1.0, 1.8), col)
			_box(st, Vector3(1.0, 0.55, 0.0), Vector3(2.6, 0.15, 1.8), col.darkened(0.15))
			_box(st, Vector3(1.0, 0.75, 0.85), Vector3(2.6, 0.4, 0.10), col.darkened(0.15))
			_box(st, Vector3(1.0, 0.75, -0.85), Vector3(2.6, 0.4, 0.10), col.darkened(0.15))
			_box(st, Vector3(2.30, 0.75, 0.0), Vector3(0.10, 0.4, 1.8), col.darkened(0.15))
			_wheels(st, [-1.2, 1.4], 0.92, 0.25, Vector3(0.5, 0.5, 0.32))
		"van":
			_box(st, Vector3(0.2, 1.0, 0.0), Vector3(5.0, 1.8, 1.9), col)
			_box(st, Vector3(-2.3, 0.55, 0.0), Vector3(0.6, 0.9, 1.85), col.darkened(0.05))
			_wheels(st, [-1.7, 1.7], 0.92, 0.225, Vector3(0.45, 0.45, 0.30))
		"box_truck":
			_box(st, Vector3(-2.3, 1.0, 0.0), Vector3(1.8, 1.6, 2.1), col)
			_box(st, Vector3(-1.9, 1.7, 0.0), Vector3(0.9, 0.5, 1.9), glass.lerp(col, 0.4))
			_box(st, Vector3(0.9, 1.6, 0.0), Vector3(4.2, 3.0, 2.2), col.lerp(Color.WHITE, 0.15))
			_wheels(st, [-2.1, 0.5, 1.9], 1.0, 0.275, Vector3(0.55, 0.55, 0.34))


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
static func _build_tree_round(st: SurfaceTool, variant: int = 0) -> void:
	_cylinder(st, Vector3.ZERO, 0.22, 3.0, 6, TRUNK_COL, false, false)
	var c := _leaf(variant)
	_box(st, Vector3(0.0, 3.7, 0.0), Vector3(3.0, 1.7, 3.0), c.darkened(0.06))
	_box(st, Vector3(0.5, 4.5, -0.3), Vector3(2.4, 1.5, 2.3), c)
	_box(st, Vector3(-0.4, 4.7, 0.4), Vector3(2.2, 1.4, 2.2), c.lerp(Color.WHITE, 0.05))
	_box(st, Vector3(0.1, 5.4, 0.0), Vector3(1.5, 1.1, 1.5), c.lerp(Color.WHITE, 0.10))


## Big spreading oak — widest canopy, for canopy-cover cells.
static func _build_tree_oak(st: SurfaceTool, variant: int = 0) -> void:
	_cylinder(st, Vector3.ZERO, 0.30, 3.2, 8, TRUNK_COL.darkened(0.05), false, false)
	var c := _leaf(variant)
	_box(st, Vector3(0.0, 4.0, 0.0), Vector3(4.4, 2.0, 4.4), c.darkened(0.08))
	_box(st, Vector3(1.0, 4.8, 0.6), Vector3(3.2, 1.8, 3.0), c)
	_box(st, Vector3(-1.0, 5.0, -0.6), Vector3(3.0, 1.7, 3.2), c.lerp(Color.WHITE, 0.04))
	_box(st, Vector3(0.2, 5.9, 0.2), Vector3(2.2, 1.4, 2.2), c.lerp(Color.WHITE, 0.09))


static func _build_tree_conical(st: SurfaceTool, variant: int = 0) -> void:
	_cylinder(st, Vector3.ZERO, 0.18, 1.4, 6, TRUNK_COL.darkened(0.05), false, false)
	var leaf := _leaf(variant).darkened(0.05)
	_cone(st, Vector3(0.0, 1.3, 0.0), 2.0, 6.6, 9, leaf, true)
	_cone(st, Vector3(0.0, 3.6, 0.0), 1.5, 4.0, 9, leaf.lerp(Color.WHITE, 0.05), false)


static func _build_tree_columnar(st: SurfaceTool, variant: int = 0) -> void:
	_cylinder(st, Vector3.ZERO, 0.16, 1.4, 6, TRUNK_COL.darkened(0.05), false, false)
	_cone(st, Vector3(0.0, 1.3, 0.0), 0.9, 7.8, 8, _leaf(variant), true)


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
	_box(st, Vector3(0.0, 0.45, 0.0), Vector3(1.2, 0.9, 1.2), leaf)
	_box(st, Vector3(0.15, 0.95, -0.1), Vector3(0.8, 0.6, 0.8), leaf.lerp(Color.WHITE, 0.05))


static func _build_bush_low(st: SurfaceTool, variant: int = 0) -> void:
	var leaf := _leaf(variant, 0.03)
	_box(st, Vector3(0.0, 0.35, 0.0), Vector3(1.6, 0.7, 0.9), leaf)
