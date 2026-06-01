extends Node3D

## Builds the low-poly block city from an Asphodel bundle at runtime.
## Zone blocks are drawn as a single MultiMeshInstance3D of boxes, colored by
## zone density; major roads as line strips; plus a ground plane, a sun, and a
## camera framed to the city. The bundle directory is exported so Phase 3 can
## point it at a freshly generated city.

@export var bundle_dir: String = "res://sample_bundle"
## Blocks come from realistic (small) footprints; scale them up to a readable
## stylized size. Horizontal size is a fraction of the mean cell side.
@export var block_footprint_frac: float = 0.16
@export var block_height_scale: float = 3.0
@export var low_density_color: Color = Color(0.35, 0.45, 0.55)
@export var high_density_color: Color = Color(0.95, 0.85, 0.55)

var _meta: Dictionary
var _zones: Array


func _ready() -> void:
	var bundle := BundleLoader.load_bundle(bundle_dir)
	if bundle.is_empty():
		push_error("city_builder: failed to load bundle at %s — see errors above." % bundle_dir)
		return
	_meta = bundle["meta"]
	_zones = bundle["zones"]
	_add_environment_and_light()
	_build_ground()
	_build_blocks()
	_build_roads(bundle["roads"])
	_frame_camera()
	print("Asphodel: built '%s' — %d zones, %d block instances."
		% [_meta.get("name", "?"), _zones.size(), _count_blocks()])


func _count_blocks() -> int:
	var n := 0
	for z in _zones:
		n += (z.get("blocks", []) as Array).size()
	return n


func _cell_side() -> float:
	var grid: Dictionary = _meta.get("grid", {})
	return float(grid.get("cell_m", 100.0))


func _add_environment_and_light() -> void:
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.07, 0.09, 0.13)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.5, 0.55, 0.6)
	env.ambient_light_energy = 0.5
	var we := WorldEnvironment.new()
	we.environment = env
	add_child(we)

	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-55.0, -45.0, 0.0)
	sun.light_energy = 1.1
	sun.shadow_enabled = true
	add_child(sun)


func _world_bounds() -> Rect2:
	# Axis-aligned XZ bounds of all zone centers (+ half-extent), in meters.
	var min_x := INF
	var min_z := INF
	var max_x := -INF
	var max_z := -INF
	for z in _zones:
		var c: Array = z["center_xy"]
		var e: Array = z["extent"]
		min_x = min(min_x, float(c[0]) - float(e[0]) * 0.5)
		max_x = max(max_x, float(c[0]) + float(e[0]) * 0.5)
		min_z = min(min_z, float(c[1]) - float(e[1]) * 0.5)
		max_z = max(max_z, float(c[1]) + float(e[1]) * 0.5)
	return Rect2(min_x, min_z, max_x - min_x, max_z - min_z)


func _build_ground() -> void:
	var b := _world_bounds()
	var plane := PlaneMesh.new()
	plane.size = Vector2(b.size.x * 1.2, b.size.y * 1.2)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.12, 0.14, 0.17)
	plane.material = mat
	var mi := MeshInstance3D.new()
	mi.mesh = plane
	mi.position = Vector3(b.position.x + b.size.x * 0.5, 0.0, b.position.y + b.size.y * 0.5)
	add_child(mi)


func _build_blocks() -> void:
	# One box mesh, instanced once per block, colored per-instance by density.
	var total := _count_blocks()
	if total == 0:
		return
	var side := _cell_side() * block_footprint_frac

	var box := BoxMesh.new()
	box.size = Vector3(1.0, 1.0, 1.0)  # unit cube; per-instance transform scales it
	var mat := StandardMaterial3D.new()
	mat.vertex_color_use_as_albedo = true  # let per-instance colors show
	mat.roughness = 0.9
	box.material = mat

	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.use_colors = true
	mm.mesh = box
	mm.instance_count = total

	var i := 0
	for z in _zones:
		var density := float(z.get("density", 0.0))
		var col := low_density_color.lerp(high_density_color, clampf(density, 0.0, 1.0))
		for blk in (z.get("blocks", []) as Array):
			var bxy: Array = blk["xy"]
			var h := float(blk["height"]) * block_height_scale
			var basis := Basis().scaled(Vector3(side, h, side))
			var origin := Vector3(float(bxy[0]), h * 0.5, float(bxy[1]))
			mm.set_instance_transform(i, Transform3D(basis, origin))
			mm.set_instance_color(i, col)
			i += 1

	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	add_child(mmi)


func _build_roads(roads: Dictionary) -> void:
	var polylines: Array = roads.get("polylines", [])
	if polylines.is_empty():
		return
	var im := ImmediateMesh.new()
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_color = Color(0.9, 0.9, 0.95)
	for pl in polylines:
		var pts: Array = pl.get("points", [])
		if pts.size() < 2:
			continue
		im.surface_begin(Mesh.PRIMITIVE_LINE_STRIP, mat)
		for p in pts:
			im.surface_add_vertex(Vector3(float(p[0]), 1.0, float(p[1])))
		im.surface_end()
	var mi := MeshInstance3D.new()
	mi.mesh = im
	add_child(mi)


func _frame_camera() -> void:
	var b := _world_bounds()
	var center := Vector3(b.position.x + b.size.x * 0.5, 0.0, b.position.y + b.size.y * 0.5)
	var span := maxf(b.size.x, b.size.y)
	var cam := Camera3D.new()
	cam.far = span * 6.0 + 1000.0
	# Angled bird's-eye view from the +X/+Z corner, looking at the city center.
	var eye := center + Vector3(span * 0.7, span * 0.8, span * 0.7)
	cam.position = eye
	cam.current = true
	add_child(cam)
	cam.look_at(center, Vector3.UP)  # after add_child so global transform is set
