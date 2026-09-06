class_name EmbodiedMobility
extends Node3D

## Embodied mobility client (ASPHODEL_EMBODIED_MOBILITY_V1 §7, §17, §18).
##
## Turns the authoritative movement block (`World.mobility_snapshot()`, carried
## by ADVANCE_TIME / SNAPSHOT replies) into real Godot bodies for the NEAR band
## and reports their physical result back:
##
##     simulation intent (executor position/heading/speed + route ahead)
##       -> set_follow_target on a CitizenBody / VehicleBody
##       -> physics moves the body (collision authority: CollisionLayers)
##       -> MOBILITY_REPORT {id, x, z, blocked}
##       -> Python reconciles progress (holds the plan back, never ahead)
##
## Identity: one body per semantic id ("cit:<citizen_id>", "veh:<vehicle_id>"),
## created when the id enters the NEAR band and freed when it leaves; a
## citizen inside a building or inside a car has NO citizen body (the car body
## carries them), so nothing is ever drawn twice. The node never decides where
## anything goes — it only realises and reports.
##
## INTERIOR EMBODIMENT (ASPHODEL_SMART_OBJECTS_WORK_V1). While the player is
## inside a building (IsometricWorld.inside_building() >= 0), `set_interior()`
## puts this node in interior mode for that building: every citizen row with
## `building_id == bid` and state doing_activity / inside_building becomes a
## CitizenBody INSIDE THE STAGED INTERIOR at
##     interior_offset + Vector3(row.x, floor_y + body_height, row.y)
## — `row.x/row.y` are the citizen's authoritative interior position in WORLD
## metres (Python's WorkRuntime owns interior locomotion) and `interior_offset`
## is exactly the offset IsometricWorld._enter_building staged the interior
## with, so a worker walking between smart objects is visible walking between
## the rendered objects. The bodies are follow-mode only and are NEVER included
## in MOBILITY_REPORT: there is no physics reconciliation indoors (interior
## locomotion is authoritative Python; a wall the body snags on must not hold
## the authority back). Identity stays single: an interior body reuses the same
## "cit:<id>" key as the exterior body would, and the InteriorBuilder's static
## "Occupant_<id>" avatar is hidden for any citizen this node embodies.

const V = preload("res://scripts/citizen_visual_identity.gd")

@export var report_interval: float = 0.25     # real seconds between reports
@export var body_height: float = 0.9          # capsule half-height above ground
@export var enabled: bool = true
@export var stuck_rematerialize_applies: int = 90   # blocked applies before a body is re-materialized
## Game seconds per real second the bodies must keep up with (the GameClock's
## pacing: 24x by default; a real-time evidence scene uses 1.0). Follow speeds
## are scaled by it so a body can track the authoritative point.
var time_scale: float = 24.0

var bodies: Dictionary = {}                   # id -> CharacterBody3D
var last_block: Dictionary = {}
var promotions := 0
var demotions := 0
var reports_sent := 0
var reports_applied := 0
var rematerializations := 0                   # bodies moved out of a collider they could not leave
var _stuck_applies: Dictionary = {}           # id -> consecutive applies with the body blocked
var _material: ShaderMaterial
var _since_report := 0.0
var _game_dt_accum := 0.0
var _ground_y := 0.0

# --- interior mode (work / smart objects) ----------------------------------
const INTERIOR_STATES := ["doing_activity", "inside_building"]
const MARKER_REFRESH_S := 2.0        # wall seconds between GET_ROOMS marker refreshes
@export var interior_walk_speed: float = 1.3   # WorkRuntime WALK_SPEED (m/s), for the follow cap
var interior_building := -1                    # building whose interior is staged, or -1
var interior_offset := Vector3.ZERO            # IsometricWorld._enter_building's stage offset
var interior_floor_y := 0.0                    # InteriorBuilder.FLOOR_Y of the staged interior
var interior_bodies := 0                       # bodies currently driven from interior positions
var _interior_root: Node3D = null
var _interior_ids := {}                        # id -> true for bodies driven inside the interior
var _marker_root: Node3D = null
var _markers := {}                             # object_id -> MeshInstance3D
var _since_markers := 0.0
var _marker_mat: StandardMaterial3D = null
var _using_mat: StandardMaterial3D = null


func _ready() -> void:
	_material = V.build_material()


func set_ground_y(y: float) -> void:
	_ground_y = y


var _height_provider = null                    # ExteriorWorld (surface_height_at), or null


func set_height_provider(p) -> void:
	## Seat exterior bodies on the real rendered ground instead of a flat datum
	## (Convergence V2 §17). `p` must expose surface_height_at(x, z) -> float.
	_height_provider = p


func _gy(x: float, z: float) -> float:
	if _height_provider != null and is_instance_valid(_height_provider) \
			and _height_provider.has_method("surface_height_at"):
		return _height_provider.surface_height_at(x, z)
	return _ground_y


func set_interior(building_id: int, offset: Vector3, root: Node3D = null, floor_y: float = 0.0) -> void:
	## Enter interior mode for `building_id`. `offset` MUST be the offset the
	## interior was staged with (IsometricWorld.interior_offset()), else bodies
	## would be drawn away from the rooms they are authoritatively in.
	interior_building = int(building_id)
	interior_offset = offset
	interior_floor_y = floor_y
	_interior_root = root
	_since_markers = MARKER_REFRESH_S      # refresh markers on the next frame


func clear_interior() -> void:
	## Leave interior mode: free every interior body (the player can no longer
	## see the room) and every holder marker. Exterior bodies are untouched.
	for id in _interior_ids.keys():
		if bodies.has(id):
			bodies[id].queue_free()
			bodies.erase(id)
			demotions += 1
	_interior_ids.clear()
	interior_bodies = 0
	interior_building = -1
	_interior_root = null
	_clear_markers()


func interior_body_ids() -> Array:
	return _interior_ids.keys()


func apply(block: Dictionary, game_dt: float = 0.0) -> void:
	## Realise the NEAR band of a movement block. Called for every block the
	## GameClock receives (signal mobility_updated) or by a test harness.
	if not enabled or block.is_empty():
		return
	last_block = block
	_game_dt_accum += game_dt
	var keep := {}
	var near: Array = block.get("near", [])
	var citizens: Dictionary = {}
	for row in block.get("citizens", []):
		citizens["cit:%d" % int(row["citizen_id"])] = row
	# --- citizens on foot (living, undead) and corpses ------------------------
	for id in near:
		var row: Dictionary = citizens.get(id, {})
		if row.is_empty():
			continue
		var st: String = str(row.get("state", ""))
		var health: String = str(row.get("health", "susceptible"))
		if st in ["on_foot", "approaching_vehicle", "entering_vehicle", "exiting_vehicle", "undead"]:
			var body := _ensure_citizen(id, row)
			var target := Vector3(float(row["x"]), _gy(float(row["x"]), float(row["y"])) + body_height, float(row["y"]))
			body.set_follow_target(target, float(row.get("speed", 0.0)) * time_scale)
			# Materialization safety (2): a body that stays blocked without any
			# progress is inside something it cannot leave (a hull it was spawned
			# in, a wreck): re-materialize it at a free spot beside the
			# authoritative point. The authority never moved for it; it only
			# stopped holding back.
			if body.is_blocked():
				_stuck_applies[id] = int(_stuck_applies.get(id, 0)) + 1
				if int(_stuck_applies[id]) > stuck_rematerialize_applies:
					body.global_position = _free_spot(target)
					body.velocity = Vector3.ZERO
					rematerializations += 1
					_stuck_applies[id] = 0
			else:
				_stuck_applies[id] = 0
			_set_gait(body, float(row.get("speed", 0.0)))
			_apply_health_look(body, health, st)
			keep[id] = true
		elif st in ["corpse", "incapacitated"] and int(row.get("building_id", -1)) < 0 \
				and row.get("vehicle_id") == null:
			# a body on the street at the authoritative death location: solid, lying down
			var body := _ensure_citizen(id, row)
			body.set_follow_target(Vector3(float(row["x"]), _gy(float(row["x"]), float(row["y"])) + body_height, float(row["y"])), 0.0)
			_apply_health_look(body, health, st)
			keep[id] = true
	# --- vehicles -------------------------------------------------------------
	for row in block.get("vehicles", []):
		var vid: String = str(row["vehicle_id"])
		if str(row.get("band", "")) != "physical":
			continue
		var body := _ensure_vehicle(vid, row)
		var driving: bool = row.get("driver") != null and float(row.get("speed", 0.0)) >= 0.0 \
			and str(row.get("fidelity", "")) in ["physical_controlled", "route_simulated"] \
			and not bool(row.get("parked", false))
		var pose := Vector3(float(row["x"]), _gy(float(row["x"]), float(row["y"])) + 0.7, float(row["y"]))
		if driving:
			body.set_follow_target(pose, float(row.get("heading", 0.0)), float(row.get("speed", 0.0)) * time_scale)
		elif body.follow_mode or not body.has_meta("parked_at") or body.get_meta("parked_at") != pose:
			body.set_parked(pose, float(row.get("heading", 0.0)))
			body.set_meta("parked_at", pose)
		keep[vid] = true
	# --- interior: everyone inside the building the player is standing in ----
	# The authoritative interior position (row.x/row.y, world metres) placed in
	# the staged interior. Not gated on the NEAR band: the player is in the room.
	var inside := {}
	if interior_building >= 0:
		for id in citizens:
			var row: Dictionary = citizens[id]
			if int(row.get("building_id", -1)) != interior_building:
				continue
			if not (str(row.get("state", "")) in INTERIOR_STATES):
				continue
			if keep.has(id):
				continue      # already embodied outside (never two bodies per identity)
			var body := _ensure_citizen(id, row, true)
			var target := interior_offset + Vector3(float(row["x"]),
				interior_floor_y + body_height, float(row["y"]))
			var spd: float = maxf(float(row.get("speed", 0.0)), interior_walk_speed)
			body.set_follow_target(target, spd * time_scale)
			_set_gait(body, spd)
			_apply_health_look(body, str(row.get("health", "susceptible")), str(row.get("state", "")))
			_apply_work_look(body, row.get("work", {}))
			_hide_static_occupant(int(row["citizen_id"]))
			inside[id] = true
			keep[id] = true
	for id in _interior_ids.keys():
		if not inside.has(id):
			_interior_ids.erase(id)
	for id in inside:
		_interior_ids[id] = true
	interior_bodies = _interior_ids.size()
	# --- demote everything that left the band --------------------------------
	for id in bodies.keys():
		if not keep.has(id):
			bodies[id].queue_free()
			bodies.erase(id)
			demotions += 1


func _physics_process(delta: float) -> void:
	if not enabled or bodies.is_empty():
		return
	_since_report += delta
	if _since_report >= report_interval:
		_since_report = 0.0
		var dt := _game_dt_accum
		_game_dt_accum = 0.0
		if SimBridge.is_connected_to_sim():
			var r: Dictionary = SimBridge.mobility_report(collect_report(), dt)
			reports_sent += 1
			reports_applied += int(r.get("applied", 0))


func collect_report() -> Array:
	## EXTERIOR bodies only. Interior bodies are deliberately never reported:
	## indoor locomotion is authoritative Python (WorkRuntime walks the room
	## graph) and there is no physics reconciliation indoors — a body snagged on
	## a staged wall must not hold a worker's task back.
	var out := []
	for id in bodies:
		if _interior_ids.has(id):
			continue
		var b = bodies[id]
		out.append({"id": id, "x": b.global_position.x, "z": b.global_position.z,
			"blocked": bool(b.is_blocked())})
	return out


func body_of(id: String) -> Node3D:
	return bodies.get(id, null)


func _free_spot(p: Vector3) -> Vector3:
	## The nearest point to `p` (p itself first) where a citizen-sized sphere
	## overlaps no static collider. Other citizens/vehicles do not count.
	var world := get_world_3d()
	if world == null:
		return p
	var space := world.direct_space_state
	if space == null:
		return p
	var shape := SphereShape3D.new()
	shape.radius = 0.4
	var q := PhysicsShapeQueryParameters3D.new()
	q.shape = shape
	q.collision_mask = CollisionLayers.PROFILES["npc"]["mask"]
	q.collide_with_areas = false
	q.collide_with_bodies = true
	var cands: Array = [Vector3.ZERO]
	for r in [0.8, 1.6, 2.4, 3.2, 4.5]:
		for k in range(8):
			var a := float(k) * PI / 4.0
			cands.append(Vector3(cos(a) * r, 0.0, sin(a) * r))
	for off in cands:
		q.transform = Transform3D(Basis(), p + off)
		var hits: Array = space.intersect_shape(q, 8)
		var solid := false
		for h in hits:
			var c = h.get("collider")
			if c is CitizenBody or c is VehicleBody:
				continue
			solid = true
			break
		if not solid:
			return p + off
	return p


func _ensure_citizen(id: String, row: Dictionary, interior: bool = false) -> CitizenBody:
	if bodies.has(id):
		return bodies[id]
	var b := CitizenBody.new()
	b.semantic_id = id
	b.name = id.replace(":", "_")
	if interior:
		# Inside the staged interior the authoritative point IS a legal spot
		# (Python walks the room graph through doorways), and a free-spot search
		# against interior walls would push the body off its authoritative pose:
		# spawn exactly where the authority says it is (LOD promotion, jump 0).
		b.position = interior_offset + Vector3(float(row["x"]),
			interior_floor_y + body_height, float(row["y"]))
	else:
		# Materialization safety (1): never spawn inside a static collider (a
		# building hull at its own entrance anchor, a wreck) — the nearest free
		# spot within a few metres, else the authoritative point itself.
		b.position = _free_spot(Vector3(float(row["x"]), _gy(float(row["x"]), float(row["y"])) + body_height, float(row["y"])))
	var cid := int(row["citizen_id"])
	b.set_meta("citizen_id", cid)
	# The same deterministic look as the crowd (citizen_visual_identity.gd).
	var av := CitizenAvatar.new()
	av.configure(cid, V.appearance(cid), _material, 0.0)
	av.position = Vector3(0.0, -body_height, 0.0)
	b.add_child(av)
	add_child(b)
	bodies[id] = b
	promotions += 1
	return b


var _undead_mat: StandardMaterial3D = null
var _corpse_mat: StandardMaterial3D = null
var _sick_mat: StandardMaterial3D = null


func _apply_health_look(b: CitizenBody, health: String, st: String) -> void:
	## Presentation of the authoritative health state (never decided here):
	## undead = grey-green tint, corpse/incapacitated = lying down, symptomatic = pale.
	var want := ""
	if health == "undead":
		want = "undead"
	elif st == "corpse" or st == "incapacitated" or health == "corpse" or health == "dead":
		want = "corpse"
	elif health == "symptomatic":
		want = "sick"
	if b.get_meta("health_look", "") == want:
		return
	b.set_meta("health_look", want)
	b.set_meta("health", health)
	for c in b.get_children():
		if c is CitizenAvatar:
			if want == "undead":
				if _undead_mat == null:
					_undead_mat = StandardMaterial3D.new()
					_undead_mat.albedo_color = Color(0.45, 0.62, 0.42)
				c.set_material_override(_undead_mat)
				c.rotation = Vector3.ZERO
			elif want == "corpse":
				if _corpse_mat == null:
					_corpse_mat = StandardMaterial3D.new()
					_corpse_mat.albedo_color = Color(0.5, 0.45, 0.42)
				c.set_material_override(_corpse_mat)
				c.rotation = Vector3(0.0, 0.0, PI / 2.0)      # lying on the ground
				c.position = Vector3(0.0, -body_height + 0.35, 0.0)
			elif want == "sick":
				if _sick_mat == null:
					_sick_mat = StandardMaterial3D.new()
					_sick_mat.albedo_color = Color(0.85, 0.85, 0.7)
				c.set_material_override(_sick_mat)
				c.rotation = Vector3.ZERO
			else:
				c.set_material_override(_material)
				c.rotation = Vector3.ZERO
				c.position = Vector3(0.0, -body_height, 0.0)


func _set_gait(b: CitizenBody, speed: float) -> void:
	for c in b.get_children():
		if c is CitizenAvatar:
			c.set_gait(clampf(speed / 1.4, 0.0, 1.0))
			var v := b.velocity
			v.y = 0.0
			if v.length() > 0.05:
				c.set_heading(atan2(v.x, v.z))


func _ensure_vehicle(vid: String, row: Dictionary) -> VehicleBody:
	if bodies.has(vid):
		return bodies[vid]
	var b := VehicleBody.new()
	b.semantic_id = vid
	b.name = vid.replace(":", "_")
	# Real-speed ceiling scales with the clock pacing so the body can track a
	# time-compressed authoritative car (40 m/s of game speed).
	b.max_speed = 40.0 * time_scale
	b.position = Vector3(float(row["x"]), _gy(float(row["x"]), float(row["y"])) + 0.7, float(row["y"]))
	b.rotation.y = -float(row.get("heading", 0.0))
	b.set_meta("vehicle_id", vid)
	var mi := MeshInstance3D.new()
	var kind: String = str(row.get("type", "car"))
	if not PropMeshes.is_supported(kind):
		kind = "sedan"
	var variant: int = abs(hash(vid)) % 6
	mi.mesh = PropMeshes.get_mesh(kind, variant)
	mi.position = Vector3(0.0, -0.7, 0.0)
	b.add_child(mi)
	add_child(b)
	bodies[vid] = b
	promotions += 1
	return b


# ---------------------------------------------------------------- interior look
func _apply_work_look(b: CitizenBody, work) -> void:
	## Truthful, minimal presentation of the authoritative work phase: a worker
	## reported `phase == "using"` gets a slight warm highlight so the station in
	## use reads at iso scale. Nothing here decides a phase — it only draws one.
	if not (work is Dictionary):
		return
	var phase := str(work.get("phase", ""))
	var want: String = "using" if phase == "using" else ""
	if str(b.get_meta("work_look", "")) == want:
		return
	b.set_meta("work_look", want)
	b.set_meta("work_phase", phase)
	if str(b.get_meta("health_look", "")) != "":
		return    # a health look (undead/corpse/sick) is the stronger truth; leave it
	for c in b.get_children():
		if c is CitizenAvatar:
			if want == "using":
				if _using_mat == null:
					_using_mat = StandardMaterial3D.new()
					_using_mat.albedo_color = Color(0.92, 0.86, 0.62)
					_using_mat.emission_enabled = true
					_using_mat.emission = Color(0.35, 0.28, 0.10)
					_using_mat.emission_energy_multiplier = 0.5
				c.set_material_override(_using_mat)
			else:
				c.set_material_override(_material)


func _hide_static_occupant(cid: int) -> void:
	## One body per identity: the InteriorBuilder's static "Occupant_<cid>"
	## avatar (the descriptor's presentational anchor) is hidden for any citizen
	## this node embodies, so a worker is never drawn twice in the same room.
	if _interior_root == null or not is_instance_valid(_interior_root):
		return
	var occ := _interior_root.get_node_or_null("Occupants")
	if occ == null:
		return
	var node := occ.get_node_or_null("Occupant_%d" % cid)
	if node != null and node.visible:
		node.visible = false


# ------------------------------------------------ smart-object holder markers
func _process(delta: float) -> void:
	if interior_building < 0 or not enabled:
		return
	_since_markers += delta
	if _since_markers < MARKER_REFRESH_S:
		return
	_since_markers = 0.0
	refresh_object_markers()


func refresh_object_markers() -> void:
	## A thin ring at the interaction point of every smart object that currently
	## HAS A HOLDER, straight from GET_ROOMS (authoritative `holders`): the
	## station actually in use is visible in the room. Presentation only.
	if interior_building < 0 or not SimBridge.is_connected_to_sim():
		return
	var r: Dictionary = SimBridge.get_rooms(interior_building)
	if not r.get("ok", false):
		return
	var held := {}
	for o in r.get("objects", []):
		var holders: Array = o.get("holders", [])
		if holders.is_empty():
			continue
		held[str(o["object_id"])] = o
	if _marker_root == null or not is_instance_valid(_marker_root):
		_marker_root = Node3D.new()
		_marker_root.name = "SmartObjectMarkers"
		add_child(_marker_root)
	for oid in held:
		var o: Dictionary = held[oid]
		var pos := interior_offset + Vector3(float(o["x"]), interior_floor_y + 0.05, float(o["y"]))
		var mi: MeshInstance3D = _markers.get(oid, null)
		if mi == null or not is_instance_valid(mi):
			if _marker_mat == null:
				_marker_mat = StandardMaterial3D.new()
				_marker_mat.albedo_color = Color(1.0, 0.78, 0.25)
				_marker_mat.emission_enabled = true
				_marker_mat.emission = Color(0.9, 0.65, 0.15)
				_marker_mat.emission_energy_multiplier = 1.4
			var ring := TorusMesh.new()
			ring.inner_radius = 0.5
			ring.outer_radius = 0.62
			ring.material = _marker_mat
			mi = MeshInstance3D.new()
			mi.name = "Marker_" + oid.replace(":", "_")
			mi.mesh = ring
			_marker_root.add_child(mi)
			_markers[oid] = mi
		mi.global_position = pos
		mi.set_meta("object_id", oid)
		mi.set_meta("holders", o.get("holders", []))
		mi.visible = true
	for oid in _markers.keys():
		if not held.has(oid):
			var m = _markers[oid]
			if is_instance_valid(m):
				m.queue_free()
			_markers.erase(oid)


func marker_ids() -> Array:
	return _markers.keys()


func _clear_markers() -> void:
	for oid in _markers.keys():
		var m = _markers[oid]
		if is_instance_valid(m):
			m.queue_free()
	_markers.clear()
	if _marker_root != null and is_instance_valid(_marker_root):
		_marker_root.queue_free()
	_marker_root = null
