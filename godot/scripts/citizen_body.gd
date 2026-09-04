class_name CitizenBody
extends CharacterBody3D

## Physical NPC body + local navigation (AS-PHYS-0 §4.4, AS-NAV-2 §7.1/§7.2).
##
## The authoritative physical object a near citizen follows. The planner supplies a
## high-level route (a list of waypoints from the MobilityGraph); this body steers
## toward the current waypoint with cheap local avoidance and lets physics decide
## where it actually moves — the planner never sets the transform directly. When
## local movement repeatedly fails to make progress the body declares itself stuck
## and emits `blocked`, which the strategic layer turns into a replan (§7.2). Layers
## come from the generated CollisionLayers authority, so the NPC cannot pass through
## walls/player/cars/other NPCs but fits through valid doorways, and crowd
## bottlenecks emerge from real collision.

signal blocked(at: Vector3)     # local nav failed -> ask the strategic layer to replan
signal arrived()

@export var walk_speed: float = 1.4
@export var arrive_radius: float = 0.6
@export var avoid_radius: float = 2.0
@export var stuck_frames: int = 90        # ~1.5 s at 60 Hz of no progress
@export var progress_epsilon: float = 0.3  # metres that count as "made progress"

var semantic_id: String = ""              # stable citizen id across LOD (§12)
var waypoints: Array = []                 # Array[Vector3] high-level route
var is_stuck: bool = false

var _wp: int = 0
var _sensor: Area3D
var _gravity: float = 20.0
var _progress_ref: Vector3
var _progress_frames: int = 0


func _ready() -> void:
	collision_layer = CollisionLayers.NPC
	collision_mask = CollisionLayers.PROFILES["npc"]["mask"]
	if not has_node("Collision"):
		var cap := CollisionShape3D.new()
		cap.name = "Collision"
		var shape := CapsuleShape3D.new()
		shape.radius = 0.35
		shape.height = 1.8
		cap.shape = shape
		add_child(cap)
	if not has_node("Sensor"):
		_sensor = Area3D.new()
		_sensor.name = "Sensor"
		_sensor.collision_layer = CollisionLayers.TRIGGER
		_sensor.collision_mask = CollisionLayers.NPC | CollisionLayers.VEHICLE
		_sensor.monitoring = true
		var scol := CollisionShape3D.new()
		var ssh := SphereShape3D.new()
		ssh.radius = avoid_radius
		scol.shape = ssh
		_sensor.add_child(scol)
		add_child(_sensor)
	else:
		_sensor = $Sensor
	_progress_ref = global_position


func set_route(points: Array) -> void:
	waypoints = points
	_wp = 0
	is_stuck = false
	_progress_frames = 0
	_progress_ref = global_position


func has_arrived() -> bool:
	return _wp >= waypoints.size()


func _physics_process(delta: float) -> void:
	if is_stuck or has_arrived():
		velocity = Vector3(0, velocity.y - _gravity * delta, 0)
		move_and_slide()
		return

	var target: Vector3 = waypoints[_wp]
	var to := target - global_position
	to.y = 0.0
	if to.length() < arrive_radius:
		_wp += 1
		_progress_frames = 0
		_progress_ref = global_position
		if has_arrived():
			emit_signal("arrived")
		return

	# Desired heading = toward the waypoint, steered by local avoidance.
	var desired := _steer(to.normalized())
	if desired.length() > 0.001:
		desired = desired.normalized() * walk_speed
	velocity = Vector3(desired.x, velocity.y - _gravity * delta, desired.z)
	move_and_slide()
	_update_stuck()


func _steer(goal_dir: Vector3) -> Vector3:
	# Bounded local avoidance (§7.1): repulsion from nearby agents PLUS a
	# tangential component so a head-on obstacle is skirted, not merely pushed
	# back against (naive repulsion cancels forward motion and deadlocks).
	var steer := goal_dir
	if _sensor == null:
		return steer
	for b in _sensor.get_overlapping_bodies():
		if b == self:
			continue
		var rel := b.global_position - global_position
		rel.y = 0.0
		var d := rel.length()
		if d <= 0.001 or d >= avoid_radius:
			continue
		var toward := rel / d
		var strength := 1.0 - d / avoid_radius
		steer += -toward * strength                       # repulsion
		if goal_dir.dot(toward) > 0.2:                     # obstacle roughly ahead
			var perp := Vector3(-toward.z, 0.0, toward.x)  # rotate 90 deg in xz
			if perp.dot(goal_dir) < 0.0:
				perp = -perp                               # pick the forward-ish side
			steer += perp * strength * 1.6                 # go around it
	return steer


func _update_stuck() -> void:
	# If the body has not netted `progress_epsilon` metres in `stuck_frames`
	# frames while still trying to reach a waypoint, escalate a blockage (§7.2).
	if global_position.distance_to(_progress_ref) > progress_epsilon:
		_progress_ref = global_position
		_progress_frames = 0
	else:
		_progress_frames += 1
		if _progress_frames > stuck_frames:
			is_stuck = true
			emit_signal("blocked", global_position)
