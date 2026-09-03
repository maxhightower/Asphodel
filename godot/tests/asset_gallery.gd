extends Node3D

## Asset contact sheet: lay out every catalogued render kind (one row per kind,
## its variants across the row) under clean neutral lighting, then screenshot.
## Doubles as the Package-D no-magenta gate (every kind builds a real mesh).
##
##   ... res://tests/AssetGallery.tscn -- --group street --out /tmp/g.png

const PropMeshes = preload("res://scripts/prop_meshes.gd")

var _group := "street"
var _out := "/tmp/asset_gallery.png"

const GROUPS := {
	"street": ["mailbox", "garbage_bin", "recycling_bin", "fire_hydrant",
		"streetlight", "bench", "bollard", "utility_cabinet", "transformer_box",
		"dumpster", "traffic_sign", "traffic_signal", "bus_shelter",
		"parking_stop", "utility_pole", "ac_condenser", "guardrail",
		"road_barrier", "pallet", "wood_fence", "chainlink_fence"],
	"vehicles": ["sedan", "sports_car", "suv", "jeep", "pickup", "van",
		"box_truck", "semi_truck", "oil_tanker"],
	"veg": ["tree_oak", "tree_round", "tree_magnolia", "tree_conical",
		"tree_baldcypress", "tree_columnar", "tree_palm", "tree_willow",
		"tree_crape_myrtle", "bush_round", "bush_low", "hedge",
		"flowering_shrub", "tall_grass", "native_scrub"],
}


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	for i in range(args.size()):
		if args[i] == "--group" and i + 1 < args.size():
			_group = args[i + 1]
		elif args[i] == "--out" and i + 1 < args.size():
			_out = args[i + 1]
	await _run()


func _variant_count(kind: String) -> int:
	var f := FileAccess.open("res://catalog_v1.json", FileAccess.READ)
	if f == null:
		return 1
	var doc: Variant = JSON.parse_string(f.get_as_text())
	if typeof(doc) == TYPE_DICTIONARY and doc.has("render_variants"):
		return int((doc["render_variants"] as Dictionary).get(kind, 1))
	return 1


func _run() -> void:
	# neutral bright environment so assets read clearly (not the iso scene ambient)
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.62, 0.66, 0.70)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.75, 0.78, 0.82)
	env.ambient_light_energy = 0.9
	var we := WorldEnvironment.new()
	we.environment = env
	add_child(we)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-52, -46, 0)
	sun.light_energy = 1.1
	add_child(sun)

	var ground := MeshInstance3D.new()
	var pm := PlaneMesh.new()
	pm.size = Vector2(200, 200)
	ground.mesh = pm
	var gmat := StandardMaterial3D.new()
	gmat.albedo_color = Color(0.34, 0.42, 0.30)
	ground.material_override = gmat
	add_child(ground)

	print("gallery: building group ", _group)
	var kinds: Array = GROUPS.get(_group, GROUPS["street"])
	# Spacing is derived from each kind's real mesh AABB so nothing overlaps whether
	# it's a 4.5 m sedan or a 17 m tanker. Vehicles get one kind per row (variants
	# along +X, the length axis); other groups keep the squarish grid.
	var gap := 1.6
	var kpr := 1 if _group == "vehicles" else maxi(1, int(round(sqrt(float(kinds.size())))))
	# per-kind mesh length (X) and width (Z)
	var klen := PackedFloat32Array()
	var kwid := PackedFloat32Array()
	for kind_i in kinds:
		var ab := (PropMeshes.get_mesh(kind_i, 0) as Mesh).get_aabb()
		klen.append(maxf(ab.size.x, 1.0))
		kwid.append(maxf(ab.size.z, 1.0))
	var min_x := INF; var min_z := INF; var max_x := -INF; var max_z := -INF
	var z_cursor := 0.0
	var row_h := 0.0
	for i in range(kinds.size()):
		var kind: String = kinds[i]
		var nvar := _variant_count(kind)
		var kcol := i % kpr
		if kcol == 0 and i > 0:
			z_cursor += row_h + gap
			row_h = 0.0
		row_h = maxf(row_h, kwid[i])
		var x0 := float(kcol) * 12.0        # (unused for vehicles: kpr==1)
		var step := klen[i] + gap
		for c in range(nvar):
			var mi := MeshInstance3D.new()
			mi.mesh = PropMeshes.get_mesh(kind, c)
			var px := x0 + float(c) * step
			mi.position = Vector3(px, 0.0, z_cursor)
			add_child(mi)
			min_x = minf(min_x, px - klen[i] * 0.5); max_x = maxf(max_x, px + klen[i] * 0.5)
			min_z = minf(min_z, z_cursor); max_z = maxf(max_z, z_cursor)

	# frame the grid bounds with an angled iso ortho camera
	var w := max_x - min_x
	var d := max_z - min_z
	var center := Vector3((min_x + max_x) * 0.5, 1.0, (min_z + max_z) * 0.5)
	var cam := Camera3D.new()
	cam.projection = Camera3D.PROJECTION_ORTHOGONAL
	cam.size = 0.62 * (w + d) + 14.0
	cam.near = 0.1
	cam.far = 3000.0
	cam.position = center + Vector3(-0.55, 0.85, -0.55).normalized() * ((w + d) + 60.0)
	add_child(cam)
	cam.look_at(center, Vector3.UP)
	cam.make_current()

	for _i in range(8):
		await get_tree().process_frame
	await get_tree().create_timer(0.3).timeout
	var img := get_viewport().get_texture().get_image()
	img.save_png(_out)
	print("GALLERY saved: %s (%s, %d kinds)" % [_out, _group, kinds.size()])
	get_tree().quit(0)
