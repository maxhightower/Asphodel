extends Node3D

## Walkable first-person view of the loaded city, built from the bundle's real
## OSM data at metre scale: streets as drivable-width ribbons following the
## actual road polylines, buildings extruded from their footprint outlines
## (buildings.json), and the nearest ones fully enterable — doors, furnished
## rooms and lootable containers via the procedural interior generator. Visuals
## (sky, ground, wall palettes) come from a deterministic per-city style.

var _pause_layer: CanvasLayer
var _prompt_label: Label
var _inventory_label: Label
var _toast_label: Label
var _toast_tween: Tween


func _ready() -> void:
	_ensure_input()
	# ASPHODEL_BUNDLE lets headless smoke tests load any bundle without the menu
	var dir := OS.get_environment("ASPHODEL_BUNDLE")
	if dir == "":
		dir = Session.bundle_dir if Session.bundle_dir != "" else "res://sample_bundle"
	var bundle := BundleLoader.load_bundle(dir)
	if bundle.is_empty():
		push_error("street_world: failed to load bundle at %s — see errors above." % dir)
		return
	var meta: Dictionary = bundle["meta"]
	var zones: Array = bundle["zones"]
	var roads: Dictionary = bundle["roads"]
	var buildings: Array = BundleLoader.load_buildings(dir, zones)
	var style := CityStyle.for_city(str(meta.get("name", "city")))

	_add_environment_and_light(style)
	_build_ground(_world_bounds(zones), style)
	RoadBuilder.build(self, roads, style)

	var spawn := _pick_spawn(zones, buildings, roads)
	var stats := BuildingBuilder.build_all(self, buildings, style, spawn, roads)
	print("street_world: %d buildings (%d enterable), %d road polylines" % [
		stats["total"], stats["enterable"], (roads.get("polylines", []) as Array).size()])

	_spawn_player(spawn)
	_build_hud(meta)
	_build_pause_overlay()
	if OS.get_environment("ASPHODEL_SMOKE") != "":
		_smoke_report.call_deferred()
	if OS.get_environment("ASPHODEL_SHOT") != "":
		_capture_screenshot(OS.get_environment("ASPHODEL_SHOT"))


## Dev tool: render a few frames, save a screenshot, quit (needs a real
## rendering driver, e.g. xvfb-run + --rendering-method mobile).
func _capture_screenshot(path: String) -> void:
	for i in range(10):
		await get_tree().process_frame
	if OS.get_environment("ASPHODEL_SHOT_AERIAL") != "":
		var p := get_tree().get_first_node_in_group("player")
		if p != null:
			(p as Node3D).global_position += Vector3(0, 350, 0)
			var cam := (p as Node3D).find_children("", "Camera3D", true, false)
			if not cam.is_empty():
				(cam[0] as Camera3D).rotation.x = -PI / 2.0
	elif OS.get_environment("ASPHODEL_SHOT_INSIDE") != "":
		# teleport the player into the first enterable building for the shot
		for child in get_children():
			if child is Node3D and str(child.name).begins_with("Building_"):
				var player := get_tree().get_first_node_in_group("player")
				if player != null:
					(player as Node3D).global_position = \
						(child as Node3D).global_position + Vector3(1.2, 1.0, 1.2)
					(player as Node3D).rotation.y = randf() * TAU
				break
	for i in range(20):
		await get_tree().process_frame
	var img := get_viewport().get_texture().get_image()
	img.save_png(path)
	print("screenshot saved: ", path)
	get_tree().quit()


## Headless CI check: prove the generated world actually contains the survival
## loop pieces (doors + stocked containers) before anyone plays it.
func _smoke_report() -> void:
	var doors := 0
	var lootables := 0
	var lights := 0
	var stack: Array[Node] = [self]
	while not stack.is_empty():
		var n: Node = stack.pop_back()
		if n is DoorInteractable:
			doors += 1
		elif n is Lootable:
			lootables += 1
		elif n is OmniLight3D:
			lights += 1
		for child in n.get_children():
			stack.append(child)
	print("smoke: doors=%d lootables=%d interior_lights=%d" % [doors, lootables, lights])
	if doors == 0 or lootables == 0:
		printerr("smoke: FAILED — enterable buildings are missing doors or loot")


# ----------------------------------------------------------------- input setup
func _ensure_input() -> void:
	var binds := {
		"move_forward": KEY_W, "move_back": KEY_S,
		"move_left": KEY_A, "move_right": KEY_D, "sprint": KEY_SHIFT,
		"interact": KEY_E,
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


func _build_ground(b: Rect2, style: CityStyle) -> void:
	var center := Vector3(b.position.x + b.size.x * 0.5, 0.0, b.position.y + b.size.y * 0.5)
	var sx := b.size.x * 1.4
	var sz := b.size.y * 1.4

	var plane := PlaneMesh.new()
	plane.size = Vector2(sx, sz)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = style.grass
	mat.roughness = 1.0
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


## Spawn on the street in the middle of the busiest part of town: nearest road
## point to the centroid of the densest cluster of buildings.
func _pick_spawn(zones: Array, buildings: Array, roads: Dictionary) -> Vector2:
	var target := Vector2.ZERO
	if not buildings.is_empty():
		# densest zone center, refined by nearby building centroids
		var best_zone: Dictionary = zones[0]
		for z in zones:
			if float(z.get("density", 0.0)) > float(best_zone.get("density", 0.0)):
				best_zone = z
		var zc: Array = best_zone["center_xy"]
		var zone_center := Vector2(float(zc[0]), float(zc[1]))
		var acc := Vector2.ZERO
		var cnt := 0
		for b in buildings:
			var c: Array = b.get("center_xy", [0.0, 0.0])
			var v := Vector2(float(c[0]), float(c[1]))
			if v.distance_to(zone_center) < 400.0:
				acc += v
				cnt += 1
		target = (acc / cnt) if cnt > 0 else zone_center
	return RoadBuilder.closest_road_point(roads, target)


func _add_environment_and_light(style: CityStyle) -> void:
	var sky_mat := ProceduralSkyMaterial.new()
	sky_mat.sky_top_color = style.sky_top
	sky_mat.sky_horizon_color = style.sky_horizon
	sky_mat.ground_bottom_color = style.grass.darkened(0.4)
	sky_mat.ground_horizon_color = style.sky_horizon
	var sky := Sky.new()
	sky.sky_material = sky_mat

	var env := Environment.new()
	env.background_mode = Environment.BG_SKY
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_energy = 0.45
	env.fog_enabled = true
	env.fog_light_color = style.sky_horizon
	env.fog_density = 0.00025
	env.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	env.tonemap_exposure = 0.9
	var we := WorldEnvironment.new()
	we.environment = env
	add_child(we)

	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-48.0, -35.0, 0.0)
	sun.light_color = style.sun_color
	sun.light_energy = style.sun_energy * 0.75
	sun.shadow_enabled = true
	sun.directional_shadow_max_distance = 250.0
	add_child(sun)


# ----------------------------------------------------------------------- player
func _spawn_player(spawn: Vector2) -> void:
	var player := CharacterBody3D.new()
	player.set_script(load("res://scripts/first_person.gd"))
	player.position = Vector3(spawn.x, 1.5, spawn.y)
	add_child(player)
	player.prompt_changed.connect(_on_prompt_changed)
	player.inventory_changed.connect(_on_inventory_changed)
	player.looted.connect(_on_looted)


# -------------------------------------------------------------------------- HUD
func _build_hud(meta: Dictionary) -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var c: Dictionary = Session.citizen
	var who := Label.new()
	var city := str(meta.get("name", ""))
	who.text = city if c.is_empty() else "%s · %s — %s" % [
		str(c.get("name", "?")), str(c.get("occupation", "?")), city]
	who.position = Vector2(16, 12)
	who.add_theme_font_size_override("font_size", 18)
	layer.add_child(who)
	var hint := Label.new()
	hint.text = "WASD move · Shift sprint · mouse look · E interact · Esc menu"
	hint.position = Vector2(16, 38)
	hint.add_theme_font_size_override("font_size", 13)
	hint.modulate = Color(0.7, 0.75, 0.8)
	layer.add_child(hint)

	_inventory_label = Label.new()
	_inventory_label.set_anchors_preset(Control.PRESET_TOP_RIGHT)
	_inventory_label.position = Vector2(-320, 12)
	_inventory_label.custom_minimum_size = Vector2(300, 0)
	_inventory_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	_inventory_label.add_theme_font_size_override("font_size", 15)
	layer.add_child(_inventory_label)
	_on_inventory_changed({"food": 0, "water": 0, "meds": 0, "materials": 0, "valuables": 0})

	# centered reticle dot + interact prompt under it
	var reticle := ColorRect.new()
	reticle.color = Color(1, 1, 1, 0.7)
	reticle.custom_minimum_size = Vector2(4, 4)
	reticle.set_anchors_preset(Control.PRESET_CENTER)
	reticle.position = Vector2(-2, -2)
	layer.add_child(reticle)

	_prompt_label = Label.new()
	_prompt_label.set_anchors_preset(Control.PRESET_CENTER)
	_prompt_label.position = Vector2(-200, 28)
	_prompt_label.custom_minimum_size = Vector2(400, 0)
	_prompt_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_prompt_label.add_theme_font_size_override("font_size", 17)
	layer.add_child(_prompt_label)

	_toast_label = Label.new()
	_toast_label.set_anchors_preset(Control.PRESET_CENTER)
	_toast_label.position = Vector2(-200, 64)
	_toast_label.custom_minimum_size = Vector2(400, 0)
	_toast_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_toast_label.add_theme_font_size_override("font_size", 15)
	_toast_label.modulate = Color(0.85, 0.95, 0.7, 0.0)
	layer.add_child(_toast_label)


func _on_prompt_changed(text: String) -> void:
	if _prompt_label != null:
		_prompt_label.text = text


func _on_inventory_changed(inv: Dictionary) -> void:
	if _inventory_label == null:
		return
	_inventory_label.text = "Food %d · Water %d · Meds %d · Materials %d · Valuables %d" % [
		int(inv.get("food", 0)), int(inv.get("water", 0)), int(inv.get("meds", 0)),
		int(inv.get("materials", 0)), int(inv.get("valuables", 0))]


func _on_looted(items: Dictionary) -> void:
	if _toast_label == null:
		return
	var parts: Array[String] = []
	for k in items:
		parts.append("+%d %s" % [int(items[k]), str(k)])
	_toast_label.text = "  ".join(parts)
	if _toast_tween != null and _toast_tween.is_valid():
		_toast_tween.kill()
	_toast_label.modulate.a = 1.0
	_toast_tween = create_tween()
	_toast_tween.tween_interval(1.4)
	_toast_tween.tween_property(_toast_label, "modulate:a", 0.0, 0.8)


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
