extends Node3D

## Renders horizon screenshots of the baked regional terrain (§14/§20) using the
## OpenGL3 compatibility renderer (software llvmpipe under Xvfb — no GPU needed).
## Builds a lit, elevation-coloured terrain mesh from a bundle's baked heightmap,
## places a sun + aerial-perspective fog, points a camera at the horizon, and
## saves a PNG. Runs several views then quits.

const OUT_DIR := "/home/user/Asphodel/shots"
const GRID := 200          # terrain samples per side (fast software raster)
const HALF := 70000.0      # metres from origin covered each way

const SUN := Vector3(0.45, 0.72, 0.30)   # bake direction for hillshading

var _shots := [
	# Oblique aerial looking WEST and down over the plains to the Front Range.
	{"bundle": "res://bundles/denver_region", "name": "denver_aerial_range",
	 "cam": Vector3(25000, 5000, 0), "look": Vector3(-42000, 1200, 0)},
	# Eye level on the plains looking west at the mountain horizon.
	{"bundle": "res://bundles/denver_region", "name": "denver_eyelevel",
	 "cam": Vector3(8000, 450, 0), "look": Vector3(-60000, 2600, 0)},
	{"bundle": "res://bundles/houston", "name": "houston_flat",
	 "cam": Vector3(0, 400, 8000), "look": Vector3(0, -120, -45000)},
	# Oblique aerial over the flat coastal plain toward the Gulf (water to the SE).
	{"bundle": "res://bundles/houston", "name": "houston_aerial_coast",
	 "cam": Vector3(-22000, 3200, 22000), "look": Vector3(14000, -700, -38000)},
]

var _heights: Array
var _rows: int
var _cols: int
var _hx0: float
var _hz0: float
var _hstep: float


func _ready() -> void:
	DirAccess.make_dir_recursive_absolute(OUT_DIR)
	get_window().size = Vector2i(1600, 900)
	await get_tree().process_frame
	for shot in _shots:
		await _render(shot)
	print("HORIZON_SHOTS_DONE")
	get_tree().quit(0)


func _sample(x: float, z: float) -> float:
	var fx: float = clamp((x - _hx0) / _hstep, 0.0, float(_cols) - 1.0001)
	var fz: float = clamp((z - _hz0) / _hstep, 0.0, float(_rows) - 1.0001)
	var ix := int(fx); var iz := int(fz)
	var tx := fx - ix; var tz := fz - iz
	var r0: Array = _heights[iz]
	var r1: Array = _heights[iz + 1]
	var a: float = float(r0[ix]) + (float(r0[ix + 1]) - float(r0[ix])) * tx
	var b: float = float(r1[ix]) + (float(r1[ix + 1]) - float(r1[ix])) * tx
	return a + (b - a) * tz


func _render(shot: Dictionary) -> void:
	for c in get_children():
		c.queue_free()
	await get_tree().process_frame

	var region: Dictionary = JSON.parse_string(
		FileAccess.get_file_as_string(shot["bundle"].path_join("region.json")))
	var hm: Dictionary = region["heightmap"]
	_heights = hm["heights"]
	_hx0 = hm["x0"]; _hz0 = hm["z0"]; _hstep = hm["step_m"]
	_rows = _heights.size(); _cols = (_heights[0] as Array).size()
	var origin_elev: float = float(region.get("georef", {}).get("origin_elevation", 0.0))
	var sea: Variant = region.get("sea_level", null)
	var has_sea := sea != null
	var seaf: float = float(sea) if has_sea else -1e9
	var stats: Dictionary = region["terrain_stats"]
	var lo: float = stats["min_elevation"]; var hi: float = stats["max_elevation"]
	# Rock/snow only in genuinely mountainous regions — a flat plain's few metres
	# of relief must NOT be painted as snow. Gate on the real relief span.
	var mountainous := (hi - lo) > 400.0
	var rock_line := lo + 0.55 * (hi - lo) if mountainous else 1e9
	var snow_line := lo + 0.80 * (hi - lo) if mountainous else 1e9
	var green := Color(0.38, 0.55, 0.30)
	var tan := Color(0.64, 0.55, 0.40)
	var rock := Color(0.50, 0.47, 0.44)
	var snow := Color(0.95, 0.96, 0.98)
	var water := Color(0.17, 0.36, 0.54)
	var beach := Color(0.82, 0.77, 0.58)

	var L := SUN.normalized()
	var g := 250.0   # gradient sample distance for hillshading
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
			if has_sea and h <= seaf:
				base = water
			elif has_sea and h <= seaf + 4.0:
				base = beach
			elif h >= snow_line:
				base = snow
			elif h >= rock_line:
				base = rock
			else:
				base = green.lerp(tan, clamp((h - lo) / max(1.0, rock_line - lo), 0.0, 1.0))
			# Bake hillshade from the heightmap gradient (renderer-independent).
			var nrm := Vector3(_sample(wx - g, wz) - _sample(wx + g, wz), 2.0 * g,
							   _sample(wx, wz - g) - _sample(wx, wz + g)).normalized()
			var shade: float = 0.42 + 0.72 * maxf(0.0, nrm.dot(L))
			st.set_color(Color(minf(base.r * shade, 1.0), minf(base.g * shade, 1.0),
							   minf(base.b * shade, 1.0)))
			st.add_vertex(Vector3(wx, h - origin_elev, wz))
	for iz in range(GRID):
		for ix in range(GRID):
			var a := iz * n + ix
			st.add_index(a); st.add_index(a + n); st.add_index(a + 1)
			st.add_index(a + 1); st.add_index(a + n); st.add_index(a + n + 1)
	var mi := MeshInstance3D.new()
	mi.mesh = st.commit()
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.vertex_color_use_as_albedo = true
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED   # never cull the terrain surface
	mi.material_override = mat
	add_child(mi)

	# Terrain brightness is baked into vertex colours (unshaded), so we only need
	# a sky and aerial-perspective fog here.
	var env := Environment.new()
	env.background_mode = Environment.BG_SKY
	env.sky = Sky.new()
	var sky_mat := ProceduralSkyMaterial.new()
	sky_mat.sky_top_color = Color(0.42, 0.58, 0.82)
	sky_mat.sky_horizon_color = Color(0.74, 0.82, 0.92)
	sky_mat.ground_horizon_color = Color(0.74, 0.82, 0.92)
	sky_mat.ground_bottom_color = Color(0.74, 0.82, 0.92)   # not the default dark brown
	env.sky.sky_material = sky_mat
	env.fog_enabled = true
	env.fog_light_color = Color(0.74, 0.82, 0.92)
	env.fog_density = 0.0000042
	env.fog_aerial_perspective = 1.0
	var we := WorldEnvironment.new()
	we.environment = env
	add_child(we)

	var cam := Camera3D.new()
	cam.far = 220000.0
	cam.fov = 70.0
	add_child(cam)
	cam.global_position = shot["cam"]
	cam.look_at(shot["look"], Vector3.UP)

	for _i in range(5):
		await get_tree().process_frame
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	var path := OUT_DIR.path_join(shot["name"] + ".png")
	img.save_png(path)
	print("SHOT %s -> %s (%dx%d)" % [shot["name"], path, img.get_width(), img.get_height()])
