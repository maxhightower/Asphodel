class_name IsometricPlayer
extends CharacterBody3D

## Embodied player for the isometric presentation (ISO-3).
##
## The player is still ONE real person moving in continuous world coordinates —
## not a unit being commanded. Movement is direct WASD; there is no mouse-look and
## the camera is NOT a child of this body (an external IsometricCamera frames it).
## Locomotion is camera-relative by default so "up" on the keyboard always means
## "away from the camera" regardless of how the view is rotated — proven usable in
## IsometricCameraSmoke / IsometricExteriorSmoke.
##
## Nothing here is authoritative: the body's transform is presentation. The
## player's authoritative location is owned by Python; this node is placed at the
## authoritative spawn coordinate and reports its continuous position back for
## focus/interaction, never a tile.

@export var walk_speed: float = 4.5
@export var sprint_speed: float = 9.0
@export var camera_relative: bool = true

const _GRAVITY := 20.0
const _CAPSULE_R := 0.35
const _CAPSULE_H := 1.8
# Below this planar speed (m/s) the body reads as standing still, so idle drift
# from move_and_slide never spins the model or triggers a walk cycle.
const _IDLE_SPEED := 0.15
# How fast the body turns toward its heading, per physics tick (0..1 lerp factor).
const _TURN_RATE := 0.25

var camera: Camera3D = null       # framing camera; supplies the movement basis
var movement_enabled: bool = true # gate (e.g. while a modal UI is open)

## The visible character model (a CitizenAvatar), attached via set_body. Purely
## presentation — the body's transform is driven from this node's velocity, never
## the other way round. Null until a body is attached (headless tests, etc.).
var body: Node3D = null
var _facing: float = 0.0          # smoothed heading yaw the body is turned to


func _ready() -> void:
	# Authoritative collision identity (AS-PHYS-0), same profile as the
	# first-person walker — the presentation differs, the body does not.
	collision_layer = CollisionLayers.PLAYER
	collision_mask = CollisionLayers.PROFILES["player"]["mask"]
	var capsule := CapsuleShape3D.new()
	capsule.radius = _CAPSULE_R
	capsule.height = _CAPSULE_H
	var col := CollisionShape3D.new()
	col.shape = capsule
	col.position = Vector3(0.0, 0.9, 0.0)   # feet near y=0
	add_child(col)
	# PAUSABLE so an authoritative pause (get_tree().paused) freezes the player.
	process_mode = Node.PROCESS_MODE_PAUSABLE


func set_camera(cam: Camera3D) -> void:
	camera = cam


## Attach (or replace) the visible character model. The avatar is parented at the
## player's origin, so its feet sit at y=0 exactly like the collision capsule.
func set_body(avatar: Node3D) -> void:
	if body != null and is_instance_valid(body):
		if body.get_parent() == self:
			remove_child(body)
		body.queue_free()
	body = avatar
	if avatar.get_parent() != self:
		add_child(avatar)
	avatar.position = Vector3.ZERO


## Map a planar speed to a gait amplitude (0 idle, 0.5 walk, 1.0 run) — the same
## channel the crowd shader uses to drive the walk cycle. Run kicks in at the
## midpoint between walk and sprint so a normal walk never reads as a run.
static func gait_for_speed(speed: float, walk_speed: float, sprint_speed: float) -> float:
	if speed < _IDLE_SPEED:
		return 0.0
	if speed >= (walk_speed + sprint_speed) * 0.5:
		return 1.0
	return 0.5


func _update_body() -> void:
	if body == null or not is_instance_valid(body):
		return
	var planar := Vector2(velocity.x, velocity.z)
	var speed := planar.length()
	if speed > _IDLE_SPEED:
		# Heading from motion, same convention as the crowd (atan2(x, z)); retain
		# the last heading while stationary so the body doesn't snap back to 0.
		_facing = lerp_angle(_facing, atan2(velocity.x, velocity.z), _TURN_RATE)
	if body.has_method("set_heading"):
		body.set_heading(_facing)
	if body.has_method("set_gait"):
		body.set_gait(gait_for_speed(speed, walk_speed, sprint_speed))


## Move the player to a continuous world position and stop it dead. Used for
## authoritative interior enter/leave staging (coordinate continuity is owned by
## the world orchestrator, exactly as the first-person path does it).
func teleport(pos: Vector3) -> void:
	position = pos
	velocity = Vector3.ZERO


func _physics_process(delta: float) -> void:
	var input_dir := Vector2.ZERO
	if movement_enabled:
		input_dir = Input.get_vector("move_left", "move_right", "move_forward", "move_back")

	var flat_fwd := Vector3(0.0, 0.0, -1.0)
	var flat_right := Vector3(1.0, 0.0, 0.0)
	if camera_relative and camera != null and is_instance_valid(camera):
		# Derive the movement basis from the camera's ACTUAL orientation, projected
		# onto the ground. This stays correct under any pitch/yaw/rotation without
		# trigonometry, and never touches the camera's or player's world position.
		var b := camera.global_transform.basis
		var f := -b.z
		f.y = 0.0
		var r := b.x
		r.y = 0.0
		if f.length() > 0.001:
			flat_fwd = f.normalized()
		if r.length() > 0.001:
			flat_right = r.normalized()

	# input_dir.y is +1 for "back" (S) and -1 for "forward" (W); pushing forward
	# should move away from the camera (along flat_fwd), hence the negation.
	var dir := (flat_right * input_dir.x - flat_fwd * input_dir.y)
	if dir.length() > 1.0:
		dir = dir.normalized()

	var speed := sprint_speed if Input.is_action_pressed("sprint") else walk_speed
	velocity.x = dir.x * speed
	velocity.z = dir.z * speed

	if not is_on_floor():
		velocity.y -= _GRAVITY * delta
	else:
		velocity.y = 0.0

	move_and_slide()
	_update_body()
