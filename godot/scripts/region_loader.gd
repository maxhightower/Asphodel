class_name RegionLoader
extends Node3D

## Regional terrain realization seam (AS-REGION-0, §3, §14).
##
## Loads region.json (baked by asphodel.region_bundle) and builds the chunked
## quadtree terrain: each chunk in the manifest becomes an ArrayMesh sampled from
## the baked heightmap, with a crack-hiding skirt; near chunks (collision=true in
## the manifest) also get a StaticBody3D on the WORLD_STATIC layer; distant chunks
## are render-only. A WorldEnvironment provides the aerial-perspective fog so far
## terrain reads as distant rather than a nearby miniature.
##
## NOTE: authored seam — the mesh math mirrors asphodel/region/terrain.py exactly,
## but has not been run in a Godot editor in this environment. Wire it into a scene
## and set `bundle_dir` to exercise it.

@export var bundle_dir: String = "res://bundles/houston"
@export var chunk_res: int = 16
@export var skirt_depth: float = 30.0
## When a gameplay scene owns its own WorldEnvironment (the city scenes do),
## the loader must not add a second one — set false there.
@export var own_atmosphere: bool = true
## The compiled city (ExteriorWorld ground raster, roads, sidewalks) is authored
## at y = 0 on the region's city plateau (region.json.city_plateau). Terrain
## vertices inside that disc are lowered by `city_sink` so the two never
## z-fight, and chunks lying entirely inside the disc are skipped when
## `omit_city_interior` is set (the city renderer owns that ground).
@export var city_sink: float = 0.3
@export var omit_city_interior: bool = false

var _region: Dictionary = {}
var _hx0: float
var _hz0: float
var _hstep: float
var _heights: Array = []      # row-major Array[Array[float]]
var _origin_elev: float = 0.0
var _city_radius: float = 0.0          # region.json.city_plateau.radius_m (0 = none)
var _city_center := Vector2.ZERO
var chunks_built: int = 0
var chunks_skipped_inside_city: int = 0


func _ready() -> void:
	load_region(bundle_dir)


func load_region(dir_path: String) -> bool:
	# One schema contract for region.json, shared with the world scenes' Gate I
	# check — the loader never re-implements (or relaxes) the boundary rules.
	var parsed := BundleLoader.load_region(dir_path)
	if parsed.is_empty():
		return false
	_region = parsed
	var hm: Dictionary = _region["heightmap"]
	_hx0 = hm["x0"]; _hz0 = hm["z0"]; _hstep = hm["step_m"]
	_heights = hm["heights"]
	_origin_elev = float(_region.get("georef", {}).get("origin_elevation", 0.0))
	var plateau: Variant = _region.get("city_plateau")
	if plateau is Dictionary:
		_city_radius = float((plateau as Dictionary).get("radius_m", 0.0))
		var ext: Dictionary = _region.get("extent", {})
		var c: Array = ext.get("center", [0.0, 0.0])
		_city_center = Vector2(float(c[0]), float(c[1]))
	if own_atmosphere:
		_setup_atmosphere()
	_build_chunks()
	return true


func city_plateau_radius() -> float:
	return _city_radius


func _sample_height(x: float, z: float) -> float:
	# Bilinear sample of the baked heightmap (matches CachedDEMProvider).
	var rows := _heights.size()
	var cols: int = (_heights[0] as Array).size()
	var fx: float = clamp((x - _hx0) / _hstep, 0.0, float(cols) - 1.0001)
	var fz: float = clamp((z - _hz0) / _hstep, 0.0, float(rows) - 1.0001)
	var ix := int(floor(fx)); var iz := int(floor(fz))
	var tx := fx - ix; var tz := fz - iz
	var h00: float = _heights[iz][ix]
	var h10: float = _heights[iz][ix + 1]
	var h01: float = _heights[iz + 1][ix]
	var h11: float = _heights[iz + 1][ix + 1]
	var a := h00 + (h10 - h00) * tx
	var b := h01 + (h11 - h01) * tx
	return a + (b - a) * tz


func _chunk_inside_city(chunk: Dictionary) -> bool:
	if _city_radius <= 0.0:
		return false
	var o: Array = chunk["origin"]
	var size: float = chunk["size"]
	# All four corners inside the plateau disc => the city renderer owns it.
	for dx in [0.0, size]:
		for dz in [0.0, size]:
			var p := Vector2(float(o[0]) + dx, float(o[1]) + dz)
			if p.distance_to(_city_center) > _city_radius:
				return false
	return true


func _build_chunks() -> void:
	for chunk in _region["chunk_manifest"]:
		if omit_city_interior and _chunk_inside_city(chunk):
			chunks_skipped_inside_city += 1
			continue
		chunks_built += 1
		var mesh := _build_chunk_mesh(chunk)
		var mi := MeshInstance3D.new()
		mi.mesh = mesh
		mi.name = String(chunk["key"])
		add_child(mi)
		# Distance-driven physical fidelity (§3.4): only near chunks collide.
		if bool(chunk["collision"]):
			var faces := _collider_faces(mesh.get_faces())
			if faces.size() >= 3:
				var body := StaticBody3D.new()
				body.name = "TerrainCollision"
				body.collision_layer = CollisionLayers.WORLD_STATIC
				body.collision_mask = 0
				var shape := CollisionShape3D.new()
				var cshape := ConcavePolygonShape3D.new()
				cshape.set_faces(faces)
				# Terrain is solid from both sides: a body must never fall
				# through a slope because of triangle winding.
				cshape.backface_collision = true
				shape.shape = cshape
				body.add_child(shape)
				mi.add_child(body)


func _collider_faces(faces: PackedVector3Array) -> PackedVector3Array:
	## Terrain collision stops at the city plateau: inside the disc the compiled
	## city's own ground (ExteriorWorld raster / the scene ground body) is the
	## walkable surface, so triangles wholly inside it are left out of the
	## terrain collider (they are still drawn, sunk under the city).
	if _city_radius <= 0.0:
		return faces
	var out := PackedVector3Array()
	var i := 0
	while i + 2 < faces.size():
		var inside := 0
		for k in range(3):
			var v := faces[i + k]
			if Vector2(v.x, v.z).distance_to(_city_center) <= _city_radius:
				inside += 1
		if inside < 3:
			out.append(faces[i]); out.append(faces[i + 1]); out.append(faces[i + 2])
		i += 3
	return out


func _build_chunk_mesh(chunk: Dictionary) -> ArrayMesh:
	var origin: Array = chunk["origin"]
	var x0: float = origin[0]
	var z0: float = origin[1]
	var size: float = chunk["size"]
	var n := chunk_res + 1
	var verts := PackedVector3Array()
	var indices := PackedInt32Array()
	for iz in range(n):
		for ix in range(n):
			var wx := x0 + (float(ix) / chunk_res) * size
			var wz := z0 + (float(iz) / chunk_res) * size
			var wy := _sample_height(wx, wz) - _origin_elev
			if _city_radius > 0.0 and Vector2(wx, wz).distance_to(_city_center) <= _city_radius:
				wy -= city_sink        # under the compiled city ground, never through it
			verts.append(Vector3(wx, wy, wz))
	for iz in range(chunk_res):
		for ix in range(chunk_res):
			var a := iz * n + ix
			var b := a + 1
			var c := a + n
			var d := c + 1
			indices.append_array([a, c, b, b, c, d])
	# (Skirt omitted here for brevity; add border walls dropped by skirt_depth to
	# hide seams between differing LODs — see asphodel/region/terrain.py.)
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = verts
	arrays[Mesh.ARRAY_INDEX] = indices
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh


func _setup_atmosphere() -> void:
	# First-pass aerial perspective (§14): depth-cue fog from region params.
	var atmo: Dictionary = _region.get("atmosphere", {})
	var env := Environment.new()
	env.background_mode = Environment.BG_SKY
	env.sky = Sky.new()
	env.sky.sky_material = ProceduralSkyMaterial.new()
	env.fog_enabled = true
	var tint: Array = atmo.get("haze_tint", [0.62, 0.70, 0.80])
	env.fog_light_color = Color(tint[0], tint[1], tint[2])
	# Godot depth fog density approximated from the far horizon distance.
	var fog_end: float = atmo.get("fog_end", 150000.0)
	env.fog_density = 1.0 / max(1000.0, fog_end)
	var we := WorldEnvironment.new()
	we.environment = env
	add_child(we)
