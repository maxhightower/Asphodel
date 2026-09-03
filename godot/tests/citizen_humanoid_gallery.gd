extends Node3D

## CitizenHumanoidGallery — deterministic visual gate (H13). Renders >= 30 stable
## citizens through the shared identity + mesh + shader system and captures them
## from the ACTUAL game camera (isometric normal zoom + a closer interaction zoom),
## plus a neutral-grey SILHOUETTE sheet proving the geometry reads as people
## without colour.
##
##   xvfb-run -a env LIBGL_ALWAYS_SOFTWARE=1 godot4 --path godot \
##     --rendering-method gl_compatibility --rendering-driver opengl3 \
##     res://tests/CitizenHumanoidGallery.tscn -- --out /tmp/gallery
##
## Writes <out>_iso.png, <out>_close.png, <out>_silhouette.png.

const V = preload("res://scripts/citizen_visual_identity.gd")
const M = preload("res://scripts/citizen_meshes.gd")

const COLS := 8
const N := 32

var _out := "/tmp/asph_gallery"
var _avatars: Array = []
var _material: ShaderMaterial
var _cam: Camera3D
var _t := 0.0


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--out" and i + 1 < args.size():
			_out = args[i + 1]

	# environment: soft ambient so the faceted low-poly reads without harsh shadow.
	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.62, 0.66, 0.70)
	e.ambient_light_color = Color(0.8, 0.8, 0.82)
	e.ambient_light_energy = 0.9
	env.environment = e
	add_child(env)
	var sun := DirectionalLight3D.new()
	sun.rotation = Vector3(deg_to_rad(-55.0), deg_to_rad(-40.0), 0.0)
	sun.light_energy = 1.1
	add_child(sun)
	# ground
	var ground := MeshInstance3D.new()
	var pm := PlaneMesh.new()
	pm.size = Vector2(80, 80)
	var gmat := StandardMaterial3D.new()
	gmat.albedo_color = Color(0.42, 0.45, 0.40)
	pm.material = gmat
	ground.mesh = pm
	add_child(ground)

	_material = V.build_material()
	_build_grid()

	_cam = Camera3D.new()
	_cam.projection = Camera3D.PROJECTION_ORTHOGONAL
	add_child(_cam)

	await _capture_all()
	get_tree().quit(0)


func _build_grid() -> void:
	# A deterministic spread of citizens (ids chosen to exercise every body, hair,
	# lower-clothing and colour axis). Laid out in a grid, all facing the camera.
	for i in range(N):
		var cid := i + 1
		var app := V.appearance(cid)
		var av := CitizenAvatar.new()
		var gait := 0.5 if (i % 3 == 0) else 0.0        # some mid-walk, some idle
		av.configure(cid, app, _material, gait, M.LOD_NEAR)
		var col := i % COLS
		var row := i / COLS
		av.position = Vector3(float(col) * 1.4 - float(COLS - 1) * 0.7, 0.0, float(row) * 1.8)
		av.set_heading(PI)                              # face -Z toward the camera
		add_child(av)
		_avatars.append(av)


func _frame_camera(center: Vector3, ortho: float) -> void:
	# The production isometric framing: 45° yaw, ~55° pitch, orthographic.
	var yaw := deg_to_rad(45.0)
	var pitch := deg_to_rad(55.0)
	var dist := 40.0
	var dir := Vector3(sin(yaw) * cos(pitch), sin(pitch), cos(yaw) * cos(pitch))
	_cam.position = center + dir * dist
	_cam.look_at(center, Vector3.UP)
	_cam.size = ortho


func _capture_all() -> void:
	var center := Vector3(0.0, 0.9, float(N / COLS) * 0.9)
	# advance a few frames so the walk animation is mid-cycle and shaders warm up
	for f in range(6):
		_t += 0.12
		_material.set_shader_parameter("anim_time", _t)
		await get_tree().process_frame
	# 1) isometric normal zoom — the whole crowd
	_frame_camera(center, float(N / COLS) * 3.4 + 8.0)
	await _grab(_out + "_iso.png")
	# 2) closer interaction zoom — a few figures, arms/hair/clothing legible
	_frame_camera(Vector3(-2.0, 0.95, 1.0), 6.0)
	await _grab(_out + "_close.png")
	# 3) silhouette gate: same geometry, one neutral grey, from normal zoom
	var grey := StandardMaterial3D.new()
	grey.albedo_color = Color(0.55, 0.55, 0.57)
	for av in _avatars:
		av.set_material_override(grey)
	_frame_camera(center, float(N / COLS) * 3.4 + 8.0)
	await _grab(_out + "_silhouette.png")


func _grab(path: String) -> void:
	for f in range(3):
		await get_tree().process_frame
	await RenderingServer.frame_post_draw
	var img := get_viewport().get_texture().get_image()
	img.save_png(path)
	print("GALLERY wrote ", path, " (", img.get_width(), "x", img.get_height(), ")")
