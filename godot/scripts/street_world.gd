extends Node3D

## Walkable first-person view of the loaded city. Unlike the earlier version this
## scene is a *client of the authoritative world*: it spawns the selected citizen
## at their real coordinate, drives the GameClock (which advances the outbreak),
## renders blocks at their true footprint, freezes everything on an authoritative
## pause, and recovers the player if they leave the ground.
##
## process_mode is ALWAYS so this node keeps handling Esc while the tree is
## paused; the player and GameClock are PAUSABLE, so they freeze when paused.

const HEIGHT_SCALE := 3.0
const LOW := Color(0.35, 0.45, 0.55)
const HIGH := Color(0.95, 0.85, 0.55)
const PLAYER_RADIUS := 0.5
const FALL_KILL_Y := -40.0          # below this, the player is out of bounds

var _pause_layer: CanvasLayer
var _player: CharacterBody3D
var _spawn_pos: Vector3
var _bounds: Rect2
var _block_boxes: Array = []        # [Vector3(x, z, half_extent), ...]
var _env: Environment
var _sun: DirectionalLight3D
var _time_label: Label
var _outbreak_label: Label

# Live citizen rendering (M6/BW4) + player-position focus (BW3).
var _zones: Array = []
var _zone_map: ZoneMap
var _citizen_render: Node3D
var _current_focus_zone: int = -1
var _last_render_tick: int = -1


func _ready() -> void:
	# Keep processing input while paused so Esc can resume.
	process_mode = Node.PROCESS_MODE_ALWAYS
	_ensure_input()
	var dir: String = Session.bundle_dir if Session.bundle_dir != "" else "res://sample_bundle"
	var bundle := BundleLoader.load_bundle(dir)
	if bundle.is_empty():
		push_error("street_world: failed to load bundle at %s — see errors above." % dir)
		return
	var meta: Dictionary = bundle["meta"]
	var zones: Array = bundle["zones"]
	_zones = zones
	_add_environment_and_light()
	_bounds = _world_bounds(zones)
	_build_ground(_bounds)
	_build_blocks(meta, zones)
	_build_roads(bundle["roads"])
	_spawn_player(_bounds, bundle["roads"])
	_build_hud()
	_build_pause_overlay()

	# Authoritative clock: start at the citizen's spawn hour; it advances the
	# outbreak while unpaused. The outbreak itself is owned by the live Python
	# World, reached through SimBridge (M1) — not by any baked timeline.
	var start_hour := 8.0
	var c: Dictionary = Session.citizen
	if c.has("spawn_hour"):
		start_hour = float(c["spawn_hour"])
	GameClock.reset()
	GameClock.configure(meta, start_hour)
	_connect_live_world(dir, meta)
	GameClock.ticked.connect(_on_clock_ticked)
	_on_clock_ticked(GameClock.game_day, GameClock.hour, GameClock.outbreak_belief())


func _connect_live_world(dir: String, meta: Dictionary) -> void:
	## Bring up the authoritative Python World for this city and bind it to the
	## clock. If the sim process isn't reachable the scene still runs (the clock
	## keeps time; the outbreak simply holds), so play is never hard-blocked.
	var bundle_name := dir.get_file()          # e.g. res://bundles/houston -> houston
	if not SimBridge.connect_to_sim():
		push_warning("street_world: no live World bridge — outbreak will hold. "
			+ "Start it with: python -m asphodel.bridge.server")
		return
	var opts := {"seed": int(meta.get("seed", 0))}
	var started: Dictionary = SimBridge.start_world(bundle_name, opts)
	if not started.get("ok", false):
		push_warning("street_world: START_WORLD failed: %s" % str(started))
		SimBridge.disconnect_from_sim()
		return
	GameClock.bind_bridge(SimBridge)
	# BW3: resolve the player's world position -> zone via the SAME frame the
	# bundle uses, and focus it so the neighbourhood the player stands in resolves
	# to live agents.
	_zone_map = ZoneMap.new()
	_zone_map.load_from_zones(_zones)
	_current_focus_zone = _zone_map.zone_of_xy(_player.position.x, _player.position.z)
	SimBridge.set_focus([_current_focus_zone])
	# BW4: a MultiMesh renderer that draws the promoted bubble from live snapshots.
	_citizen_render = load("res://scripts/citizen_render.gd").new()
	_citizen_render.process_mode = Node.PROCESS_MODE_PAUSABLE
	add_child(_citizen_render)
	# Prime the initial outbreak from an authoritative snapshot.
	var snap: Dictionary = SimBridge.snapshot()
	if snap.get("ok", false):
		GameClock.apply_outbreak(SimBridge._mean_belief_from(snap))
		SimBridge.last_world = snap.get("world", {})
		_render_live()


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
			# Use the block's OWN stored footprint so the visual box and its
			# collision box agree and match the bundle's geometry -- no more
			# constant giant width that punched through roads.
			var side := float(blk.get("footprint", 6.0))
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
			# Remember the XZ footprint for collision-safe player placement.
			_block_boxes.append(Vector3(float(bxy[0]), float(bxy[1]), side * 0.5))
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
	# One surface of line SEGMENTS for the whole road network. (One surface per
	# polyline overflowed the GLES3 MAX_MESH_SURFACES cap on big cities like
	# Houston, which has hundreds of roads.)
	im.surface_begin(Mesh.PRIMITIVE_LINES, mat)
	for pl in polylines:
		var pts: Array = pl.get("points", [])
		if pts.size() < 2:
			continue
		for k in range(pts.size() - 1):
			var a: Array = pts[k]
			var b: Array = pts[k + 1]
			im.surface_add_vertex(Vector3(float(a[0]), 0.1, float(a[1])))
			im.surface_add_vertex(Vector3(float(b[0]), 0.1, float(b[1])))
	im.surface_end()
	var mi := MeshInstance3D.new()
	mi.mesh = im
	add_child(mi)


func _add_environment_and_light() -> void:
	_env = Environment.new()
	_env.background_mode = Environment.BG_COLOR
	_env.background_color = Color(0.5, 0.6, 0.72)
	_env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	_env.ambient_light_color = Color(0.6, 0.64, 0.7)
	_env.ambient_light_energy = 0.6
	_env.fog_enabled = true
	_env.fog_light_color = Color(0.5, 0.6, 0.72)
	_env.fog_density = 0.0006
	var we := WorldEnvironment.new()
	we.environment = _env
	add_child(we)

	_sun = DirectionalLight3D.new()
	_sun.rotation_degrees = Vector3(-50.0, -50.0, 0.0)
	_sun.light_energy = 1.1
	_sun.shadow_enabled = true
	add_child(_sun)


# ----------------------------------------------------------------------- player
func _spawn_player(b: Rect2, roads: Dictionary) -> void:
	# Authoritative spawn: the selected citizen's own coordinate for their state
	# (home when asleep, workplace on shift, a route point mid-commute). Fall
	# back to a road point, then the city centre, only as a documented fail-safe.
	var desired := Vector2(b.position.x + b.size.x * 0.5, b.position.y + b.size.y * 0.5)
	var have_citizen := false
	var c: Dictionary = Session.citizen
	if c.has("spawn_xy") and c["spawn_xy"] != null:
		var sp: Array = c["spawn_xy"]
		if sp.size() >= 2:
			desired = Vector2(float(sp[0]), float(sp[1]))
			have_citizen = true
	if not have_citizen:
		var polylines: Array = roads.get("polylines", [])
		if polylines.size() > 0:
			var pts: Array = polylines[0].get("points", [])
			if pts.size() > 0:
				desired = Vector2(float(pts[0][0]), float(pts[0][1]))

	var clear := _find_clear_spawn(desired)
	_spawn_pos = Vector3(clear.x, 3.0, clear.y)   # a little above ground; falls to floor

	_player = CharacterBody3D.new()
	_player.set_script(load("res://scripts/first_person.gd"))
	_player.position = _spawn_pos
	# PAUSABLE so player physics freezes when the world is paused.
	_player.process_mode = Node.PROCESS_MODE_PAUSABLE
	add_child(_player)


func _find_clear_spawn(desired: Vector2) -> Vector2:
	## Return a point not inside any building footprint. Tries the desired point,
	## then a widening ring of candidates around it, then gives up on the desired
	## point (still above ground, never inside a wall).
	if not _inside_block(desired):
		return desired
	for ring in range(1, 16):
		var r := float(ring) * 4.0
		for k in range(8):
			var a := TAU * float(k) / 8.0
			var cand := desired + Vector2(cos(a), sin(a)) * r
			if not _inside_block(cand):
				return cand
	return desired


func _inside_block(p: Vector2) -> bool:
	for bb in _block_boxes:
		var half: float = bb.z + PLAYER_RADIUS
		if abs(p.x - bb.x) <= half and abs(p.y - bb.y) <= half:
			return true
	return false


# -------------------------------------------------------------------- HUD
func _build_hud() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var c: Dictionary = Session.citizen
	var who := Label.new()
	who.text = "" if c.is_empty() else "%s · %s" % [str(c.get("name", "?")), str(c.get("occupation", "?"))]
	who.position = Vector2(16, 12)
	who.add_theme_font_size_override("font_size", 18)
	layer.add_child(who)

	_time_label = Label.new()
	_time_label.position = Vector2(16, 38)
	_time_label.add_theme_font_size_override("font_size", 16)
	_time_label.modulate = Color(0.85, 0.9, 0.95)
	layer.add_child(_time_label)

	_outbreak_label = Label.new()
	_outbreak_label.position = Vector2(16, 60)
	_outbreak_label.add_theme_font_size_override("font_size", 16)
	layer.add_child(_outbreak_label)

	var hint := Label.new()
	hint.text = "WASD move · Shift sprint · mouse look · Esc menu"
	hint.position = Vector2(16, 86)
	hint.add_theme_font_size_override("font_size", 13)
	hint.modulate = Color(0.7, 0.75, 0.8)
	layer.add_child(hint)


func _on_clock_ticked(_day: int, _hour: float, outbreak: float) -> void:
	if _time_label != null:
		_time_label.text = GameClock.time_string()
	if _outbreak_label != null:
		_outbreak_label.text = "Outbreak: %d%%" % int(round(outbreak * 100.0))
		_outbreak_label.modulate = Color(0.6, 0.7, 0.8).lerp(Color(1.0, 0.3, 0.25), outbreak)
	_apply_time_and_outbreak(outbreak)


func _apply_time_and_outbreak(outbreak: float) -> void:
	# Day/night from the clock hour + an ominous reddening as the outbreak grows,
	# so standing still and watching time pass visibly changes the world.
	if _env == null or _sun == null:
		return
	var day := GameClock.is_daytime()
	var day_sky := Color(0.5, 0.6, 0.72)
	var night_sky := Color(0.04, 0.05, 0.09)
	var base_sky := day_sky if day else night_sky
	var panic_sky := Color(0.35, 0.08, 0.08)
	_env.background_color = base_sky.lerp(panic_sky, outbreak * 0.7)
	_env.fog_light_color = _env.background_color
	_env.fog_density = 0.0006 + outbreak * 0.0025
	_sun.light_energy = (1.1 if day else 0.15) * (1.0 - 0.4 * outbreak)


# ------------------------------------------------------------------ per-frame
func _physics_process(_delta: float) -> void:
	# Out-of-bounds recovery: if the player falls off the finite ground, put them
	# back at a safe spawn instead of falling forever.
	if _player != null and _player.position.y < FALL_KILL_Y:
		_recover_player()
	_update_live_bubble()


func _update_live_bubble() -> void:
	## BW3: as the player crosses a zone boundary, move the authoritative focus so
	## the promoted micro bubble follows them. BW4: re-render when a new snapshot
	## (a new authoritative tick) has arrived. Guarded so an offline scene no-ops.
	if _zone_map == null or _player == null or not SimBridge.is_connected_to_sim():
		return
	var z := _zone_map.zone_of_xy(_player.position.x, _player.position.z)
	if z != _current_focus_zone and z >= 0:
		_current_focus_zone = z
		SimBridge.set_focus([z])
	var world: Dictionary = SimBridge.last_world
	var tick := int(world.get("tick", -1)) if not world.is_empty() else -1
	if tick != _last_render_tick:
		_last_render_tick = tick
		_render_live()


func _render_live() -> void:
	if _citizen_render == null or _current_focus_zone < 0:
		return
	var world: Dictionary = SimBridge.last_world
	if world.is_empty():
		return
	# Place the promoted zone's torus at the zone's real world centre.
	_citizen_render.render_snapshot(world, _current_focus_zone,
		_zone_center(_current_focus_zone))


func _recover_player() -> void:
	_player.velocity = Vector3.ZERO
	_player.position = _spawn_pos + Vector3(0.0, 2.0, 0.0)


# ------------------------------------------------------------------ pause / Esc
func _build_pause_overlay() -> void:
	_pause_layer = CanvasLayer.new()
	_pause_layer.visible = false
	# The pause UI must keep working while the tree is paused.
	_pause_layer.process_mode = Node.PROCESS_MODE_ALWAYS
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


func _pause() -> void:
	_pause_layer.visible = true
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	GameClock.set_paused(true)          # authoritative: freezes clock + outbreak + player


func _resume() -> void:
	_pause_layer.visible = false
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	GameClock.set_paused(false)


func _to_menu() -> void:
	GameClock.set_paused(false)
	GameClock.reset()
	# Tear down the authoritative world cleanly (sends SHUTDOWN) before leaving.
	if SimBridge.is_connected_to_sim():
		SimBridge.disconnect_from_sim()
	Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	get_tree().change_scene_to_file("res://MainMenu.tscn")


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_cancel"):
		if _pause_layer != null and _pause_layer.visible:
			_resume()
		elif _pause_layer != null:
			_pause()
	elif event.is_action_pressed("interact"):
		_try_interact()


func _try_interact() -> void:
	## BW5: engage the nearest identified citizen -> authoritative roster. Resolves
	## a citizen_id from the live snapshot and sends INTERACT_WITH; the citizen
	## becomes persistent (named) and is recognisable on return.
	if not SimBridge.is_connected_to_sim() or _current_focus_zone < 0:
		return
	var world: Dictionary = SimBridge.last_world
	var a: Dictionary = world.get("agents", {}).get(str(_current_focus_zone), {})
	var ids: Array = a.get("citizen_id", [])
	var pos: Array = a.get("positions", [])
	var area: float = float(a.get("area_size", 100.0))
	var half := area * 0.5
	var offset := _zone_center(_current_focus_zone)
	var best := -1
	var best_d := INF
	for i in range(ids.size()):
		if int(ids[i]) < 0:
			continue
		var p: Array = pos[i]
		var wp := offset + Vector3(float(p[0]) - half, 0.0, float(p[1]) - half)
		var d := wp.distance_squared_to(_player.position)
		if d < best_d:
			best_d = d
			best = int(ids[i])
	if best >= 0:
		var r: Dictionary = SimBridge.interact_with(best)
		if r.get("ok", false) and _outbreak_label != null:
			_outbreak_label.text = "Met Citizen %d (now in your roster)" % best


func _zone_center(zid: int) -> Vector3:
	for zz in _zones:
		if int(zz["id"]) == zid:
			var c: Array = zz["center_xy"]
			return Vector3(float(c[0]), 0.0, float(c[1]))
	return Vector3.ZERO
