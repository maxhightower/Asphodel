extends Node

## IsometricCameraSmoke — ISO-1 certification (headless, no bridge).
##
## Proves the isometric camera is a pure PRESENTATION transform: it is
## orthographic, follows a moving target, zooms within bounds, rotates in 90°
## steps, and NEVER changes the target's continuous world coordinates (no tile
## snapping, no rounding).
##
##   godot --headless --path godot res://tests/IsometricCameraSmoke.tscn

const IsometricCameraScript = preload("res://scripts/isometric_camera.gd")

var _fail := 0


func _check(cond: bool, label: String) -> void:
	if cond:
		print("  ok  %s" % label)
	else:
		_fail += 1
		push_error("FAIL: %s" % label)
		print("  FAIL: %s" % label)


func _ready() -> void:
	print("== IsometricCameraSmoke ==")
	var root := Node3D.new()
	add_child(root)

	# A continuous, deliberately non-integer target position (would reveal snapping).
	var player := Node3D.new()
	var p0 := Vector3(123.456, 0.0, -78.9)
	player.position = p0
	root.add_child(player)

	var cam: IsometricCamera = IsometricCameraScript.new()
	root.add_child(cam)
	cam.set_target(player)

	await get_tree().process_frame
	await get_tree().process_frame

	# --- projection ---------------------------------------------------------
	_check(cam.projection == Camera3D.PROJECTION_ORTHOGONAL, "camera is orthographic")
	_check(cam.is_orthographic(), "is_orthographic() reports true")
	_check(cam.current, "camera is current")

	# --- follow + coordinate preservation -----------------------------------
	_check(player.global_position.is_equal_approx(p0),
		"target world position unchanged after camera attach")
	var cam_pos_before: Vector3 = cam.global_position
	var p1 := Vector3(900.0, 0.0, 640.0)
	var d_initial: float = cam.get_focus().distance_to(p1)
	player.position = p1
	for i in range(60):
		await get_tree().process_frame
	_check(player.global_position.is_equal_approx(p1),
		"target world position unchanged by camera follow (no snapping)")
	# Smooth follow: the focus should have travelled most of the way toward the
	# moved target (headless process-frame delta varies, so assert >=70% progress
	# rather than a fixed metre tolerance).
	var d_after: float = cam.get_focus().distance_to(p1)
	_check(d_after < d_initial * 0.3,
		"camera focus smoothly tracks the moved target (%.0f%% closed)"
			% ((1.0 - d_after / d_initial) * 100.0))
	# And settling snaps the focus exactly onto the continuous target position.
	cam.settle()
	_check(cam.get_focus().distance_to(p1) < 0.01,
		"camera focus settles exactly on the target")
	_check(cam.global_position.distance_to(cam_pos_before) > 100.0,
		"camera itself actually moved to follow")
	# The camera must look down at the target, not be level with it.
	_check(cam.global_position.y > player.global_position.y + 50.0,
		"camera sits well above the target (elevated 3/4 view)")

	# --- zoom (bounded) -----------------------------------------------------
	var size_mid: float = cam.ortho_size
	for i in range(3):
		cam.zoom_in()
	_check(cam.ortho_size < size_mid, "zoom_in reduces the ortho size (%.1f < %.1f)" % [cam.ortho_size, size_mid])
	_check(is_equal_approx(cam.size, cam.ortho_size), "applied viewport size matches ortho_size immediately")
	for i in range(40):
		cam.zoom_in()
	_check(cam.ortho_size >= cam.min_ortho - 0.001 and cam.ortho_size <= cam.min_ortho + 0.001,
		"zoom_in is clamped at min_ortho (%.1f)" % cam.ortho_size)
	for i in range(80):
		cam.zoom_out()
	_check(cam.ortho_size >= cam.max_ortho - 0.001 and cam.ortho_size <= cam.max_ortho + 0.001,
		"zoom_out is clamped at max_ortho (%.1f)" % cam.ortho_size)
	# Zooming did not move the target.
	_check(player.global_position.is_equal_approx(p1), "target unchanged by zoom")

	# --- 90-degree rotation -------------------------------------------------
	cam.set_zoom(60.0)
	cam.settle()
	var yaw_before: float = cam.get_yaw_rad()
	var focus_before: Vector3 = cam.get_focus()
	var campos_before: Vector3 = cam.global_position
	cam.rotate_left()
	cam.settle()
	await get_tree().process_frame
	var dyaw: float = rad_to_deg(cam.get_yaw_rad() - yaw_before)
	_check(abs(abs(dyaw) - 90.0) < 0.5, "rotate_left turns the view by 90° (%.1f°)" % dyaw)
	_check(cam.get_focus().distance_to(focus_before) < 1.0,
		"rotation keeps the same focus point")
	_check(cam.global_position.distance_to(campos_before) > 10.0,
		"rotation actually swings the camera around the target")
	_check(player.global_position.is_equal_approx(p1), "target unchanged by rotation")
	# rotate back
	cam.rotate_right()
	cam.settle()
	_check(abs(rad_to_deg(cam.get_yaw_rad()) - rad_to_deg(yaw_before)) < 0.5,
		"rotate_right returns to the original yaw")

	print("== IsometricCameraSmoke done: %d failure(s) ==" % _fail)
	get_tree().quit(1 if _fail > 0 else 0)
