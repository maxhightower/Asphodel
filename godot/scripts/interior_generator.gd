class_name InteriorGenerator
extends RefCounted

## Procedurally furnishes the inside of an enterable building. Works in the
## building's local space (origin = footprint center, floor at y=0):
##  - floor + ceiling caps cut to the real footprint polygon
##  - partition walls (with doorways) splitting the footprint into rooms
##  - furniture per room chosen by the building's OSM kind
##  - lootable containers stocked from per-kind loot tables
## Deterministic for a given RNG state.

const CEIL_H := 2.9
const WALL_THICK := 0.16
const DOORWAY_W := 1.15

# what a room of each building kind gets filled with (placement order)
const _FURNISH := {
	"house": ["bed", "table", "chair", "chair", "sofa", "fridge", "cabinet", "shelf", "bed", "cabinet"],
	"apartments": ["bed", "table", "chair", "sofa", "fridge", "cabinet", "shelf", "bed"],
	"hotel": ["bed", "bed", "cabinet", "table", "chair", "shelf"],
	"shop": ["counter", "shelf", "shelf", "shelf", "crate", "shelf", "crate"],
	"pharmacy": ["counter", "shelf", "shelf", "cabinet", "crate"],
	"restaurant": ["counter", "table", "chair", "chair", "table", "chair", "chair", "fridge", "crate"],
	"commercial": ["counter", "desk", "shelf", "shelf", "crate", "cabinet"],
	"office": ["desk", "chair", "desk", "chair", "cabinet", "shelf", "desk", "chair"],
	"civic": ["desk", "chair", "shelf", "cabinet", "table", "chair"],
	"school": ["desk", "chair", "desk", "chair", "desk", "chair", "shelf", "cabinet"],
	"hospital": ["bed", "bed", "cabinet", "desk", "chair", "shelf", "cabinet"],
	"industrial": ["crate", "crate", "crate", "shelf", "counter", "crate"],
	"garage": ["crate", "shelf", "crate"],
	"generic": ["table", "chair", "crate", "shelf", "cabinet"],
}


static func generate(parent: Node3D, poly: PackedVector2Array, kind: String,
		style: CityStyle, rng: RandomNumberGenerator, door_local: Vector2) -> void:
	var aabb := _poly_aabb(poly)
	_add_cap(parent, poly, 0.02, style.interior_floor, true)
	_add_cap(parent, poly, CEIL_H, style.interior_wall.darkened(0.1), false)

	# partition along the longer axis into rooms
	var along_x := aabb.size.x >= aabb.size.y   # split lines perpendicular to x
	var span := aabb.size.x if along_x else aabb.size.y
	var lo := aabb.position.x if along_x else aabb.position.y
	var splits: Array[float] = []
	var pos := lo + rng.randf_range(4.2, 6.5)
	while pos < lo + span - 3.5:
		splits.append(pos)
		pos += rng.randf_range(4.2, 6.5)
	for s in splits:
		_partition_wall(parent, poly, s, along_x, style, rng, door_local)

	_add_lights(parent, aabb, poly)
	_furnish(parent, poly, aabb, splits, along_x, kind, rng)


static func _poly_aabb(poly: PackedVector2Array) -> Rect2:
	var r := Rect2(poly[0], Vector2.ZERO)
	for p in poly:
		r = r.expand(p)
	return r


# ------------------------------------------------------------------- caps
static func _add_cap(parent: Node3D, poly: PackedVector2Array, y: float,
		color: Color, up_face: bool) -> void:
	var idx := Geometry2D.triangulate_polygon(poly)
	if idx.is_empty():
		return
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = color
	mat.roughness = 0.95
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	st.set_material(mat)
	for i in idx:
		st.set_normal(Vector3.UP if up_face else Vector3.DOWN)
		st.add_vertex(Vector3(poly[i].x, y, poly[i].y))
	var mi := MeshInstance3D.new()
	mi.mesh = st.commit()
	parent.add_child(mi)


# --------------------------------------------------------------- partitions
## Wall pieces along the line (x = s) or (y = s), clipped to the footprint,
## each run leaving a doorway so every room stays reachable.
static func _partition_wall(parent: Node3D, poly: PackedVector2Array, s: float,
		along_x: bool, style: CityStyle, rng: RandomNumberGenerator,
		door_local: Vector2) -> void:
	var cuts: Array[float] = []
	var n := poly.size()
	for i in range(n):
		var a := poly[i]
		var b := poly[(i + 1) % n]
		var a_v := a.x if along_x else a.y
		var b_v := b.x if along_x else b.y
		if (a_v - s) * (b_v - s) < 0.0:
			var t := (s - a_v) / (b_v - a_v)
			cuts.append((a.y + t * (b.y - a.y)) if along_x else (a.x + t * (b.x - a.x)))
	cuts.sort()
	var j := 0
	while j + 1 < cuts.size():
		var lo: float = cuts[j] + 0.15
		var hi: float = cuts[j + 1] - 0.15
		j += 2
		if hi - lo < 1.0:
			continue
		var run_len := hi - lo
		# doorway somewhere inside the run (keep clear of the exterior door line)
		var gap_c := (lo + hi) * 0.5
		if run_len > DOORWAY_W + 1.6:
			gap_c = rng.randf_range(lo + 0.8 + DOORWAY_W * 0.5, hi - 0.8 - DOORWAY_W * 0.5)
		var door_axis_v := door_local.y if along_x else door_local.x
		if absf(door_axis_v - gap_c) < 1.0 and run_len > DOORWAY_W + 3.0:
			gap_c = lo + (hi - gap_c)   # mirror it away from the entrance
		_wall_piece(parent, s, lo, gap_c - DOORWAY_W * 0.5, along_x, style)
		_wall_piece(parent, s, gap_c + DOORWAY_W * 0.5, hi, along_x, style)


static func _wall_piece(parent: Node3D, s: float, from_v: float, to_v: float,
		along_x: bool, style: CityStyle) -> void:
	var piece_len := to_v - from_v
	if piece_len < 0.25:
		return
	var body := StaticBody3D.new()
	var mesh := BoxMesh.new()
	var mat := StandardMaterial3D.new()
	mat.albedo_color = style.interior_wall
	mat.roughness = 0.95
	mesh.material = mat
	if along_x:  # wall plane runs along z at x = s
		mesh.size = Vector3(WALL_THICK, CEIL_H, piece_len)
		body.position = Vector3(s, CEIL_H * 0.5, (from_v + to_v) * 0.5)
	else:
		mesh.size = Vector3(piece_len, CEIL_H, WALL_THICK)
		body.position = Vector3((from_v + to_v) * 0.5, CEIL_H * 0.5, s)
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	body.add_child(mi)
	var shape := BoxShape3D.new()
	shape.size = mesh.size
	var cs := CollisionShape3D.new()
	cs.shape = shape
	body.add_child(cs)
	parent.add_child(body)


# ------------------------------------------------------------------- lights
static func _add_lights(parent: Node3D, aabb: Rect2, poly: PackedVector2Array) -> void:
	var count := clampi(int(aabb.get_area() / 45.0), 1, 4)
	for k in range(count):
		var t := (k + 0.5) / float(count)
		var p := Vector2(
			aabb.position.x + aabb.size.x * (t if aabb.size.x >= aabb.size.y else 0.5),
			aabb.position.y + aabb.size.y * (t if aabb.size.x < aabb.size.y else 0.5))
		if not Geometry2D.is_point_in_polygon(p, poly):
			p = aabb.get_center()
		var light := OmniLight3D.new()
		light.position = Vector3(p.x, CEIL_H - 0.25, p.y)
		light.light_color = Color(1.0, 0.93, 0.82)
		light.light_energy = 2.2
		light.omni_range = 9.0
		light.shadow_enabled = false
		parent.add_child(light)


# ---------------------------------------------------------------- furniture
static func _furnish(parent: Node3D, poly: PackedVector2Array, aabb: Rect2,
		splits: Array[float], along_x: bool, kind: String,
		rng: RandomNumberGenerator) -> void:
	var pieces: Array = _FURNISH.get(kind, _FURNISH["generic"])
	# room bands between consecutive split lines (plus the two outer bands)
	var bounds: Array[float] = []
	bounds.append((aabb.position.x if along_x else aabb.position.y))
	for s in splits:
		bounds.append(s)
	bounds.append((aabb.end.x if along_x else aabb.end.y))

	var placed: Array = []   # [Vector2 center, float radius]
	var piece_i := 0
	for r in range(bounds.size() - 1):
		var band_lo: float = bounds[r] + 0.9
		var band_hi: float = bounds[r + 1] - 0.9
		if band_hi - band_lo < 1.2:
			continue
		var per_room := 2 + rng.randi_range(0, 2)
		for _k in range(per_room):
			var piece: String = pieces[piece_i % pieces.size()]
			piece_i += 1
			var fp := FurnitureFactory.footprint_of(piece)
			var rad := maxf(fp.x, fp.y) * 0.55
			for _try in range(10):
				var av := rng.randf_range(band_lo + rad, band_hi - rad)
				var bv := rng.randf_range(
					(aabb.position.y if along_x else aabb.position.x) + rad + 0.6,
					(aabb.end.y if along_x else aabb.end.x) - rad - 0.6)
				var p := Vector2(av, bv) if along_x else Vector2(bv, av)
				if not _clear_spot(p, rad, poly, placed):
					continue
				var node := FurnitureFactory.make(piece)
				if node is Lootable:
					(node as Lootable).loot = _roll_loot(piece, kind, rng)
				node.position = Vector3(p.x, 0.0, p.y)
				node.rotation.y = PI * 0.5 * rng.randi_range(0, 3)
				parent.add_child(node)
				placed.append([p, rad])
				break


static func _clear_spot(p: Vector2, rad: float, poly: PackedVector2Array,
		placed: Array) -> bool:
	# the piece plus a walkable margin must sit fully inside the footprint
	for off in [Vector2.ZERO, Vector2(rad, 0), Vector2(-rad, 0), Vector2(0, rad), Vector2(0, -rad)]:
		if not Geometry2D.is_point_in_polygon(p + off * 1.4, poly):
			return false
	for entry in placed:
		if p.distance_to(entry[0]) < rad + float(entry[1]) + 0.5:
			return false
	return true


# -------------------------------------------------------------------- loot
static func _roll_loot(piece: String, kind: String, rng: RandomNumberGenerator) -> Dictionary:
	var loot := {}
	match piece:
		"fridge":
			loot = {"food": rng.randi_range(1, 3), "water": rng.randi_range(0, 2)}
		"counter":
			loot = {"valuables": rng.randi_range(0, 2), "food": rng.randi_range(0, 1)}
		"shelf":
			match kind:
				"pharmacy", "hospital":
					loot = {"meds": rng.randi_range(1, 3)}
				"shop", "restaurant":
					loot = {"food": rng.randi_range(1, 3), "water": rng.randi_range(0, 2)}
				"industrial", "garage":
					loot = {"materials": rng.randi_range(1, 3)}
				_:
					loot = {"materials": rng.randi_range(0, 2), "food": rng.randi_range(0, 1)}
		"cabinet":
			loot = {"meds": rng.randi_range(0, 2), "valuables": rng.randi_range(0, 1)}
		"desk":
			loot = {"valuables": rng.randi_range(0, 1), "materials": rng.randi_range(0, 1)}
		"crate":
			loot = {"materials": rng.randi_range(1, 4)}
		_:
			loot = {"materials": 1}
	# drop zero entries so the pickup toast reads clean
	var out := {}
	for k in loot:
		if int(loot[k]) > 0:
			out[k] = int(loot[k])
	if out.is_empty():
		out = {"materials": 1}
	return out
