class_name BuildingBuilder
extends RefCounted

## Builds city buildings from their (OSM or synthesized) footprint polygons.
##
## Far/large buildings become batched extruded shells (walls + roof cap in one
## vertex-colored mesh, plus one trimesh collider). Buildings near the spawn
## point with a sane footprint become ENTERABLE: real perimeter walls with a
## doorway facing the nearest road, a hinged door, and a furnished, lootable
## interior from InteriorGenerator.

const ENTER_RADIUS := 380.0        # only near-spawn buildings get interiors
const MAX_ENTERABLE := 28
const MIN_ENTER_AREA := 35.0
const MAX_ENTER_AREA := 1400.0
const COLLIDE_RADIUS := 1500.0     # trimesh collision for shells inside this
const WALL_H := 2.9                # ground-floor interior height
const DOOR_GAP := 1.5
const DOOR_H := 2.25
const PERIM_THICK := 0.28


static func build_all(parent: Node3D, buildings: Array, style: CityStyle,
		spawn: Vector2, roads: Dictionary) -> Dictionary:
	var shells := SurfaceTool.new()
	shells.begin(Mesh.PRIMITIVE_TRIANGLES)
	var faces := PackedVector3Array()

	# nearest-first so the enterable budget goes to buildings around the player
	var order := buildings.duplicate()
	order.sort_custom(func(a, b):
		return _center(a).distance_squared_to(spawn) < _center(b).distance_squared_to(spawn))

	var n_enterable := 0
	var salt := 0
	for b in order:
		salt += 1
		var poly := _footprint(b)
		if poly.size() < 3:
			continue
		var center := _center(b)
		var dist := center.distance_to(spawn)
		var area := float(b.get("area_m2", 100.0))
		var height := clampf(float(b.get("height", 6.0)), 3.4, 90.0)
		var kind := str(b.get("kind", "generic"))
		var enterable := (
			n_enterable < MAX_ENTERABLE and dist <= ENTER_RADIUS
			and area >= MIN_ENTER_AREA and area <= MAX_ENTER_AREA
			and poly.size() <= 16 and kind != "garage"
		)
		if enterable:
			n_enterable += 1
			parent.add_child(_enterable_building(b, poly, height, style, salt, roads))
		else:
			_shell(shells, faces, poly, height, style, kind, salt,
					dist <= COLLIDE_RADIUS)

	var mat := StandardMaterial3D.new()
	mat.vertex_color_use_as_albedo = true
	mat.vertex_color_is_srgb = true
	mat.roughness = 0.9
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	shells.set_material(mat)
	var mi := MeshInstance3D.new()
	mi.mesh = shells.commit()
	parent.add_child(mi)

	if faces.size() >= 3:
		var body := StaticBody3D.new()
		var shape := ConcavePolygonShape3D.new()
		shape.set_faces(faces)
		var cs := CollisionShape3D.new()
		cs.shape = shape
		body.add_child(cs)
		parent.add_child(body)

	return {"enterable": n_enterable, "total": buildings.size()}


static func _center(b: Dictionary) -> Vector2:
	var c: Array = b.get("center_xy", [0.0, 0.0])
	return Vector2(float(c[0]), float(c[1]))


## World-space footprint ring, forced counter-clockwise (shoelace > 0) so the
## outward wall normal of edge a→b is always (d.y, -d.x).
static func _footprint(b: Dictionary) -> PackedVector2Array:
	var out := PackedVector2Array()
	for p in b.get("footprint", []):
		out.append(Vector2(float(p[0]), float(p[1])))
	if out.size() >= 3:
		var s := 0.0
		for i in range(out.size()):
			var q := out[(i + 1) % out.size()]
			s += out[i].x * q.y - q.x * out[i].y
		if s < 0.0:
			out.reverse()
	return out


# ---------------------------------------------------------------- shells
static func _shell(st: SurfaceTool, faces: PackedVector3Array,
		poly: PackedVector2Array, height: float, style: CityStyle,
		kind: String, salt: int, collide: bool) -> void:
	var wall := style.wall_color(kind, salt)
	var n := poly.size()
	for i in range(n):
		var a := poly[i]
		var b := poly[(i + 1) % n]
		var d := (b - a)
		if d.length() < 0.05:
			continue
		var normal := Vector3(d.y, 0.0, -d.x).normalized()
		var v0 := Vector3(a.x, 0.0, a.y)
		var v1 := Vector3(b.x, 0.0, b.y)
		var v2 := Vector3(b.x, height, b.y)
		var v3 := Vector3(a.x, height, a.y)
		st.set_color(wall)
		st.set_normal(normal)
		for v in [v0, v1, v2, v0, v2, v3]:
			st.add_vertex(v)
		if collide:
			for v in [v0, v1, v2, v0, v2, v3]:
				faces.append(v)
	var idx := Geometry2D.triangulate_polygon(poly)
	var roof := style.roof_color(salt)
	st.set_color(roof)
	st.set_normal(Vector3.UP)
	for i in idx:
		st.add_vertex(Vector3(poly[i].x, height, poly[i].y))


# ------------------------------------------------------------- enterable
static func _enterable_building(b: Dictionary, poly_world: PackedVector2Array,
		height: float, style: CityStyle, salt: int, roads: Dictionary) -> Node3D:
	var center := _center(b)
	var kind := str(b.get("kind", "generic"))
	var root := Node3D.new()
	root.position = Vector3(center.x, 0.0, center.y)
	root.name = "Building_%s_%d" % [kind, salt]

	var poly := PackedVector2Array()
	for p in poly_world:
		poly.append(p - center)

	var wall_col := style.wall_color(kind, salt)
	var road_pt := RoadBuilder.closest_road_point(roads, center) - center
	var door_edge := _pick_door_edge(poly, road_pt)

	var rng := RandomNumberGenerator.new()
	rng.seed = hash(str(center.x, ":", center.y, ":", kind))

	var n := poly.size()
	var door_mid := Vector2.ZERO
	for i in range(n):
		var a := poly[i]
		var bb := poly[(i + 1) % n]
		if i == door_edge:
			door_mid = (a + bb) * 0.5
			_wall_with_door(root, a, bb, wall_col, style)
		else:
			_wall_box(root, a, bb, 0.0, WALL_H, wall_col)

	# upper band + roof as a small per-building mesh
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	for i in range(n):
		var a := poly[i]
		var bb := poly[(i + 1) % n]
		var d := bb - a
		if d.length() < 0.05:
			continue
		st.set_color(wall_col)
		st.set_normal(Vector3(d.y, 0.0, -d.x).normalized())
		var v0 := Vector3(a.x, WALL_H, a.y)
		var v1 := Vector3(bb.x, WALL_H, bb.y)
		var v2 := Vector3(bb.x, height, bb.y)
		var v3 := Vector3(a.x, height, a.y)
		for v in [v0, v1, v2, v0, v2, v3]:
			st.add_vertex(v)
	var idx := Geometry2D.triangulate_polygon(poly)
	st.set_color(style.roof_color(salt))
	st.set_normal(Vector3.UP)
	for i in idx:
		st.add_vertex(Vector3(poly[i].x, height, poly[i].y))
	var mat := StandardMaterial3D.new()
	mat.vertex_color_use_as_albedo = true
	mat.vertex_color_is_srgb = true
	mat.roughness = 0.9
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	st.set_material(mat)
	var mi := MeshInstance3D.new()
	mi.mesh = st.commit()
	root.add_child(mi)

	InteriorGenerator.generate(root, poly, kind, style, rng, door_mid)
	return root


## Edge whose midpoint is closest to the nearest road — that's the street side.
## Falls back to the longest edge when the closest one is too short for a door.
static func _pick_door_edge(poly: PackedVector2Array, road_pt: Vector2) -> int:
	var n := poly.size()
	var best := -1
	var best_d := INF
	var longest := 0
	var longest_len := 0.0
	for i in range(n):
		var a := poly[i]
		var b := poly[(i + 1) % n]
		var seg_len := a.distance_to(b)
		if seg_len > longest_len:
			longest_len = seg_len
			longest = i
		if seg_len < DOOR_GAP + 1.2:
			continue
		var d := ((a + b) * 0.5).distance_to(road_pt)
		if d < best_d:
			best_d = d
			best = i
	return best if best >= 0 else longest


static func _wall_box(parent: Node3D, a: Vector2, b: Vector2,
		y0: float, y1: float, color: Color) -> void:
	var d := b - a
	var seg_len := d.length()
	if seg_len < 0.1 or y1 - y0 < 0.05:
		return
	var body := StaticBody3D.new()
	var mesh := BoxMesh.new()
	mesh.size = Vector3(seg_len, y1 - y0, PERIM_THICK)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = color
	mat.roughness = 0.9
	mesh.material = mat
	var mid := (a + b) * 0.5
	# wall centered on the footprint line, box local X along the edge
	body.position = Vector3(mid.x, (y0 + y1) * 0.5, mid.y)
	body.rotation.y = atan2(-d.y, d.x)
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	body.add_child(mi)
	var shape := BoxShape3D.new()
	shape.size = mesh.size
	var cs := CollisionShape3D.new()
	cs.shape = shape
	body.add_child(cs)
	parent.add_child(body)


static func _wall_with_door(parent: Node3D, a: Vector2, b: Vector2,
		color: Color, style: CityStyle) -> void:
	var d := b - a
	var seg_len := d.length()
	if seg_len < DOOR_GAP + 0.4:   # fallback edge too short for a doorway
		_wall_box(parent, a, b, 0.0, WALL_H, color)
		return
	var dir := d / seg_len
	var gap0 := seg_len * 0.5 - DOOR_GAP * 0.5
	var gap1 := seg_len * 0.5 + DOOR_GAP * 0.5
	_wall_box(parent, a, a + dir * gap0, 0.0, WALL_H, color)
	_wall_box(parent, a + dir * gap1, b, 0.0, WALL_H, color)
	# lintel above the doorway
	_wall_box(parent, a + dir * gap0, a + dir * gap1, DOOR_H, WALL_H, color)

	var hinge_pt := a + dir * gap0 + dir * ((DOOR_GAP - DoorInteractable.WIDTH) * 0.5)
	var door := DoorInteractable.make(style.interior_floor.darkened(0.15))
	door.position = Vector3(hinge_pt.x, 0.0, hinge_pt.y)
	door.rotation.y = atan2(-dir.y, dir.x)
	parent.add_child(door)
