extends Node

## CursorIndicatorGate — the isometric view marks the ground point under the cursor.
##
## The interaction layer already reads the mouse and the highlight already draws
## player/target rings, but nothing showed WHERE on the ground the cursor aims.
## This gate proves the two presentation-only pieces of the new cursor reticle,
## without a physics world or a real mouse:
##   * ray_ground_point projects a camera ray onto the flat ground plane (and
##     refuses a ray that is parallel to, or points away from, the plane);
##   * the highlight's cursor ring shows/hides and tracks a world position.
##
##   godot --headless --path godot res://tests/CursorIndicatorGate.tscn

const World = preload("res://scripts/isometric_world.gd")
const Highlight = preload("res://scripts/isometric_highlight.gd")

var _fail := 0


func _check(cond: bool, label: String) -> void:
	if cond:
		print("  ok  %s" % label)
	else:
		_fail += 1
		push_error("FAIL: %s" % label)
		print("  FAIL: %s" % label)


func _ready() -> void:
	print("== CursorIndicatorGate ==")
	_test_ray_ground_point()
	await _test_cursor_ring()
	print("== CursorIndicatorGate done: %d failure(s) ==" % _fail)
	get_tree().quit(1 if _fail > 0 else 0)


func _test_ray_ground_point() -> void:
	# Straight down onto y=0.
	var p = World.ray_ground_point(Vector3(0, 10, 0), Vector3(0, -1, 0), 0.0)
	_check(p is Vector3 and (p as Vector3).is_equal_approx(Vector3.ZERO),
		"straight-down ray meets the plane directly below the origin")

	# 45° down/forward: from (0,10,0) it must reach the plane 10 m out in x.
	var angled := Vector3(1, -1, 0).normalized()
	var p2 = World.ray_ground_point(Vector3(0, 10, 0), angled, 0.0)
	_check(p2 is Vector3 and (p2 as Vector3).is_equal_approx(Vector3(10, 0, 0)),
		"angled ray meets the plane at the projected point")

	# A non-zero ground height is honoured.
	var p3 = World.ray_ground_point(Vector3(2, 10, -4), Vector3(0, -1, 0), -0.5)
	_check(p3 is Vector3 and is_equal_approx((p3 as Vector3).y, -0.5),
		"the point lands on the requested ground height")

	# Parallel to the plane => no intersection.
	var par = World.ray_ground_point(Vector3(0, 10, 0), Vector3(1, 0, 0), 0.0)
	_check(par == null, "a ray parallel to the plane yields no point")

	# Pointing away from the plane (upward, plane below) => no intersection.
	var away = World.ray_ground_point(Vector3(0, 10, 0), Vector3(0, 1, 0), 0.0)
	_check(away == null, "a ray pointing away from the plane yields no point")


func _test_cursor_ring() -> void:
	var h: IsometricHighlight = Highlight.new()
	add_child(h)
	await get_tree().process_frame

	h.hide_cursor()
	_check(not h.is_cursor_visible(), "cursor ring starts/hides invisible")

	h.show_cursor(Vector3(5.0, 0.0, -3.0))
	_check(h.is_cursor_visible(), "show_cursor makes the cursor ring visible")
	var cp := h.get_cursor_position()
	_check(is_equal_approx(cp.x, 5.0) and is_equal_approx(cp.z, -3.0),
		"cursor ring tracks the cursor world position in x/z")
	_check(cp.y >= 0.0 and cp.y < 0.5,
		"cursor ring sits just above the ground")

	h.hide_cursor()
	_check(not h.is_cursor_visible(), "hide_cursor hides the ring again")

	h.queue_free()
