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


func _ready() -> void:
	_material = V.build_material()


func set_ground_y(y: float) -> void:
	_ground_y = y


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
			var target := Vector3(float(row["x"]), _ground_y + body_height, float(row["y"]))
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
			body.set_follow_target(Vector3(float(row["x"]), _ground_y + body_height, float(row["y"])), 0.0)
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
		var pose := Vector3(float(row["x"]), _ground_y + 0.7, float(row["y"]))
		if driving:
			body.set_follow_target(pose, float(row.get("heading", 0.0)), float(row.get("speed", 0.0)) * time_scale)
		elif body.follow_mode or not body.has_meta("parked_at") or body.get_meta("parked_at") != pose:
			body.set_parked(pose, float(row.get("heading", 0.0)))
			body.set_meta("parked_at", pose)
		keep[vid] = true
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
	var out := []
	for id in bodies:
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


func _ensure_citizen(id: String, row: Dictionary) -> CitizenBody:
	if bodies.has(id):
		return bodies[id]
	var b := CitizenBody.new()
	b.semantic_id = id
	b.name = id.replace(":", "_")
	# Materialization safety (1): never spawn inside a static collider (a
	# building hull at its own entrance anchor, a wreck) — the nearest free
	# spot within a few metres, else the authoritative point itself.
	b.position = _free_spot(Vector3(float(row["x"]), _ground_y + body_height, float(row["y"])))
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
	b.position = Vector3(float(row["x"]), _ground_y + 0.7, float(row["y"]))
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
