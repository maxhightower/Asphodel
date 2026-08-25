extends RefCounted
class_name InteriorBuilder

## Materializes an authoritative interior descriptor (from GET_INTERIOR) into a
## Godot Node3D subtree: floor, perimeter + partition walls with doorway gaps,
## searchable furniture (with collision + container metadata), and an exit marker
## at the entrance. This is PRESENTATION ONLY — it never invents rooms, fixtures,
## or container assignments; it draws exactly what Python reported.
##
## The interior is built in an offset "interior cell" (a streamed local space) so
## it never clips the batched exterior city mesh. Coordinate continuity is
## preserved logically: the player is placed just inside the entrance doorway on
## enter and returned to the exterior entrance on leave (street_world owns that).

const WALL_H := 3.0
const WALL_T := 0.2
const FLOOR_Y := 0.0
const DOOR_W := 1.1

# Fixture visual sizes (metres) by kind.
const FIXTURE_SIZE := {
	"cabinet": Vector3(1.0, 1.0, 0.6),
	"fridge": Vector3(0.8, 1.8, 0.8),
	"shelf": Vector3(1.2, 1.8, 0.4),
	"dresser": Vector3(1.2, 0.9, 0.6),
	"desk": Vector3(1.4, 0.8, 0.7),
	"counter": Vector3(1.6, 0.9, 0.6),
	"crate": Vector3(0.8, 0.8, 0.8),
}
const FIXTURE_COL := Color(0.55, 0.42, 0.30)
const FLOOR_COL := Color(0.30, 0.30, 0.34)
const WALL_COL := Color(0.72, 0.72, 0.76)


## Build the interior. `descriptor` is the "interior" dict from GET_INTERIOR.
## `offset` translates the whole cell (default: a far staging area). Returns the
## root Node3D. Fixtures carry meta: building_id, fixture_id, container_index.
static func build(descriptor: Dictionary, offset: Vector3 = Vector3(0, 0, 0)) -> Node3D:
	var root := Node3D.new()
	root.name = "Interior_%d" % int(descriptor.get("building_id", -1))
	root.position = offset
	root.set_meta("building_id", int(descriptor.get("building_id", -1)))
	root.set_meta("geometry_hash", str(descriptor.get("seed", 0)))

	var hull: Array = descriptor.get("hull", [])
	var rooms: Array = descriptor.get("rooms", [])
	var doorways: Array = descriptor.get("doorways", [])
	var entrances: Array = descriptor.get("entrances", [])
	var fixtures: Array = descriptor.get("fixtures", [])

	# collect all gap centres (doorways + entrances) for wall cutting
	var gaps: Array = []
	for d in doorways:
		gaps.append(Vector2(float(d["x"]), float(d["y"])))
	for e in entrances:
		gaps.append(Vector2(float(e["x"]), float(e["y"])))

	# --- floor + ceiling over the hull + interior fill light ----------------
	if hull.size() >= 4:
		var hx0 = float(hull[0][0]); var hy0 = float(hull[0][1])
		var hx1 = float(hull[2][0]); var hy1 = float(hull[2][1])
		root.add_child(_floor(hx0, hy0, hx1, hy1))
		root.add_child(_ceiling(hx0, hy0, hx1, hy1))
		# a soft interior fill so enclosed rooms are lit independent of the sun.
		var lamp := OmniLight3D.new()
		lamp.name = "InteriorLight"
		lamp.position = Vector3((hx0 + hx1) * 0.5, WALL_H - 0.4, (hy0 + hy1) * 0.5)
		lamp.omni_range = maxf(hx1 - hx0, hy1 - hy0) + 20.0
		lamp.light_energy = 1.6
		root.add_child(lamp)

	# --- per-room walls with doorway/entrance gaps --------------------------
	var body := StaticBody3D.new()
	body.name = "InteriorCollision"
	root.add_child(body)
	for r in rooms:
		_room_walls(body, float(r["x0"]), float(r["y0"]),
			float(r["x1"]), float(r["y1"]), gaps)

	# --- searchable fixtures ------------------------------------------------
	var fx_root := Node3D.new()
	fx_root.name = "Fixtures"
	root.add_child(fx_root)
	for f in fixtures:
		fx_root.add_child(_fixture(descriptor, f))

	# --- interior NPC occupants (Package 5) --------------------------------
	var occupants: Array = descriptor.get("occupants", [])
	if occupants.size() > 0:
		var occ_root := Node3D.new()
		occ_root.name = "Occupants"
		root.add_child(occ_root)
		for o in occupants:
			occ_root.add_child(_occupant(o))

	# --- exit marker at the entrance ---------------------------------------
	if entrances.size() > 0:
		var e = entrances[0]
		var marker := Node3D.new()
		marker.name = "ExitMarker"
		marker.position = Vector3(float(e["x"]), FLOOR_Y, float(e["y"]))
		marker.set_meta("nx", float(e["nx"]))
		marker.set_meta("ny", float(e["ny"]))
		root.add_child(marker)

	return root


static func _occupant(o: Dictionary) -> Node3D:
	## An interior NPC: a capsule at the authoritative anchor, tagged with the
	## citizen id so E-interact routes to INTERACT_WITH. Presentation only.
	var n := Node3D.new()
	var cid := int(o.get("citizen_id", -1))
	n.name = "Occupant_%d" % cid
	n.position = Vector3(float(o.get("x", 0.0)), 0.0, float(o.get("y", 0.0)))
	var mesh := CapsuleMesh.new()
	mesh.radius = 0.28
	mesh.height = 1.7
	var mat := StandardMaterial3D.new()
	# roster members tinted by their stable visual seed (recognisable on return)
	var base := Color(0.75, 0.72, 0.68)
	if bool(o.get("in_roster", false)):
		var hue := float((cid * 0x9E3779B1) % 360) / 360.0
		base = base.lerp(Color.from_hsv(hue, 0.5, 0.95), 0.5)
	mat.albedo_color = base
	mesh.material = mat
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.position = Vector3(0, 1.0, 0)
	n.add_child(mi)
	n.set_meta("citizen_id", cid)
	return n


static func _box(size: Vector3, col: Color) -> MeshInstance3D:
	var mesh := BoxMesh.new()
	mesh.size = size
	var mat := StandardMaterial3D.new()
	mat.albedo_color = col
	mesh.material = mat
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	return mi


static func _floor(x0: float, y0: float, x1: float, y1: float) -> Node3D:
	var w = maxf(x1 - x0, 0.5)
	var d = maxf(y1 - y0, 0.5)
	var n := StaticBody3D.new()
	n.name = "Floor"
	var mi := _box(Vector3(w, 0.1, d), FLOOR_COL)
	mi.position = Vector3((x0 + x1) * 0.5, FLOOR_Y - 0.05, (y0 + y1) * 0.5)
	n.add_child(mi)
	var cs := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = Vector3(w, 0.1, d)
	cs.shape = shape
	cs.position = mi.position
	n.add_child(cs)
	return n


static func _ceiling(x0: float, y0: float, x1: float, y1: float) -> Node3D:
	var w = maxf(x1 - x0, 0.5)
	var d = maxf(y1 - y0, 0.5)
	var mi := _box(Vector3(w, 0.1, d), WALL_COL.darkened(0.15))
	mi.position = Vector3((x0 + x1) * 0.5, WALL_H, (y0 + y1) * 0.5)
	mi.name = "Ceiling"
	return mi


static func _room_walls(body: StaticBody3D, x0: float, y0: float,
		x1: float, y1: float, gaps: Array) -> void:
	# four edges; each cut by any gap centre lying on it
	_wall_run(body, Vector2(x0, y0), Vector2(x1, y0), gaps)   # south
	_wall_run(body, Vector2(x0, y1), Vector2(x1, y1), gaps)   # north
	_wall_run(body, Vector2(x0, y0), Vector2(x0, y1), gaps)   # west
	_wall_run(body, Vector2(x1, y0), Vector2(x1, y1), gaps)   # east


static func _wall_run(body: StaticBody3D, a: Vector2, b: Vector2, gaps: Array) -> void:
	# Build a wall from a->b, leaving a DOOR_W gap wherever a gap centre lies on it.
	var horiz := absf(b.x - a.x) > absf(b.y - a.y)
	var length := a.distance_to(b)
	if length < 0.1:
		return
	# positions (0..length) of gaps on this segment
	var cut_ts: Array = []
	for g in gaps:
		var on := false
		var t := 0.0
		if horiz and absf(g.y - a.y) < 0.4 and g.x >= minf(a.x, b.x) - 0.3 and g.x <= maxf(a.x, b.x) + 0.3:
			on = true
			t = absf(g.x - a.x)
		elif not horiz and absf(g.x - a.x) < 0.4 and g.y >= minf(a.y, b.y) - 0.3 and g.y <= maxf(a.y, b.y) + 0.3:
			on = true
			t = absf(g.y - a.y)
		if on:
			cut_ts.append(t)
	cut_ts.sort()
	# build sub-segments avoiding [t-DOOR_W/2, t+DOOR_W/2]
	var segments: Array = []
	var cursor := 0.0
	for t in cut_ts:
		var gap_lo = maxf(cursor, t - DOOR_W * 0.5)
		if gap_lo > cursor + 0.05:
			segments.append([cursor, gap_lo])
		cursor = maxf(cursor, t + DOOR_W * 0.5)
	if cursor < length - 0.05:
		segments.append([cursor, length])
	var dir := (b - a).normalized()
	for seg in segments:
		var s0: float = seg[0]
		var s1: float = seg[1]
		var seg_len := s1 - s0
		if seg_len < 0.1:
			continue
		var mid2 := a + dir * ((s0 + s1) * 0.5)
		var size := Vector3(seg_len, WALL_H, WALL_T) if horiz else Vector3(WALL_T, WALL_H, seg_len)
		var pos := Vector3(mid2.x, FLOOR_Y + WALL_H * 0.5, mid2.y)
		var mi := _box(size, WALL_COL)
		mi.position = pos
		body.add_child(mi)
		var cs := CollisionShape3D.new()
		var shape := BoxShape3D.new()
		shape.size = size
		cs.shape = shape
		cs.position = pos
		body.add_child(cs)


static func _fixture(descriptor: Dictionary, f: Dictionary) -> Node3D:
	var kind := str(f.get("kind", "crate"))
	var size: Vector3 = FIXTURE_SIZE.get(kind, Vector3(0.8, 0.9, 0.6))
	var n := StaticBody3D.new()
	n.name = "Fixture_%d" % int(f.get("fixture_id", -1))
	var mi := _box(size, FIXTURE_COL)
	mi.position = Vector3(float(f["x"]), FLOOR_Y + size.y * 0.5, float(f["y"]))
	n.add_child(mi)
	var cs := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = size
	cs.shape = shape
	cs.position = mi.position
	n.add_child(cs)
	# authoritative linkage — the ONLY source of the container this fixture opens
	n.set_meta("building_id", int(descriptor.get("building_id", -1)))
	n.set_meta("fixture_id", int(f.get("fixture_id", -1)))
	n.set_meta("container_index", int(f.get("container_index", -1)))
	n.set_meta("fixture_pos", mi.position)
	return n
