extends Node3D

## Renders the morning-commute playback (§19/§25): the detailed city on its
## terrain, with citizens and cars moving along the streets and congested roads
## lighting up, captured one PNG per playback frame (assembled into a GIF offline).
## Software GL under Xvfb — no GPU. Terrain/city are built once; only the moving
## agents + congestion overlay are rebuilt each frame.

const OUT_DIR := "/home/user/Asphodel/shots/living"
const BUNDLE := "res://bundles/boulder"
const GRID := 200
const HALF := 60000.0
const SUN := Vector3(0.48, 0.72, 0.30)
const PED_R := 9.0        # exaggerated so map-scale agents are visible
const CAR_S := Vector3(22, 9, 22)

var _heights: Array
var _rows: int
var _cols: int
var _hx0: float
var _hz0: float
var _hstep: float
var _origin_elev: float
var _lo: float
var _hi: float
var _water := {}
var _nodes := {}          # id -> Vector2 (for congestion overlay)
var _seg := {}            # id -> [Vector2 a, Vector2 b]
var _frames := []
var _agents_node: Node3D
var _ped_mesh: SphereMesh
var _car_mesh: BoxMesh


func _ready() -> void:
	DirAccess.make_dir_recursive_absolute(OUT_DIR)
	get_window().size = Vector2i(960, 540)
	await get_tree().process_frame
	_load_all()
	_build_terrain_mesh()
	_build_city_static()
	_setup_env()
	_setup_camera()
	_ped_mesh = SphereMesh.new(); _ped_mesh.radius = PED_R; _ped_mesh.height = PED_R * 2.0
	_car_mesh = BoxMesh.new(); _car_mesh.size = CAR_S
	_agents_node = Node3D.new(); add_child(_agents_node)

	for i in range(_frames.size()):
		_draw_frame(_frames[i])
		for _k in range(2):
			await get_tree().process_frame
		await RenderingServer.frame_post_draw
		var img := get_viewport().get_texture().get_image()
		img.save_png(OUT_DIR.path_join("frame_%04d.png" % i))
	print("LIVING_CITY_DONE frames=%d" % _frames.size())
	get_tree().quit(0)


func _load_all() -> void:
	var region: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(BUNDLE.path_join("region.json")))
	var hm: Dictionary = region["heightmap"]
	_heights = hm["heights"]; _hx0 = hm["x0"]; _hz0 = hm["z0"]; _hstep = hm["step_m"]
	_rows = _heights.size(); _cols = (_heights[0] as Array).size()
	_origin_elev = float(region.get("georef", {}).get("origin_elevation", 0.0))
	_lo = region["terrain_stats"]["min_elevation"]; _hi = region["terrain_stats"]["max_elevation"]
	for rc in region.get("water_cells", []):
		_water["%d_%d" % [int(rc[0]), int(rc[1])]] = true
	var mob: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(BUNDLE.path_join("mobility.json")))
	for nid in mob["nodes"]:
		var p: Array = mob["nodes"][nid]
		_nodes[nid] = Vector2(p[0], p[1])
	for s in mob["segments"]:
		if s["u"] != null and s["v"] != null:
			_seg[s["id"]] = [_nodes[s["u"]], _nodes[s["v"]]]
	var pb: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(BUNDLE.path_join("playback.json")))
	_frames = pb["frames"]


func _sample(x: float, z: float) -> float:
	var fx: float = clamp((x - _hx0) / _hstep, 0.0, float(_cols) - 1.0001)
	var fz: float = clamp((z - _hz0) / _hstep, 0.0, float(_rows) - 1.0001)
	var ix := int(fx); var iz := int(fz); var tx := fx - ix; var tz := fz - iz
	var r0: Array = _heights[iz]; var r1: Array = _heights[iz + 1]
	var a: float = float(r0[ix]) + (float(r0[ix + 1]) - float(r0[ix])) * tx
	var b: float = float(r1[ix]) + (float(r1[ix + 1]) - float(r1[ix])) * tx
	return a + (b - a) * tz


func terrain_y(x: float, z: float) -> float:
	return _sample(x, z) - _origin_elev


func _is_water(x: float, z: float) -> bool:
	return _water.has("%d_%d" % [int(round((z - _hz0) / _hstep)), int(round((x - _hx0) / _hstep))])


func _unshaded(mesh: Mesh) -> MeshInstance3D:
	var mi := MeshInstance3D.new(); mi.mesh = mesh
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.vertex_color_use_as_albedo = true
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	mi.material_override = mat
	add_child(mi)
	return mi


func _build_terrain_mesh() -> void:
	var L := SUN.normalized()
	var mountainous := (_hi - _lo) > 400.0
	var rock_line := 2300.0 if mountainous else 1e9
	var snow_line := 2750.0 if mountainous else 1e9
	var green := Color(0.36, 0.50, 0.28); var tan := Color(0.60, 0.52, 0.38)
	var rock := Color(0.48, 0.45, 0.42); var snow := Color(0.95, 0.96, 0.98)
	var g := 220.0
	var st := SurfaceTool.new(); st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var n := GRID + 1; var step := (2.0 * HALF) / GRID
	for iz in range(n):
		var wz := -HALF + iz * step
		for ix in range(n):
			var wx := -HALF + ix * step
			var h := _sample(wx, wz); var y := h - _origin_elev
			var base: Color; var sh := 1.0
			if _is_water(wx, wz):
				base = Color(0.16, 0.34, 0.52); y -= 2.0
			else:
				if h >= snow_line: base = snow
				elif h >= rock_line: base = rock
				else: base = green.lerp(tan, clamp((h - _lo) / max(1.0, rock_line - _lo), 0.0, 1.0))
				var nrm := Vector3(_sample(wx - g, wz) - _sample(wx + g, wz), 2.0 * g,
								   _sample(wx, wz - g) - _sample(wx, wz + g)).normalized()
				sh = 0.45 + 0.70 * maxf(0.0, nrm.dot(L))
			st.set_color(Color(minf(base.r * sh, 1), minf(base.g * sh, 1), minf(base.b * sh, 1)))
			st.add_vertex(Vector3(wx, y, wz))
	for iz in range(GRID):
		for ix in range(GRID):
			var a := iz * n + ix
			st.add_index(a); st.add_index(a + n); st.add_index(a + 1)
			st.add_index(a + 1); st.add_index(a + n); st.add_index(a + n + 1)
	_unshaded(st.commit())


func _build_city_static() -> void:
	var L := SUN.normalized()
	var zones: Array = JSON.parse_string(FileAccess.get_file_as_string(BUNDLE.path_join("zones.json")))
	var st := SurfaceTool.new(); st.begin(Mesh.PRIMITIVE_TRIANGLES)
	for zone in zones:
		for blk in zone["blocks"]:
			var xy: Array = blk["xy"]; var w: float = float(blk["footprint"]); var hgt: float = float(blk["height"])
			_add_box(st, Vector3(xy[0], terrain_y(xy[0], xy[1]) + hgt * 0.5, xy[1]), Vector3(w, hgt, w), Color(0.67, 0.67, 0.70), L)
	_unshaded(st.commit())
	# base street grid (dark), from mobility segments, draped on terrain
	var rst := SurfaceTool.new(); rst.begin(Mesh.PRIMITIVE_TRIANGLES)
	for sid in _seg:
		var e: Array = _seg[sid]
		_add_ribbon(rst, e[0], e[1], 5.0, Color(0.24, 0.24, 0.26), 0.4)
	_unshaded(rst.commit())


func _draw_frame(fr: Dictionary) -> void:
	for c in _agents_node.get_children():
		c.queue_free()
	# congested roads glow red on top of the base grid
	var cong: Dictionary = {}
	for c in fr["congestion"]:
		cong[c[0]] = float(c[1])
	if cong.size() > 0:
		var rst := SurfaceTool.new(); rst.begin(Mesh.PRIMITIVE_TRIANGLES)
		for sid in cong:
			if _seg.has(sid):
				var e: Array = _seg[sid]
				var f: float = clamp((cong[sid] - 1.0) / 0.8, 0.0, 1.0)
				_add_ribbon(rst, e[0], e[1], 9.0, Color(0.85, 0.25 * (1.0 - f), 0.12), 1.2)
		var mi := _unshaded(rst.commit())
		_reparent(mi)
	# moving agents: only those EN_ROUTE (state == 1)
	_draw_markers(fr["peds"], _ped_mesh, Color(0.20, 0.45, 0.95), PED_R)
	_draw_markers(fr["cars"], _car_mesh, Color(0.98, 0.55, 0.10), CAR_S.y * 0.5)


func _draw_markers(rows: Array, mesh: Mesh, color: Color, half_h: float) -> void:
	var pts := []
	for r in rows:
		if int(r[2]) == 1:            # EN_ROUTE
			pts.append(Vector2(r[0], r[1]))
	if pts.is_empty():
		return
	var mm := MultiMesh.new(); mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.mesh = mesh; mm.instance_count = pts.size()
	for i in range(pts.size()):
		var p: Vector2 = pts[i]
		mm.set_instance_transform(i, Transform3D(Basis(), Vector3(p.x, terrain_y(p.x, p.y) + half_h + 1.0, p.y)))
	var mmi := MultiMeshInstance3D.new(); mmi.multimesh = mm
	var mat := StandardMaterial3D.new(); mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_color = color
	mmi.material_override = mat
	_agents_node.add_child(mmi)


func _reparent(mi: MeshInstance3D) -> void:
	mi.get_parent().remove_child(mi)
	_agents_node.add_child(mi)


func _add_box(st: SurfaceTool, c: Vector3, s: Vector3, base: Color, L: Vector3) -> void:
	var hx := s.x * 0.5; var hy := s.y * 0.5; var hz := s.z * 0.5
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
		for vi in [0, 1, 2, 0, 2, 3]:
			st.set_color(col); st.add_vertex(c + q[vi])


func _add_ribbon(st: SurfaceTool, a: Vector2, b: Vector2, width: float, col: Color, lift: float) -> void:
	var perp := (b - a).orthogonal().normalized() * (width * 0.5)
	var y0 := terrain_y(a.x, a.y) + lift
	var y1 := terrain_y(b.x, b.y) + lift
	var v00 := Vector3(a.x - perp.x, y0, a.y - perp.y); var v01 := Vector3(a.x + perp.x, y0, a.y + perp.y)
	var v10 := Vector3(b.x - perp.x, y1, b.y - perp.y); var v11 := Vector3(b.x + perp.x, y1, b.y + perp.y)
	for v in [v00, v01, v11, v00, v11, v10]:
		st.set_color(col); st.add_vertex(v)


func _setup_env() -> void:
	var env := Environment.new(); env.background_mode = Environment.BG_SKY; env.sky = Sky.new()
	var sm := ProceduralSkyMaterial.new()
	sm.sky_top_color = Color(0.40, 0.56, 0.82); sm.sky_horizon_color = Color(0.74, 0.82, 0.92)
	sm.ground_horizon_color = Color(0.74, 0.82, 0.92); sm.ground_bottom_color = Color(0.74, 0.82, 0.92)
	env.sky.sky_material = sm
	env.fog_enabled = true; env.fog_light_color = Color(0.74, 0.82, 0.92)
	env.fog_density = 0.0000040; env.fog_aerial_perspective = 1.0
	var we := WorldEnvironment.new(); we.environment = env; add_child(we)


func _setup_camera() -> void:
	var gy := terrain_y(1200.0, 0.0)
	var cam := Camera3D.new(); cam.far = 200000.0; cam.fov = 64.0; add_child(cam)
	cam.global_position = Vector3(3400, gy + 520, 2400)
	cam.look_at(Vector3(-3500, gy + 200, -600), Vector3.UP)
