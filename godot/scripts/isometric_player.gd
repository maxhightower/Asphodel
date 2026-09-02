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

var camera: Camera3D = null       # framing camera; supplies the movement basis
var movement_enabled: bool = true # gate (e.g. while a modal UI is open)


func _ready() -> void:
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
