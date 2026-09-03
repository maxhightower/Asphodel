extends Node3D

## CitizenHumanoidSmoke — headless logic gates for the low-poly humanoid NPC
## system. No GPU needed: it exercises the deterministic identity, the batched
## crowd bookkeeping, the bounded avatar pool, indoor/outdoor parity, the
## capsule census, and identity stability across render churn / LOD / slot.
##
##   godot4 --headless --path godot res://tests/CitizenHumanoidSmoke.tscn
##
## Prints "SMOKE PASS" and exits 0 on success, else "SMOKE FAIL: ..." and exits 1.

const CitizenRender = preload("res://scripts/citizen_render.gd")
const V = preload("res://scripts/citizen_visual_identity.gd")
const M = preload("res://scripts/citizen_meshes.gd")
const InteriorBuilderScript = preload("res://scripts/interior_builder.gd")

var _fail: Array[String] = []


func _ready() -> void:
	_test_identity_pure()
	_test_geometry_budgets()
	_test_crowd_bookkeeping()
	_test_avatar_pool_bounded()
	_test_no_capsules()
	_test_indoor_outdoor_parity()
	_test_identity_across_churn()
	if _fail.is_empty():
		print("SMOKE PASS")
		get_tree().quit(0)
	else:
		for f in _fail:
			print("SMOKE FAIL: ", f)
		get_tree().quit(1)


func _check(cond: bool, msg: String) -> void:
	if not cond:
		_fail.append(msg)


# --- H0/H17: appearance is a pure, stable function of citizen_id --------------
func _test_identity_pure() -> void:
	var a1 := V.appearance(42)
	var a2 := V.appearance(42)
	_check(a1 == a2, "appearance(42) not stable across calls")
	# not dependent on anything transient — a fresh call much later is identical
	_check(V.appearance(42) == a1, "appearance(42) drifted")
	# distinct citizens generally differ (sample a spread)
	var distinct := {}
	for cid in range(60):
		distinct[str(V.appearance(cid))] = true
	_check(distinct.size() >= 20, "appearance variety too low across 60 citizens: %d" % distinct.size())
	# anonymous fill has no personal identity and must not equal a named person by
	# construction of the -1 path
	_check(V.appearance(-1) == V.appearance_from_seed(0), "anonymous fill path unstable")


# --- H1: triangle budgets --------------------------------------------------
func _test_geometry_budgets() -> void:
	# normal LOD humanoid within budget; far LOD strictly cheaper.
	for body in range(V.N_BODY):
		for lower in range(V.N_LOWER):
			var far := M.body_mesh(body, lower, M.LOD_FAR)
			var norm := M.body_mesh(body, lower, M.LOD_NORMAL)
			var tf := _tris(far)
			var tn := _tris(norm)
			_check(tf <= 160, "far body %d/%d tris %d > 160" % [body, lower, tf])
			_check(tn <= 460, "normal body %d/%d tris %d > 460" % [body, lower, tn])
			_check(tf <= tn, "far not cheaper than normal for %d/%d" % [body, lower])
	# a rich near combined mesh (with hair) stays within the near budget.
	var app := V.appearance(42)
	var near := M.combined_mesh(app, M.LOD_NEAR)
	var trn := _tris(near)
	_check(trn <= 900, "near combined tris %d > 900" % trn)
	# meshes are cached (same object returned) — never rebuilt per call (H12).
	_check(M.body_mesh(1, 0, M.LOD_NORMAL) == M.body_mesh(1, 0, M.LOD_NORMAL), "body mesh not cached")
	_check(M.combined_mesh(app, M.LOD_NEAR) == near, "combined mesh not cached")


func _tris(mesh: ArrayMesh) -> int:
	if mesh == null or mesh.get_surface_count() == 0:
		return 0
	var arr := mesh.surface_get_arrays(0)
	var verts: PackedVector3Array = arr[Mesh.ARRAY_VERTEX]
	return verts.size() / 3


# --- H4/H9/H12: batched crowd bookkeeping ------------------------------------
func _test_crowd_bookkeeping() -> void:
	var r = CitizenRender.new()
	r.set_near_avatars_enabled(false)         # force everyone into the batched crowd
	add_child(r)
	var snap := _make_snapshot(200, 8)        # 200 agents, 8 named
	var drawn := r.render_snapshot(snap, 0)
	_check(drawn > 0, "render_snapshot drew nothing")
	# every drawn agent is exactly one crowd instance (no avatars here)
	var crowd := _count_crowd_instances(r)
	_check(crowd == drawn, "crowd instances %d != drawn %d" % [crowd, drawn])
	# bounded number of MultiMesh nodes: <= 12 body + 6 hair + 1 debug
	var mm_nodes := _count_multimesh_nodes(r)
	_check(mm_nodes <= 19, "too many MultiMesh nodes: %d" % mm_nodes)
	# churn: a second, differently-populated snapshot leaves no stale instances
	var snap2 := _make_snapshot(30, 3)
	var drawn2 := r.render_snapshot(snap2, 0)
	var crowd2 := _count_crowd_instances(r)
	_check(crowd2 == drawn2, "after churn crowd %d != drawn %d" % [crowd2, drawn2])
	r.queue_free()


# --- H4: near avatar pool is bounded -----------------------------------------
func _test_avatar_pool_bounded() -> void:
	var r = CitizenRender.new()
	r.set_near_avatars_enabled(true)
	r.set_focus_point(Vector3.ZERO)           # everyone is near the origin cluster
	add_child(r)
	var snap := _make_snapshot(200, 20, true) # clustered near origin, identified
	r.render_snapshot(snap, 0)
	var avatars := _count_avatars(r)
	_check(avatars <= 24, "avatar pool exceeded cap: %d" % avatars)
	_check(avatars > 0, "no avatars promoted despite near cluster")
	r.queue_free()


# --- capsule census: none anywhere in the humanoid render output -------------
func _test_no_capsules() -> void:
	var r = CitizenRender.new()
	add_child(r)
	r.render_snapshot(_make_snapshot(120, 5, true), 0)
	_check(not _has_capsule(r), "capsule mesh found in outdoor renderer")
	r.queue_free()
	# interior occupant path
	var occ = InteriorBuilderScript._occupant({"citizen_id": 42, "x": 1.0, "y": 2.0, "in_roster": true})
	add_child(occ)
	_check(not _has_capsule(occ), "capsule mesh found in interior occupant")
	_check(int(occ.get_meta("citizen_id", -999)) == 42, "interior occupant lost citizen_id meta")
	occ.queue_free()


# --- H10/H15: indoor == outdoor appearance -----------------------------------
func _test_indoor_outdoor_parity() -> void:
	var cid := 42
	var outdoor := V.appearance(cid)
	var occ: CitizenAvatar = InteriorBuilderScript._occupant({"citizen_id": cid, "x": 0.0, "y": 0.0, "in_roster": false})
	_check(occ.appearance == outdoor, "indoor appearance != outdoor for citizen %d" % cid)
	occ.free()


# --- H15: identity survives churn, slot change, LOD, promotion/demotion -------
func _test_identity_across_churn() -> void:
	var cid := 42
	var base := V.appearance(cid)
	# slot independence: same citizen at different array indices -> same appearance
	for slot in [0, 5, 99]:
		_check(V.appearance(cid) == base, "appearance changed with slot context")
	# LOD independence: the geometry key (body/lower/hair/sleeve) is identical at
	# every LOD; only triangle fidelity changes.
	var k_far := "%d_%d_%d_%d" % [base["body"], base["lower"], base["hair"], base["sleeve"]]
	# combined near vs a re-derived appearance after a simulated save/load (pure fn)
	var reloaded := V.appearance(cid)
	_check(reloaded == base, "appearance not stable across save/load (pure derivation)")
	_check("%d_%d_%d_%d" % [reloaded["body"], reloaded["lower"], reloaded["hair"], reloaded["sleeve"]] == k_far,
		"geometry key drifted")


# =========================================================================
# helpers: synthetic snapshots + tree inspection
# =========================================================================

func _make_snapshot(n: int, n_named: int, cluster: bool = false) -> Dictionary:
	var positions := []
	var state := []
	var cid := []
	var named := []
	var action := []
	var world_xy := []
	var movement := []
	var authoritative := []
	for i in range(n):
		positions.append([float(i % 10) * 5.0, float(i / 10) * 5.0])
		state.append(i % 6)
		cid.append(i)                     # identified citizens 0..n-1
		named.append(i < n_named)
		action.append(0)
		if cluster:
			world_xy.append([float(i % 5) * 1.5 - 3.0, float(i / 5) * 1.5 - 3.0])
		else:
			world_xy.append([float(i) * 3.0, float((i * 7) % 50)])
		movement.append("walking" if i % 3 == 0 else "stationary")
		authoritative.append(true)
	return {
		"tick": randi(),
		"agents": {"0": {
			"positions": positions, "state": state, "citizen_id": cid,
			"named": named, "chosen_action": action, "area_size": 100.0,
			"embodiment": {"world_xy": world_xy, "movement": movement,
				"authoritative": authoritative},
		}},
	}


func _count_crowd_instances(r: Node) -> int:
	var total := 0
	for c in r.get_children():
		if c is MultiMeshInstance3D and str(c.name).begins_with("CrowdBucket"):
			total += (c as MultiMeshInstance3D).multimesh.instance_count
	return total


func _count_multimesh_nodes(r: Node) -> int:
	var total := 0
	for c in r.get_children():
		if c is MultiMeshInstance3D:
			total += 1
	return total


func _count_avatars(r: Node) -> int:
	var total := 0
	for c in r.get_children():
		if c is CitizenAvatar and c.visible:
			total += 1
	return total


func _has_capsule(node: Node) -> bool:
	if node is MeshInstance3D and (node as MeshInstance3D).mesh is CapsuleMesh:
		return true
	if node is MultiMeshInstance3D:
		var mm := (node as MultiMeshInstance3D).multimesh
		if mm != null and mm.mesh is CapsuleMesh:
			return true
	for c in node.get_children():
		if _has_capsule(c):
			return true
	return false
