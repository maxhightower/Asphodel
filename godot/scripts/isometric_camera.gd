class_name IsometricCamera
extends Camera3D

## Continuous-coordinate isometric / near-orthographic camera rig (ISO-1).
##
## A single orthographic Camera3D that smoothly follows a target Node3D from an
## elevated 3/4 vantage. It is PRESENTATION ONLY: it never reads, writes, snaps,
## or rounds any authoritative or entity position. The target moves in continuous
## world coordinates; the camera merely frames it. Zoom changes only the ortho
## viewport size; a 90-degree rotate changes only the orbit yaw. No world
## coordinate is ever transformed by this node — proven by IsometricCameraSmoke.
##
## The camera keeps framing while the tree is paused (PROCESS_MODE_ALWAYS) so a
## paused scene still reads correctly; it does not advance any simulation.

@export var pitch_deg: float = 40.0        # downward tilt (35-45 is the sweet spot)
@export var yaw_deg: float = 45.0          # orbit around the target about world +Y
@export var ortho_size: float = 60.0       # world metres across the viewport height
@export var min_ortho: float = 16.0        # closest zoom
@export var max_ortho: float = 260.0       # farthest zoom
@export var zoom_factor: float = 1.18      # multiplicative zoom per step
@export var follow_lerp: float = 8.0       # follow snappiness (<=0 = instant)
@export var rotate_lerp: float = 9.0       # 90-degree turn animation speed
@export var boom_length: float = 1200.0    # metres back along the view axis

# Under an orthographic projection the boom length changes only depth sorting and
# near/far clipping, never apparent scale — so it is generous enough to keep the
# whole vertical column of a tall building in front of the near plane.

var _target: Node3D = null
var _focus: Vector3 = Vector3.ZERO         # smoothed ground focus (continuous world coords)
var _yaw_current: float = 45.0             # animated orbit yaw (degrees, unwrapped)
var _yaw_target: float = 45.0


func _ready() -> void:
	projection = PROJECTION_ORTHOGONAL
	size = ortho_size
	near = 0.1
	far = boom_length * 2.0 + 6000.0
	_yaw_current = yaw_deg
	_yaw_target = yaw_deg
	current = true
	# Frame even while the authoritative world is paused; framing is not simulation.
	process_mode = Node.PROCESS_MODE_ALWAYS
	_apply_transform(true)


## Bind the node the camera follows (usually the player). Snaps to it at once.
func set_target(t: Node3D) -> void:
	_target = t
	if t != null and is_instance_valid(t):
		_focus = t.global_position
	_apply_transform(true)


## The continuous world point the camera is currently centred on. Drive exterior
## chunk streaming from this (it follows the player, but is presentation-derived).
func get_focus() -> Vector3:
	return _focus


## Current orbit yaw in radians — used by the player for camera-relative movement.
func get_yaw_rad() -> float:
	return deg_to_rad(_yaw_current)


func is_orthographic() -> bool:
	return projection == PROJECTION_ORTHOGONAL


# --------------------------------------------------------------- zoom / rotate
func zoom_in() -> void:
	ortho_size = clampf(ortho_size / zoom_factor, min_ortho, max_ortho)
	size = ortho_size   # apply at once so reads don't wait for the next frame


func zoom_out() -> void:
	ortho_size = clampf(ortho_size * zoom_factor, min_ortho, max_ortho)
	size = ortho_size


func set_zoom(sz: float) -> void:
	ortho_size = clampf(sz, min_ortho, max_ortho)
	size = ortho_size


func rotate_left() -> void:
	_yaw_target += 90.0


func rotate_right() -> void:
	_yaw_target -= 90.0


## Immediately settle any in-progress rotate/follow (used by tests and teleports).
func settle() -> void:
	_yaw_current = _yaw_target
	if _target != null and is_instance_valid(_target):
		_focus = _target.global_position
	_apply_transform(true)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed:
		if event.button_index == MOUSE_BUTTON_WHEEL_UP:
			zoom_in()
		elif event.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			zoom_out()
	elif event is InputEventKey and event.pressed and not event.echo:
		if InputMap.has_action("cam_rotate_left") and event.is_action_pressed("cam_rotate_left"):
			rotate_left()
		elif InputMap.has_action("cam_rotate_right") and event.is_action_pressed("cam_rotate_right"):
			rotate_right()
		elif InputMap.has_action("cam_zoom_in") and event.is_action_pressed("cam_zoom_in"):
			zoom_in()
		elif InputMap.has_action("cam_zoom_out") and event.is_action_pressed("cam_zoom_out"):
			zoom_out()


func _process(delta: float) -> void:
	# Smooth follow: ease the focus toward the target's CURRENT continuous position.
	if _target != null and is_instance_valid(_target):
		var desired: Vector3 = _target.global_position
		if follow_lerp <= 0.0:
			_focus = desired
		else:
			_focus = _focus.lerp(desired, clampf(follow_lerp * delta, 0.0, 1.0))
	# Ease the orbit yaw toward the current 90-degree target (both unwrapped degrees).
	if not is_equal_approx(_yaw_current, _yaw_target):
		_yaw_current = lerpf(_yaw_current, _yaw_target, clampf(rotate_lerp * delta, 0.0, 1.0))
		if absf(_yaw_current - _yaw_target) < 0.05:
			_yaw_current = _yaw_target
	_apply_transform(false)


func _apply_transform(_snap: bool) -> void:
	var pitch := deg_to_rad(pitch_deg)
	var yaw := deg_to_rad(_yaw_current)
	# Horizontal direction on the ground from the focus toward the camera.
	var dir_h := Vector3(sin(yaw), 0.0, cos(yaw))
	var offset := boom_length * (dir_h * cos(pitch) + Vector3.UP * sin(pitch))
	global_position = _focus + offset
	look_at(_focus, Vector3.UP)
	size = ortho_size
