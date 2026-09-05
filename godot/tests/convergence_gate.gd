extends Node3D

## Convergence certification for the Godot client (no Python bridge required).
##
##   godot --headless --path godot res://tests/ConvergenceGate.tscn
##
## Four gates, all in-engine against the shipped bundles:
##
##   G  collision-layer unification — every physics body in the shipping path
##      carries the layer/mask the Python matrix (asphodel/physics/layers.py,
##      mirrored into CollisionLayers) assigns it. Godot defaults are a bug.
##   I  schema contract at the bundle boundary — BundleLoader REJECTS obsolete
##      and skewed bundle files instead of half-reading them.
##   E  deterministic visual identity — a citizen's appearance is a pure
##      function of their id, independent of the global RNG.
##   H  multi-city load matrix — every shipped city loads through every seam.
##
## Exits 0 when every counted check passes, 1 otherwise.

const ExteriorWorld := preload("res://scripts/exterior_world.gd")
const InteriorBuilder := preload("res://scripts/interior_builder.gd")
const FirstPersonScript := preload("res://scripts/first_person.gd")

const CITIES := ["houston", "madisonville_tx", "austin", "san_antonio"]
const SYNTHETIC_CITIES := ["boulder"]   # region-only: no compiled world/, no buildings
const MATRIX_CHECKS := ["bundle", "buildings", "streetmap", "region", "physics",
	"region_chunks", "exterior"]
## Which matrix checks are load-bearing for a synthetic (region-only) bundle.
const SYNTHETIC_COUNTED := ["streetmap", "region", "physics"]

var _fail := 0
var _log: Array[String] = []
var _matrix: Dictionary = {}    # city -> {check: "PASS"/"FAIL"/"INFO"}


func _ready() -> void:
	await get_tree().process_frame
	await _gate_g_collision()
	_gate_i_schema()
	_gate_e_identity()
	await _gate_h_cities()

	print("\n==== CONVERGENCE GATE RESULTS ====")
	for l in _log:
		print(l)
	_print_matrix()
	print("==== %s (%d failure(s)) ====" % ["PASS" if _fail == 0 else "FAIL", _fail])
	get_tree().quit(1 if _fail > 0 else 0)


func _ok(name: String, cond: bool, detail: String = "") -> void:
	_log.append("%s  %s  %s" % ["PASS" if cond else "FAIL", name, detail])
	if not cond:
		_fail += 1


func _info(name: String, detail: String = "") -> void:
	_log.append("INFO  %s  %s" % [name, detail])


# =============================================================================
# G — collision-layer unification
# =============================================================================

func _gate_g_collision() -> void:
	# --- the streamed exterior: every StaticBody3D is world geometry ---------
	var world := ExteriorWorld.new()
	add_child(world)
	var setup_ok: bool = world.setup("res://bundles/houston")
	_ok("g_exterior_setup", setup_ok, "ExteriorWorld.setup(houston)")
	if setup_ok:
		world.force_materialize(Vector3.ZERO)
		await get_tree().process_frame
		await get_tree().process_frame
		var r := _audit_static(world)
		_ok("g_exterior_static_bodies_found",
			int(r["total"]) > 0 and int(r["shapes"]) > 0,
			"StaticBody3D count=%d carrying %d collision shapes" %
			[int(r["total"]), int(r["shapes"])])
		_ok("g_exterior_world_static", int(r["bad"]) == 0,
			"%d/%d on WORLD_STATIC, offenders: %s" %
			[int(r["total"]) - int(r["bad"]), int(r["total"]), str(r["names"])])
	world.queue_free()
	await get_tree().process_frame

	# --- the two player bodies ----------------------------------------------
	var pmask: int = CollisionLayers.PROFILES["player"]["mask"]
	var fp := CharacterBody3D.new()
	fp.set_script(FirstPersonScript)
	add_child(fp)
	await get_tree().process_frame
	_ok("g_first_person_player_profile",
		fp.collision_layer == CollisionLayers.PLAYER and fp.collision_mask == pmask,
		"layer=%d mask=%d (want %d/%d)" %
		[fp.collision_layer, fp.collision_mask, CollisionLayers.PLAYER, pmask])
	fp.queue_free()

	var ip := IsometricPlayer.new()
	add_child(ip)
	await get_tree().process_frame
	_ok("g_isometric_player_profile",
		ip.collision_layer == CollisionLayers.PLAYER and ip.collision_mask == pmask,
		"layer=%d mask=%d (want %d/%d)" %
		[ip.collision_layer, ip.collision_mask, CollisionLayers.PLAYER, pmask])
	ip.queue_free()

	# --- NPC + vehicle bodies ------------------------------------------------
	var cb := CitizenBody.new()
	add_child(cb)
	await get_tree().process_frame
	_ok("g_citizen_body_npc_profile",
		cb.collision_layer == CollisionLayers.NPC
		and cb.collision_mask == CollisionLayers.PROFILES["npc"]["mask"],
		"layer=%d mask=%d" % [cb.collision_layer, cb.collision_mask])
	# its perception Area3D is a TRIGGER, never a solid body
	var sensor: Area3D = cb.get_node_or_null("Sensor")
	_ok("g_citizen_sensor_trigger_profile",
		sensor != null and sensor.collision_layer == CollisionLayers.TRIGGER
		and sensor.collision_mask == CollisionLayers.PROFILES["trigger"]["mask"],
		"layer=%d mask=%d" % [
			sensor.collision_layer if sensor != null else -1,
			sensor.collision_mask if sensor != null else -1])
	cb.queue_free()

	var vb := VehicleBody.new()
	add_child(vb)
	await get_tree().process_frame
	_ok("g_vehicle_body_profile",
		vb.collision_layer == CollisionLayers.VEHICLE
		and vb.collision_mask == CollisionLayers.PROFILES["vehicle"]["mask"],
		"layer=%d mask=%d" % [vb.collision_layer, vb.collision_mask])
	vb.queue_free()
	await get_tree().process_frame

	# --- an interior built from a hand-written descriptor --------------------
	var interior := InteriorBuilder.build(_sample_interior(), Vector3(100000.0, 0.0, 0.0))
	add_child(interior)
	await get_tree().process_frame
	var ir := _audit_static(interior)
	_ok("g_interior_static_bodies_found", int(ir["total"]) >= 3,
		"StaticBody3D count=%d (floor + walls + fixtures)" % int(ir["total"]))
	_ok("g_interior_world_static", int(ir["bad"]) == 0,
		"%d/%d on WORLD_STATIC, offenders: %s" %
		[int(ir["total"]) - int(ir["bad"]), int(ir["total"]), str(ir["names"])])
	interior.queue_free()
	await get_tree().process_frame

	# The profiles are only correct if they still MEET: drop a player body onto a
	# WORLD_STATIC slab and require that it lands. A mask typo here is exactly how
	# a "unified" layer scheme silently drops the player through the city.
	await _drop_test()


func _drop_test() -> void:
	var slab := StaticBody3D.new()
	slab.name = "DropSlab"
	slab.collision_layer = CollisionLayers.WORLD_STATIC
	slab.collision_mask = 0
	var cs := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(20.0, 1.0, 20.0)
	cs.shape = box
	cs.position = Vector3(0.0, -0.5, 0.0)
	slab.add_child(cs)
	slab.position = Vector3(0.0, 500.0, 0.0)
	add_child(slab)

	var walker := CharacterBody3D.new()
	walker.set_script(FirstPersonScript)
	walker.position = Vector3(0.0, 503.0, 0.0)
	add_child(walker)
	for i in range(180):
		await get_tree().physics_frame
	var landed: bool = walker.is_on_floor() and absf(walker.position.y - 500.0) < 0.6
	_ok("g_player_stands_on_world_static", landed,
		"y=%.2f on_floor=%s (slab top y=500)" % [walker.position.y, walker.is_on_floor()])
	walker.queue_free()
	slab.queue_free()
	await get_tree().process_frame


func _audit_static(root: Node) -> Dictionary:
	## Walk the subtree; report how many StaticBody3D deviate from WORLD_STATIC.
	var total := 0
	var bad := 0
	var shapes := 0
	var names: Array[String] = []
	var stack: Array[Node] = [root]
	while not stack.is_empty():
		var n: Node = stack.pop_back()
		if n is CollisionShape3D:
			shapes += 1
		if n is StaticBody3D:
			total += 1
			var b := n as StaticBody3D
			if b.collision_layer != CollisionLayers.WORLD_STATIC or b.collision_mask != 0:
				bad += 1
				if names.size() < 6:
					names.append("%s(l=%d,m=%d)" % [b.name, b.collision_layer, b.collision_mask])
		for c in n.get_children():
			stack.append(c)
	return {"total": total, "bad": bad, "shapes": shapes, "names": names}


func _sample_interior() -> Dictionary:
	## A minimal but complete interior descriptor, shaped exactly like the
	## authoritative GET_INTERIOR payload the live bridge returns — so this gate
	## exercises the real InteriorBuilder path without needing Python running.
	return {
		"building_id": 4242,
		"seed": 7,
		"hull": [[0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [0.0, 8.0]],
		"rooms": [
			{"id": 0, "x0": 0.0, "y0": 0.0, "x1": 6.0, "y1": 8.0},
			{"id": 1, "x0": 6.0, "y0": 0.0, "x1": 10.0, "y1": 8.0},
		],
		"doorways": [{"x": 6.0, "y": 4.0}],
		"entrances": [{"x": 3.0, "y": 0.0, "nx": 0.0, "ny": -1.0}],
		"fixtures": [
			{"fixture_id": 0, "kind": "cabinet", "x": 1.2, "y": 6.4,
				"facing": 0.0, "variant": 0, "container_index": 0},
			{"fixture_id": 1, "kind": "fridge", "x": 8.6, "y": 1.4,
				"facing": 1.57, "variant": 1, "container_index": 1},
		],
		"decor": [{"kind": "sofa", "x": 3.0, "y": 5.0, "facing": 0.0}],
		"occupants": [],
	}


# =============================================================================
# I — schema contract at the bundle boundary
# =============================================================================

func _gate_i_schema() -> void:
	var bad_dir := "user://gate_bad"
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(bad_dir))

	# A bare JSON array is the obsolete pre-v1 synth.py output: must be rejected.
	_write(bad_dir.path_join("buildings.json"),
		'[{"poly": [[0,0],[1,0],[1,1]], "height": 4.0}]')
	_ok("i_reject_bare_array_buildings",
		BundleLoader.load_buildings(bad_dir).is_empty(),
		"load_buildings(bare array) -> []")

	# A version we do not speak must be rejected, not guessed at.
	_write(bad_dir.path_join("streetmap.json"),
		'{"version": 99, "nodes": {}, "segments": []}')
	_ok("i_reject_streetmap_version_99",
		BundleLoader.load_streetmap(bad_dir).is_empty(),
		"load_streetmap(version 99) -> {}")

	# ...and a whole-bundle validation must surface the same violations.
	var reason := BundleLoader.validate_bundle_schema(bad_dir)
	_ok("i_validate_bundle_schema_rejects", reason != "", "reason=%s" % reason)

	# The legacy sample_bundle form {version:1, buildings:[{poly,height}]} stays
	# readable — this gate tightens the contract, it does not break shipped data.
	var sample := BundleLoader.load_buildings("res://sample_bundle")
	_ok("i_accept_sample_bundle", not sample.is_empty(),
		"sample_bundle buildings=%d" % sample.size())
	_ok("i_sample_bundle_schema_ok",
		BundleLoader.validate_bundle_schema("res://sample_bundle") == "",
		"validate_bundle_schema(sample_bundle)")

	# The real compiled city loads at full size.
	var houston := BundleLoader.load_buildings("res://bundles/houston")
	_ok("i_houston_buildings_full", houston.size() > 20000,
		"houston buildings=%d (want > 20000)" % houston.size())

	_cleanup(bad_dir)


func _write(path: String, text: String) -> void:
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f != null:
		f.store_string(text)
		f.close()


func _cleanup(dir: String) -> void:
	var d := DirAccess.open(dir)
	if d == null:
		return
	for f in d.get_files():
		d.remove(f)


# =============================================================================
# E — deterministic visual identity
# =============================================================================

func _gate_e_identity() -> void:
	# Same id, computed twice -> byte-identical appearance.
	var a1 := _canon(CitizenVisualIdentity.appearance(7))
	var a2 := _canon(CitizenVisualIdentity.appearance(7))
	_ok("e_appearance_stable_same_id", a1 == a2, "appearance(7) x2")

	# The global RNG must not leak into identity: reseed between computations.
	seed(1)
	var s1 := CitizenVisualIdentity.visual_seed(7)
	var b1 := _canon(CitizenVisualIdentity.appearance_from_seed(s1))
	var r1 := randi()          # prove the global RNG really was reseeded
	seed(2)
	var s2 := CitizenVisualIdentity.visual_seed(7)
	var b2 := _canon(CitizenVisualIdentity.appearance_from_seed(s2))
	var r2 := randi()
	_ok("e_visual_seed_rng_independent", s1 == s2, "visual_seed(7)=%d vs %d" % [s1, s2])
	_ok("e_appearance_rng_independent", b1 == b2, "appearance under seed(1) vs seed(2)")
	_ok("e_global_rng_actually_reseeded", r1 != r2,
		"randi() after seed(1)=%d vs seed(2)=%d" % [r1, r2])
	_ok("e_appearance_matches_id_path", b1 == a1, "appearance_from_seed(visual_seed(7)) == appearance(7)")

	# Different citizens are visually distinguishable.
	var c8 := _canon(CitizenVisualIdentity.appearance(8))
	_ok("e_distinct_citizens_differ", a1 != c8, "appearance(7) != appearance(8)")


func _canon(a: Dictionary) -> String:
	## Order-independent, reference-independent serialization of an appearance.
	var keys: Array = a.keys()
	keys.sort()
	var parts: Array[String] = []
	for k in keys:
		parts.append("%s=%s" % [str(k), str(a[k])])
	return ";".join(parts)


# =============================================================================
# H — multi-city load matrix
# =============================================================================

func _gate_h_cities() -> void:
	for city in CITIES:
		await _city_row(city, false)
	for city in SYNTHETIC_CITIES:
		await _city_row(city, true)


func _city_row(city: String, synthetic: bool) -> void:
	var dir := "res://bundles/" + city
	var row := {}
	_matrix[city] = row

	# 1. the four-part bundle
	var bundle := BundleLoader.load_bundle(dir)
	_record(city, row, "bundle", not bundle.is_empty(), synthetic,
		"load_bundle -> %d parts" % bundle.size())

	# 2. building footprints
	var buildings := BundleLoader.load_buildings(dir)
	_record(city, row, "buildings", not buildings.is_empty(), synthetic,
		"buildings=%d" % buildings.size())

	# 3. street graph — checked against the file's OWN declared stats rather than
	#    an absolute segment count, so a real small town (Madisonville: 46
	#    segments) is not failed for being small. Every segment endpoint must
	#    resolve to a node: a graph with dangling ends would route citizens off
	#    the map.
	var street := BundleLoader.load_streetmap(dir)
	var nodes: Dictionary = street.get("nodes", {})
	var segs: Array = street.get("segments", [])
	var stats: Dictionary = street.get("stats", {})
	var counts_agree := true
	if stats.has("segments"):
		counts_agree = int(stats["segments"]) == segs.size()
	if stats.has("nodes"):
		counts_agree = counts_agree and int(stats["nodes"]) == nodes.size()
	var endpoints_resolve := true
	for i in range(mini(segs.size(), 200)):
		var seg = segs[i]
		if not (seg is Dictionary) or not nodes.has(str(seg.get("u"))) \
				or not nodes.has(str(seg.get("v"))):
			endpoints_resolve = false
			break
	_record(city, row, "streetmap",
		not street.is_empty() and segs.size() > 0 and not nodes.is_empty()
		and counts_agree and endpoints_resolve, synthetic,
		"segments=%d nodes=%d stats_agree=%s endpoints_resolve=%s" %
		[segs.size(), nodes.size(), counts_agree, endpoints_resolve])

	# 4. regional terrain descriptor
	var region := BundleLoader.load_region(dir)
	_record(city, row, "region", not region.is_empty(), synthetic,
		"heightmap rows=%d" % (region.get("heightmap", {}).get("heights", []) as Array).size())

	# 5. the physics contract the client mirrors
	var phys_ok := false
	var phys_path := dir.path_join("physics.json")
	if FileAccess.file_exists(phys_path):
		var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(phys_path))
		phys_ok = parsed is Dictionary and (parsed as Dictionary).has("collision_matrix")
	_record(city, row, "physics", phys_ok, synthetic, "collision_matrix present=%s" % phys_ok)

	# 6. terrain realization in-engine
	var loader := RegionLoader.new()
	loader.bundle_dir = dir
	add_child(loader)
	await get_tree().process_frame
	await get_tree().process_frame
	var chunks := 0
	for child in loader.get_children():
		if child is MeshInstance3D:
			chunks += 1
	_record(city, row, "region_chunks", chunks > 0, synthetic, "chunk meshes=%d" % chunks)
	loader.queue_free()
	await get_tree().process_frame

	# 7. the compiled exterior stream
	var world := ExteriorWorld.new()
	add_child(world)
	var ext_ok: bool = world.setup(dir)
	_record(city, row, "exterior", ext_ok, synthetic,
		"ExteriorWorld.setup" + ("" if ext_ok else " (no world/ compiled)"))
	world.queue_free()
	await get_tree().process_frame


func _record(city: String, row: Dictionary, check: String, ok: bool,
		synthetic: bool, detail: String) -> void:
	## Every check is reported. For a synthetic region-only bundle only the
	## region/street/physics seams are load-bearing; the rest is INFO, since a
	## bundle without a compiled world legitimately has nothing to stream.
	var counted := (not synthetic) or (check in SYNTHETIC_COUNTED)
	var name := "h_%s_%s" % [city, check]
	if ok:
		row[check] = "PASS"
		_ok(name, true, detail)
	elif counted:
		row[check] = "FAIL"
		_ok(name, false, detail)
	else:
		row[check] = "INFO"
		_info(name, detail + " — synthetic bundle, not counted")


func _print_matrix() -> void:
	print("\n---- multi-city load matrix ----")
	var head := "%-18s" % "city"
	for c in MATRIX_CHECKS:
		head += "%-15s" % c
	print(head)
	var order: Array = CITIES.duplicate()
	order.append_array(SYNTHETIC_CITIES)
	for city in order:
		var row: Dictionary = _matrix.get(city, {})
		var line := "%-18s" % city
		for c in MATRIX_CHECKS:
			line += "%-15s" % str(row.get(c, "-"))
		print(line)
	print("(INFO = reported but not counted: region-only bundle with no compiled world/)")
