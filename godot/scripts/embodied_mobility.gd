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
	# --- citizens on foot ----------------------------------------------------
	for id in near:
		var row: Dictionary = citizens.get(id, {})
		if row.is_empty():
			continue
		var st: String = str(row.get("state", ""))
		if st in ["on_foot", "approaching_vehicle", "entering_vehicle", "exiting_vehicle"]:
			var body := _ensure_citizen(id, row)
			body.set_follow_target(Vector3(float(row["x"]), _ground_y + body_height, float(row["y"])),
				float(row.get("speed", 0.0)) * time_scale)
			_set_gait(body, float(row.get("speed", 0.0)))
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


func _ensure_citizen(id: String, row: Dictionary) -> CitizenBody:
	if bodies.has(id):
		return bodies[id]
	var b := CitizenBody.new()
	b.semantic_id = id
	b.name = id.replace(":", "_")
	b.position = Vector3(float(row["x"]), _ground_y + body_height, float(row["y"]))
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
