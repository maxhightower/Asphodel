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

const FurnitureMeshes = preload("res://scripts/furniture_meshes.gd")

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

# Presentation-only decor furniture (from descriptor["decor"], no containers). Sizes
# in metres by kind; colours give the room a legible, varied dressing at iso scale.
const DECOR_SIZE := {
	"sofa": Vector3(2.0, 0.8, 0.9), "coffee_table": Vector3(1.1, 0.4, 0.6),
	"tv": Vector3(1.2, 0.7, 0.2), "armchair": Vector3(0.9, 0.9, 0.9),
	"bookshelf": Vector3(1.2, 1.9, 0.4), "counter": Vector3(1.8, 0.9, 0.6),
	"stove": Vector3(0.8, 0.9, 0.7), "table": Vector3(1.4, 0.75, 1.0),
	"chair": Vector3(0.5, 0.9, 0.5), "bed": Vector3(1.5, 0.6, 2.0),
	"nightstand": Vector3(0.5, 0.6, 0.5), "wardrobe": Vector3(1.2, 2.0, 0.6),
	"bathtub": Vector3(1.7, 0.6, 0.8), "sink": Vector3(0.6, 0.9, 0.5),
	"toilet": Vector3(0.6, 0.8, 0.7), "bench": Vector3(1.6, 0.5, 0.5),
	"sideboard": Vector3(1.4, 0.9, 0.5), "rack": Vector3(1.6, 1.8, 0.6),
	"display": Vector3(1.0, 1.1, 1.0), "desk": Vector3(1.4, 0.8, 0.7),
	"stool": Vector3(0.5, 0.7, 0.5), "cabinet": Vector3(1.0, 1.0, 0.6),
	"shelf": Vector3(1.2, 1.8, 0.4), "crate": Vector3(0.8, 0.8, 0.8),
	"fridge": Vector3(0.8, 1.8, 0.8), "dresser": Vector3(1.2, 0.9, 0.6),
}
const DECOR_COL := {
	"sofa": Color(0.36, 0.44, 0.55), "coffee_table": Color(0.52, 0.38, 0.26),
	"tv": Color(0.12, 0.12, 0.14), "armchair": Color(0.42, 0.48, 0.56),
	"bookshelf": Color(0.55, 0.40, 0.28), "counter": Color(0.75, 0.75, 0.78),
	"stove": Color(0.30, 0.30, 0.33), "table": Color(0.60, 0.45, 0.30),
	"chair": Color(0.50, 0.38, 0.26), "bed": Color(0.70, 0.72, 0.80),
	"nightstand": Color(0.55, 0.40, 0.28), "wardrobe": Color(0.50, 0.36, 0.24),
	"bathtub": Color(0.90, 0.92, 0.95), "sink": Color(0.85, 0.87, 0.90),
	"toilet": Color(0.90, 0.92, 0.94), "bench": Color(0.55, 0.42, 0.30),
	"sideboard": Color(0.52, 0.38, 0.26), "rack": Color(0.60, 0.60, 0.64),
	"display": Color(0.40, 0.55, 0.65), "desk": Color(0.50, 0.38, 0.28),
	"stool": Color(0.50, 0.38, 0.26), "cabinet": Color(0.55, 0.42, 0.30),
	"shelf": Color(0.58, 0.44, 0.30), "crate": Color(0.62, 0.50, 0.34),
	"fridge": Color(0.86, 0.88, 0.90), "dresser": Color(0.52, 0.38, 0.26),
}
const DECOR_DEFAULT_SIZE := Vector3(0.8, 0.8, 0.6)
const DECOR_DEFAULT_COL := Color(0.55, 0.45, 0.35)


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
	body.collision_layer = CollisionLayers.WORLD_STATIC
	body.collision_mask = 0
	root.add_child(body)
	for ri in range(rooms.size()):
		var r = rooms[ri]
		_room_walls(body, float(r["x0"]), float(r["y0"]),
			float(r["x1"]), float(r["y1"]), gaps, int(r.get("room_id", r.get("id", ri))))

	# --- searchable fixtures ------------------------------------------------
	var fx_root := Node3D.new()
	fx_root.name = "Fixtures"
	root.add_child(fx_root)
	for f in fixtures:
		fx_root.add_child(_fixture(descriptor, f))

	# --- presentation-only decor furniture (no containers) -----------------
	var decor: Array = descriptor.get("decor", [])
	if decor.size() > 0:
		var decor_root := Node3D.new()
		decor_root.name = "Decor"
		root.add_child(decor_root)
		for d in decor:
			decor_root.add_child(_decor(d))

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


# One shared NPC material for every interior occupant (never one per citizen).
static var _npc_material: ShaderMaterial = null

static func _occupant(o: Dictionary) -> Node3D:
	## An interior NPC: a low-poly humanoid at the authoritative anchor, tagged with
	## the citizen id so E-interact routes to INTERACT_WITH. It uses the SAME
	## CitizenVisualIdentity + CitizenMeshes as outdoor citizens, so a given citizen
	## looks identical indoors and outdoors (H0/H10). Presentation only.
	if _npc_material == null:
		_npc_material = CitizenVisualIdentity.build_material()
	var cid := int(o.get("citizen_id", -1))
	var appear := CitizenVisualIdentity.appearance(cid)
	var av := CitizenAvatar.new()
	av.name = "Occupant_%d" % cid
	# Interior occupants render as a neutral IDLE stance for V1 (work/sleep poses
	# are deferred); gait 0 avoids a frozen mid-stride since interiors have no
	# per-frame animation driver.
	av.configure(cid, appear, _npc_material, 0.0, CitizenMeshes.LOD_NEAR)
	av.position = Vector3(float(o.get("x", 0.0)), FLOOR_Y, float(o.get("y", 0.0)))
	# A stable, seed-derived facing so identical occupants don't all face north.
	av.set_heading(float(CitizenVisualIdentity.visual_seed(cid) % 628) / 100.0)
	if bool(o.get("in_roster", false)) and cid >= 0:
		av.set_nameplate("Citizen %d" % cid)
	# configure() already stamps set_meta("citizen_id", cid) on the avatar root,
	# which is exactly what interaction candidate-gathering reads.
	return av


static func _decor(d: Dictionary) -> MeshInstance3D:
	## A presentation-only furniture piece: a real furniture mesh (pivot on the
	## floor) at the decor anchor. No collision (interiors stay walkable) and no
	## container metadata.
	var kind := str(d.get("kind", "crate"))
	var mi := MeshInstance3D.new()
	mi.mesh = FurnitureMeshes.get_mesh(kind, int(d.get("variant", 0)))
	mi.name = "Decor_%s" % kind
	mi.position = Vector3(float(d.get("x", 0.0)), FLOOR_Y, float(d.get("y", 0.0)))
	mi.rotation.y = float(d.get("facing", 0.0))
	return mi


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
	n.collision_layer = CollisionLayers.WORLD_STATIC
	n.collision_mask = 0
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
		x1: float, y1: float, gaps: Array, room_id: int = -1) -> void:
	# four edges; each cut by any gap centre lying on it. The outward normal (away
	# from the room centre) is recorded per wall so the isometric cutaway can decide
	# which walls face the camera and hide them (ISO-5). Presentation metadata only.
	_wall_run(body, Vector2(x0, y0), Vector2(x1, y0), gaps, Vector2(0, -1), room_id)   # south
	_wall_run(body, Vector2(x0, y1), Vector2(x1, y1), gaps, Vector2(0, 1), room_id)    # north
	_wall_run(body, Vector2(x0, y0), Vector2(x0, y1), gaps, Vector2(-1, 0), room_id)   # west
	_wall_run(body, Vector2(x1, y0), Vector2(x1, y1), gaps, Vector2(1, 0), room_id)    # east


static func _wall_run(body: StaticBody3D, a: Vector2, b: Vector2, gaps: Array,
		outward: Vector2 = Vector2.ZERO, room_id: int = -1) -> void:
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
		mi.name = "Wall"
		# Presentation metadata for the isometric cutaway (ISO-5): the outward
		# normal (world XZ, pointing away from the room), the room it bounds, and a
		# stable segment id. Additive only — the first-person path ignores it.
		mi.set_meta("is_wall", true)
		mi.set_meta("wall_normal", outward)
		mi.set_meta("room_id", room_id)
		mi.set_meta("segment_id", body.get_child_count())
		mi.add_to_group("interior_walls")
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
	# Fixtures are world geometry you bump into; the searchable container they
	# carry is authoritative in Python, not a Godot interaction body.
	n.collision_layer = CollisionLayers.WORLD_STATIC
	n.collision_mask = 0
	# Real furniture mesh (pivot on the floor); the collision box + authoritative
	# container metadata are unchanged, so searchable-container linkage is intact.
	var mi := MeshInstance3D.new()
	mi.mesh = FurnitureMeshes.get_mesh(kind, int(f.get("variant", 0)))
	mi.position = Vector3(float(f["x"]), FLOOR_Y, float(f["y"]))
	mi.rotation.y = float(f.get("facing", 0.0))
	n.add_child(mi)
	var cs := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = size
	cs.shape = shape
	cs.position = Vector3(float(f["x"]), FLOOR_Y + size.y * 0.5, float(f["y"]))
	n.add_child(cs)
	# authoritative linkage — the ONLY source of the container this fixture opens
	n.set_meta("building_id", int(descriptor.get("building_id", -1)))
	n.set_meta("fixture_id", int(f.get("fixture_id", -1)))
	n.set_meta("container_index", int(f.get("container_index", -1)))
	n.set_meta("fixture_pos", cs.position)
	return n
