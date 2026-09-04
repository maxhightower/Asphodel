extends Node3D

## Renders a detailed city sitting on its regional terrain (§19/§20). Builds the
## terrain from the baked heightmap, the buildings from zones.json blocks, and the
## streets from roads.json, then captures street-level and aerial views. Uses the
## OpenGL3 compatibility renderer (software llvmpipe under Xvfb, no GPU). Shading is
## baked into vertex colours so it is renderer-independent.

const OUT_DIR := "/home/user/Asphodel/shots"
const BUNDLE := "res://bundles/boulder"
const GRID := 220
const HALF := 60000.0
const SUN := Vector3(0.48, 0.72, 0.30)

var _heights: Array
var _rows: int
var _cols: int
var _hx0: float
var _hz0: float
var _hstep: float
var _origin_elev: float
var _lo: float
var _hi: float


func _ready() -> void:
	DirAccess.make_dir_recursive_absolute(OUT_DIR)
	get_window().size = Vector2i(1600, 900)
	await get_tree().process_frame
	_load_terrain()
	_build_terrain_mesh()
	_build_city()
	_setup_env()

	var shots := [
		# SIDE PROFILE: look north along the contours so the east->west grade shows
		# in profile — the town visibly climbs left (west, toward the mountains).
		{"name": "boulder_slope_profile",
		 "cam": Vector3(500, terrain_y(500, 4600) + 260, 4600),
		 "look": Vector3(500, terrain_y(500, -1500) + 60, -1500), "fov": 74.0},
		# LOW THREE-QUARTER from the low SE corner looking NW up the grade to
		# downtown and the range — you see the streets rising away from you.
		{"name": "boulder_hillside",
		 "cam": Vector3(5200, terrain_y(5200, 3400) + 90, 3400),
		 "look": Vector3(-2500, terrain_y(-2500, -400) + 260, -400), "fov": 66.0},
		# High oblique showing the street grid and the mountain wall together.
		{"name": "boulder_overhead", "cam": Vector3(2200, terrain_y(2200, 200) + 2400, 200),
		 "look": Vector3(-5000, 200, 0), "fov": 62.0},
		# Above the rooftops looking west up the grade into downtown.
		{"name": "boulder_over_downtown", "cam": Vector3(3600, terrain_y(3600, 120) + 70, 120),
		 "look": Vector3(-6000, 1100, 0), "fov": 70.0},
	]
	for s in shots:
		await _shoot(s)
	print("CITY_SHOTS_DONE")
	get_tree().quit(0)


func _load_terrain() -> void:
	var region: Dictionary = JSON.parse_string(
		FileAccess.get_file_as_string(BUNDLE.path_join("region.json")))
	var hm: Dictionary = region["heightmap"]
	_heights = hm["heights"]; _hx0 = hm["x0"]; _hz0 = hm["z0"]; _hstep = hm["step_m"]
	_rows = _heights.size(); _cols = (_heights[0] as Array).size()
	_origin_elev = float(region.get("georef", {}).get("origin_elevation", 0.0))
	_lo = region["terrain_stats"]["min_elevation"]
	_hi = region["terrain_stats"]["max_elevation"]


func _sample(x: float, z: float) -> float:
	var fx: float = clamp((x - _hx0) / _hstep, 0.0, float(_cols) - 1.0001)
	var fz: float = clamp((z - _hz0) / _hstep, 0.0, float(_rows) - 1.0001)
	var ix := int(fx); var iz := int(fz)
	var tx := fx - ix; var tz := fz - iz
	var r0: Array = _heights[iz]; var r1: Array = _heights[iz + 1]
	var a: float = float(r0[ix]) + (float(r0[ix + 1]) - float(r0[ix])) * tx
	var b: float = float(r1[ix]) + (float(r1[ix + 1]) - float(r1[ix])) * tx
	return a + (b - a) * tz


func terrain_y(x: float, z: float) -> float:
	return _sample(x, z) - _origin_elev


func _build_terrain_mesh() -> void:
	var L := SUN.normalized()
	# Absolute (realistic) treeline/snowline so the range reads as mountains and a
	# flat region never gets snow.
	var mountainous := (_hi - _lo) > 400.0
	var rock_line := 2300.0 if mountainous else 1e9
	var snow_line := 2750.0 if mountainous else 1e9
	var green := Color(0.36, 0.50, 0.28)
	var tan := Color(0.60, 0.52, 0.38)
	var rock := Color(0.48, 0.45, 0.42)
	var snow := Color(0.95, 0.96, 0.98)
	var g := 220.0
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var n := GRID + 1
	var step := (2.0 * HALF) / GRID
	for iz in range(n):
		var wz := -HALF + iz * step
		for ix in range(n):
			var wx := -HALF + ix * step
			var h := _sample(wx, wz)
			var base: Color
			if h >= snow_line:
				base = snow
			elif h >= rock_line:
				base = rock
			else:
				base = green.lerp(tan, clamp((h - _lo) / max(1.0, rock_line - _lo), 0.0, 1.0))
			var nrm := Vector3(_sample(wx - g, wz) - _sample(wx + g, wz), 2.0 * g,
							   _sample(wx, wz - g) - _sample(wx, wz + g)).normalized()
			var sh: float = 0.45 + 0.70 * maxf(0.0, nrm.dot(L))
			st.set_color(Color(minf(base.r * sh, 1), minf(base.g * sh, 1), minf(base.b * sh, 1)))
			st.add_vertex(Vector3(wx, h - _origin_elev, wz))
	for iz in range(GRID):
		for ix in range(GRID):
			var a := iz * n + ix
			st.add_index(a); st.add_index(a + n); st.add_index(a + 1)
			st.add_index(a + 1); st.add_index(a + n); st.add_index(a + n + 1)
	_add_unshaded(st.commit())


func _build_city() -> void:
	var L := SUN.normalized()
	var zones: Array = JSON.parse_string(FileAccess.get_file_as_string(BUNDLE.path_join("zones.json")))
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	for zone in zones:
		for blk in zone["blocks"]:
			var xy: Array = blk["xy"]
			var w: float = float(blk["footprint"])
			var hgt: float = float(blk["height"])
			var base_y := terrain_y(xy[0], xy[1])
			var shade_col := Color(0.67, 0.67, 0.70)
			_add_box(st, Vector3(xy[0], base_y + hgt * 0.5, xy[1]),
					 Vector3(w, hgt, w), shade_col, L)
	_add_unshaded(st.commit())

	# Streets as thin dark ribbons following the terrain.
	var roads: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(BUNDLE.path_join("roads.json")))
	var rst := SurfaceTool.new()
	rst.begin(Mesh.PRIMITIVE_TRIANGLES)
	var road_col := Color(0.22, 0.22, 0.24)
	for pl in roads["polylines"]:
		var pts: Array = pl["points"]
		var a: Array = pts[0]; var b: Array = pts[1]
		var width: float = 7.0 if String(pl["class"]) == "secondary" else 4.5
		_add_ribbon(rst, Vector2(a[0], a[1]), Vector2(b[0], b[1]), width, road_col)
	_add_unshaded(rst.commit())


func _add_box(st: SurfaceTool, c: Vector3, s: Vector3, base: Color, L: Vector3) -> void:
	var hx := s.x * 0.5; var hy := s.y * 0.5; var hz := s.z * 0.5
	# 6 faces, each flat-shaded by its normal for readable building form.
	var faces := [
		[Vector3(0, 1, 0), [Vector3(-hx, hy, -hz), Vector3(-hx, hy, hz), Vector3(hx, hy, hz), Vector3(hx, hy, -hz)]],
		[Vector3(0, 0, 1), [Vector3(-hx, -hy, hz), Vector3(-hx, hy, hz), Vector3(hx, hy, hz), Vector3(hx, -hy, hz)]],
		[Vector3(0, 0, -1), [Vector3(hx, -hy, -hz), Vector3(hx, hy, -hz), Vector3(-hx, hy, -hz), Vector3(-hx, -hy, -hz)]],
		[Vector3(1, 0, 0), [Vector3(hx, -hy, hz), Vector3(hx, hy, hz), Vector3(hx, hy, -hz), Vector3(hx, -hy, -hz)]],
		[Vector3(-1, 0, 0), [Vector3(-hx, -hy, -hz), Vector3(-hx, hy, -hz), Vector3(-hx, hy, hz), Vector3(-hx, -hy, hz)]],
	]
	for face in faces:
		var nrm: Vector3 = face[0]
		var sh: float = 0.40 + 0.70 * maxf(0.0, nrm.dot(L))
		var col := Color(minf(base.r * sh, 1), minf(base.g * sh, 1), minf(base.b * sh, 1))
		var q: Array = face[1]
		st.set_color(col); st.add_vertex(c + q[0])
		st.set_color(col); st.add_vertex(c + q[1])
		st.set_color(col); st.add_vertex(c + q[2])
		st.set_color(col); st.add_vertex(c + q[0])
		st.set_color(col); st.add_vertex(c + q[2])
		st.set_color(col); st.add_vertex(c + q[3])


func _add_ribbon(st: SurfaceTool, a: Vector2, b: Vector2, width: float, col: Color) -> void:
	var steps := 24
	var perp := (b - a).orthogonal().normalized() * (width * 0.5)
	for i in range(steps):
		var t0 := float(i) / steps
		var t1 := float(i + 1) / steps
		var p0 := a.lerp(b, t0)
		var p1 := a.lerp(b, t1)
		var y0 := terrain_y(p0.x, p0.y) + 0.4
		var y1 := terrain_y(p1.x, p1.y) + 0.4
		var v00 := Vector3(p0.x - perp.x, y0, p0.y - perp.y)
		var v01 := Vector3(p0.x + perp.x, y0, p0.y + perp.y)
		var v10 := Vector3(p1.x - perp.x, y1, p1.y - perp.y)
		var v11 := Vector3(p1.x + perp.x, y1, p1.y + perp.y)
		for v in [v00, v01, v11, v00, v11, v10]:
			st.set_color(col); st.add_vertex(v)


func _add_unshaded(mesh: Mesh) -> void:
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.vertex_color_use_as_albedo = true
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	mi.material_override = mat
	add_child(mi)


func _setup_env() -> void:
	var env := Environment.new()
	env.background_mode = Environment.BG_SKY
	env.sky = Sky.new()
	var sm := ProceduralSkyMaterial.new()
	sm.sky_top_color = Color(0.40, 0.56, 0.82)
	sm.sky_horizon_color = Color(0.74, 0.82, 0.92)
	sm.ground_horizon_color = Color(0.74, 0.82, 0.92)
	sm.ground_bottom_color = Color(0.74, 0.82, 0.92)
	env.sky.sky_material = sm
	env.fog_enabled = true
	env.fog_light_color = Color(0.74, 0.82, 0.92)
	env.fog_density = 0.0000040
	env.fog_aerial_perspective = 1.0
	var we := WorldEnvironment.new()
	we.environment = env
	add_child(we)


func _shoot(s: Dictionary) -> void:
	for c in get_children():
		if c is Camera3D:
			c.queue_free()
	var cam := Camera3D.new()
	cam.far = 200000.0
	cam.fov = s["fov"]
	add_child(cam)
	cam.global_position = s["cam"]
	cam.look_at(s["look"], Vector3.UP)
	for _i in range(5):
		await get_tree().process_frame
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	var path := OUT_DIR.path_join(s["name"] + ".png")
	img.save_png(path)
	print("CITYSHOT %s -> %s" % [s["name"], path])
