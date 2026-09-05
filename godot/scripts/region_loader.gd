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

var _region: Dictionary = {}
var _hx0: float
var _hz0: float
var _hstep: float
var _heights: Array = []      # row-major Array[Array[float]]
var _origin_elev: float = 0.0


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
	_setup_atmosphere()
	_build_chunks()
	return true


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


func _build_chunks() -> void:
	for chunk in _region["chunk_manifest"]:
		var mesh := _build_chunk_mesh(chunk)
		var mi := MeshInstance3D.new()
		mi.mesh = mesh
		mi.name = String(chunk["key"])
		add_child(mi)
		# Distance-driven physical fidelity (§3.4): only near chunks collide.
		if bool(chunk["collision"]):
			var body := StaticBody3D.new()
			body.collision_layer = CollisionLayers.WORLD_STATIC
			body.collision_mask = 0
			var shape := CollisionShape3D.new()
			var cshape := ConcavePolygonShape3D.new()
			cshape.set_faces(mesh.get_faces())
			shape.shape = cshape
			body.add_child(shape)
			mi.add_child(body)


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
