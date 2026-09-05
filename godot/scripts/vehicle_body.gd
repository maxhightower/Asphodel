class_name VehicleBody
extends CharacterBody3D

## Physical vehicle body (AS-NAV-3 §8, §8.3 anti-tunneling,
## ASPHODEL_EMBODIED_MOBILITY_V1 §7/§10).
##
## The NEAR realisation of ONE persistent Python `VehicleInstance`
## (`semantic_id` == its vehicle_id). Uses the CollisionLayers authority so it
## collides with terrain, buildings, barriers, other vehicles, pedestrians and
## the player, and a parked car remains a solid obstacle. Motion is applied in
## substeps sized so per-substep displacement stays below the thinnest expected
## barrier (asphodel/physics/anti_tunneling.py).
##
## Drive modes:
## * raw `drive_velocity` (PhysicsGate contract);
## * **follow mode** (`set_follow_target`): the authoritative driving controller
##   (asphodel/embodied/vehicle_control.py) integrates progress along the
##   canonical road route and publishes the pose the car should be at; the body
##   drives toward it under physics. A body that cannot get there (something
##   solid in the way) falls behind, `is_blocked()` turns true, and the
##   EmbodiedMobility node reports the physical position back so the
##   simulation holds the vehicle where the body really is. Godot never
##   re-plans roads (one route authority).
##
## The mesh faces +X (prop_meshes vehicle convention); `heading` is the
## simulation heading atan2(z, x), so the body yaw is -heading.

@export var min_barrier_thickness: float = 0.2
@export var max_speed: float = 40.0
@export var follow_leash: float = 4.0
@export var stuck_frames: int = 60
@export var progress_epsilon: float = 0.25

var drive_velocity := Vector3.ZERO     # from lane-following / route controller
var semantic_id: String = ""
var follow_mode := false
var follow_target := Vector3.ZERO
var follow_heading := 0.0
var follow_speed := 0.0
var impacts := 0                        # slide collisions while following
var is_stuck := false

var _progress_ref := Vector3.ZERO
var _progress_frames := 0


func _ready() -> void:
	collision_layer = CollisionLayers.VEHICLE
	collision_mask = CollisionLayers.PROFILES["vehicle"]["mask"]
	motion_mode = CharacterBody3D.MOTION_MODE_GROUNDED
	floor_stop_on_slope = false
	if not has_node("Collision"):
		var cs := CollisionShape3D.new()
		cs.name = "Collision"
		var box := BoxShape3D.new()
		box.size = Vector3(4.6, 1.4, 2.0)   # length along +X (mesh convention)
		cs.shape = box
		add_child(cs)
	_progress_ref = global_position


func set_follow_target(target: Vector3, heading: float, speed: float) -> void:
	if not follow_mode:
		_progress_ref = global_position
		_progress_frames = 0
		is_stuck = false
	follow_mode = true
	follow_target = target
	follow_heading = heading
	follow_speed = speed


func set_parked(pose: Vector3, heading: float) -> void:
	follow_mode = false
	drive_velocity = Vector3.ZERO
	global_position = pose
	rotation.y = -heading


func is_blocked() -> bool:
	return is_stuck


func _required_substeps(speed: float, delta: float) -> int:
	var disp: float = abs(speed) * delta
	var max_step: float = max(0.0001, min_barrier_thickness * 0.5)
	return max(1, int(ceil(disp / max_step)))


func _physics_process(delta: float) -> void:
	if follow_mode:
		_update_follow_velocity(delta)
	# Substep the motion so no single move skips a thin barrier (swept-equivalent).
	var speed := drive_velocity.length()
	var n := _required_substeps(speed, delta)
	var hit := false
	for _i in range(n):
		# move_and_slide integrates over the whole physics delta, so each of the
		# n substeps carries 1/n of the velocity: total displacement stays
		# drive_velocity * delta and each sweep is <= half a barrier thickness.
		velocity = drive_velocity / float(n)
		move_and_slide()
		# Ground contact is not an impact: only a mostly-horizontal contact
		# normal (a wall, a car, a pedestrian) counts, and only that stops the
		# substep loop (the body has already been slid along the obstacle).
		var real_hit := false
		for c in range(get_slide_collision_count()):
			var nrm := get_slide_collision(c).get_normal()
			if abs(nrm.y) < 0.6:
				real_hit = true
		if real_hit:
			hit = true
			_on_impact()
			break
	if follow_mode:
		_update_stuck(hit)


func _update_follow_velocity(delta: float) -> void:
	var to := follow_target - global_position
	to.y = 0.0
	var lag := to.length()
	if lag < 0.2:
		drive_velocity = Vector3.ZERO
		rotation.y = -follow_heading
		return
	var cap: float = min(max_speed, max(follow_speed * 1.5, 1.5))
	var speed: float = min(cap, lag / max(delta, 0.0001))
	var dir := to / lag
	drive_velocity = dir * speed
	# face the direction we actually move (mesh +X forward)
	rotation.y = -atan2(dir.z, dir.x)


func _update_stuck(hit: bool) -> void:
	var to := follow_target - global_position
	to.y = 0.0
	if to.length() > follow_leash:
		if global_position.distance_to(_progress_ref) > progress_epsilon:
			_progress_ref = global_position
			_progress_frames = 0
			is_stuck = false
		else:
			_progress_frames += 1
			if _progress_frames > stuck_frames:
				is_stuck = true
	else:
		is_stuck = false
		_progress_frames = 0
		_progress_ref = global_position


func _on_impact() -> void:
	# Hook: on a significant impact, transition the VehicleInstance to
	# PHYSICAL_CRASH; when settled it becomes a PERSISTENT_WRECK and yields a
	# MobilityObstruction to the graph (§8.1, §10). V1 counts contacts and lets
	# the blocked report hold the simulation; crash escalation is future work.
	impacts += 1
