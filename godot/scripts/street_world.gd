extends Node3D

## Walkable first-person view of the *full* loaded city: builds the bundle's
## density blocks + major roads at real metre scale, with ground + per-block
## collision, spawns a first-person player on a road, and provides a HUD + Esc
## pause overlay. Self-contained (does not touch the bird's-eye CityScene).

const FOOTPRINT_FRAC := 0.16   # must match city_builder so blocks line up
const HEIGHT_SCALE := 3.0
const LOW := Color(0.35, 0.45, 0.55)
const HIGH := Color(0.95, 0.85, 0.55)

var _pause_layer: CanvasLayer


func _ready() -> void:
	_ensure_input()
	var dir: String = Session.bundle_dir if Session.bundle_dir != "" else "res://sample_bundle"
	var bundle := BundleLoader.load_bundle(dir)
	if bundle.is_empty():
		push_error("street_world: failed to load bundle at %s — see errors above." % dir)
		return
	var meta: Dictionary = bundle["meta"]
	var zones: Array = bundle["zones"]
	_add_environment_and_light()
	var bounds := _world_bounds(zones)
	_build_ground(bounds)
	_build_blocks(meta, zones)
	_build_roads(bundle["roads"])
	_spawn_player(bounds, bundle["roads"])
	_build_hud()
	_build_pause_overlay()


# ----------------------------------------------------------------- input setup
func _ensure_input() -> void:
	var binds := {
		"move_forward": KEY_W, "move_back": KEY_S,
		"move_left": KEY_A, "move_right": KEY_D, "sprint": KEY_SHIFT,
	}
	for action in binds:
		if InputMap.has_action(action):
			continue
		InputMap.add_action(action)
		var ev := InputEventKey.new()
		ev.physical_keycode = binds[action]
		InputMap.action_add_event(action, ev)


# --------------------------------------------------------------------- geometry
func _world_bounds(zones: Array) -> Rect2:
	var min_x := INF
	var min_z := INF
	var max_x := -INF
	var max_z := -INF
	for z in zones:
		var c: Array = z["center_xy"]
		var e: Array = z["extent"]
		min_x = min(min_x, float(c[0]) - float(e[0]) * 0.5)
		max_x = max(max_x, float(c[0]) + float(e[0]) * 0.5)
		min_z = min(min_z, float(c[1]) - float(e[1]) * 0.5)
		max_z = max(max_z, float(c[1]) + float(e[1]) * 0.5)
	return Rect2(min_x, min_z, max_x - min_x, max_z - min_z)


func _build_ground(b: Rect2) -> void:
	var center := Vector3(b.position.x + b.size.x * 0.5, 0.0, b.position.y + b.size.y * 0.5)
	var sx := b.size.x * 1.4
	var sz := b.size.y * 1.4

	var plane := PlaneMesh.new()
	plane.size = Vector2(sx, sz)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.12, 0.14, 0.17)
	plane.material = mat
	var mi := MeshInstance3D.new()
	mi.mesh = plane
	mi.position = center
	add_child(mi)

	var body := StaticBody3D.new()
	var shape := BoxShape3D.new()
	shape.size = Vector3(sx, 1.0, sz)
	var cs := CollisionShape3D.new()
	cs.shape = shape
	cs.position = center + Vector3(0.0, -0.5, 0.0)   # top surface at y=0
	body.add_child(cs)
	add_child(body)


func _build_blocks(meta: Dictionary, zones: Array) -> void:
	var total := 0
	for z in zones:
		total += (z.get("blocks", []) as Array).size()
	if total == 0:
		return
	var side: float = float(meta.get("grid", {}).get("cell_m", 100.0)) * FOOTPRINT_FRAC

	var box := BoxMesh.new()
	box.size = Vector3.ONE
	var mat := StandardMaterial3D.new()
	mat.vertex_color_use_as_albedo = true
	mat.roughness = 0.9
	box.material = mat

	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.use_colors = true
	mm.mesh = box
	mm.instance_count = total

	var body := StaticBody3D.new()   # one body, a box shape per building
	add_child(body)

	var i := 0
	for z in zones:
		var density := float(z.get("density", 0.0))
		var col := LOW.lerp(HIGH, clampf(density, 0.0, 1.0))
		for blk in (z.get("blocks", []) as Array):
			var bxy: Array = blk["xy"]
			var h := float(blk["height"]) * HEIGHT_SCALE
			var origin := Vector3(float(bxy[0]), h * 0.5, float(bxy[1]))
			mm.set_instance_transform(i, Transform3D(Basis().scaled(Vector3(side, h, side)), origin))
			mm.set_instance_color(i, col)
			var shape := BoxShape3D.new()
			shape.size = Vector3(side, h, side)
			var cs := CollisionShape3D.new()
			cs.shape = shape
			cs.position = origin
			body.add_child(cs)
			i += 1

	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	add_child(mmi)


func _build_roads(roads: Dictionary) -> void:
	var polylines: Array = roads.get("polylines", [])
	if polylines.is_empty():
		return
	var im := ImmediateMesh.new()
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_color = Color(0.85, 0.85, 0.9)
	for pl in polylines:
		var pts: Array = pl.get("points", [])
		if pts.size() < 2:
			continue
		im.surface_begin(Mesh.PRIMITIVE_LINE_STRIP, mat)
		for p in pts:
			im.surface_add_vertex(Vector3(float(p[0]), 0.1, float(p[1])))
		im.surface_end()
	var mi := MeshInstance3D.new()
	mi.mesh = im
	add_child(mi)


func _add_environment_and_light() -> void:
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.5, 0.6, 0.72)   # daytime sky-ish
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.6, 0.64, 0.7)
	env.ambient_light_energy = 0.6
	env.fog_enabled = true
	env.fog_light_color = Color(0.5, 0.6, 0.72)
	env.fog_density = 0.0006
	var we := WorldEnvironment.new()
	we.environment = env
	add_child(we)

	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-50.0, -50.0, 0.0)
	sun.light_energy = 1.1
	sun.shadow_enabled = true
	add_child(sun)


# ----------------------------------------------------------------------- player
func _spawn_player(b: Rect2, roads: Dictionary) -> void:
	var pos := Vector3(b.position.x + b.size.x * 0.5, 3.0, b.position.y + b.size.y * 0.5)
	var polylines: Array = roads.get("polylines", [])
	if polylines.size() > 0:
		var pts: Array = polylines[0].get("points", [])
		if pts.size() > 0:
			pos = Vector3(float(pts[0][0]), 3.0, float(pts[0][1]))
	var player := CharacterBody3D.new()
	player.set_script(load("res://scripts/first_person.gd"))
	player.position = pos
	add_child(player)


# -------------------------------------------------------------------------- HUD
func _build_hud() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var c: Dictionary = Session.citizen
	var who := Label.new()
	who.text = "" if c.is_empty() else "%s · %s" % [str(c.get("name", "?")), str(c.get("occupation", "?"))]
	who.position = Vector2(16, 12)
	who.add_theme_font_size_override("font_size", 18)
	layer.add_child(who)
	var hint := Label.new()
	hint.text = "WASD move · Shift sprint · mouse look · Esc menu"
	hint.position = Vector2(16, 38)
	hint.add_theme_font_size_override("font_size", 13)
	hint.modulate = Color(0.7, 0.75, 0.8)
	layer.add_child(hint)


# ------------------------------------------------------------------ pause / Esc
func _build_pause_overlay() -> void:
	_pause_layer = CanvasLayer.new()
	_pause_layer.visible = false
	add_child(_pause_layer)
	var dim := ColorRect.new()
	dim.color = Color(0.0, 0.0, 0.0, 0.6)
	dim.set_anchors_preset(Control.PRESET_FULL_RECT)
	_pause_layer.add_child(dim)
	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	_pause_layer.add_child(center)
	var vb := VBoxContainer.new()
	vb.add_theme_constant_override("separation", 12)
	center.add_child(vb)
	var title := Label.new()
	title.text = "Paused"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 36)
	vb.add_child(title)
	vb.add_child(_overlay_button("Resume", _resume))
	vb.add_child(_overlay_button("Back to Menu", _to_menu))


func _overlay_button(text: String, handler: Callable) -> Button:
	var b := Button.new()
	b.text = text
	b.custom_minimum_size = Vector2(260, 46)
	b.add_theme_font_size_override("font_size", 22)
	b.pressed.connect(handler)
	return b


func _resume() -> void:
	_pause_layer.visible = false
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _to_menu() -> void:
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	get_tree().change_scene_to_file("res://MainMenu.tscn")


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_cancel"):
		if _pause_layer != null and _pause_layer.visible:
			_resume()
		elif _pause_layer != null:
			_pause_layer.visible = true
			Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
