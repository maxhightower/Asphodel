extends Node3D

## CitizenRender — draws the authoritative citizen simulation from a live snapshot
## (M6). The renderer is a pure *consumer* of `World.snapshot()`: it never decides
## behaviour, only shows what the authoritative Python world reports. It may
## interpolate positions between snapshots for visual smoothness, but the truth is
## always the last snapshot.
##
## Deliberately cheap placeholders: one capsule MeshInstance3D per live agent,
## coloured by disease state, tinted by activity, scaled up + nameplated for named
## roster members. A named member's body colour is keyed on a STABLE per-citizen
## visual seed (mirrors asphodel.npc.visual_seed) so the player recognises the same
## person on return. No character art, no animation — that is out of M6 scope.
##
## Not engine-executed in the authoring environment (no Godot runtime available);
## authored to the tested snapshot contract in asphodel/orchestrator.World.snapshot.

const AGENT_SCALE := 0.6
const NAMED_SCALE := 1.15
const Y := 1.0                      # capsule centre height above ground

# Disease-state base colours (indices match STATE_NAMES: S,E,Ia,Is,R,D).
const STATE_COLOR := [
	Color(0.70, 0.72, 0.78),        # S  susceptible — grey
	Color(0.95, 0.85, 0.35),        # E  exposed — amber
	Color(0.95, 0.55, 0.20),        # Ia asymptomatic infectious — orange
	Color(0.90, 0.25, 0.20),        # Is symptomatic — red
	Color(0.35, 0.65, 0.85),        # R  recovered — blue
	Color(0.15, 0.15, 0.17),        # D  dead — near-black
]

var _pool: Array[MeshInstance3D] = []      # reused capsule instances
var _labels: Dictionary = {}               # citizen_id -> Label3D nameplate
var _mesh := CapsuleMesh.new()


func _ready() -> void:
	_mesh.radius = 0.25
	_mesh.height = 1.2


## Render one authoritative snapshot. `snap` is World.snapshot(); `focus_zone` is
## the zone whose agents to draw (the promoted bubble the player stands in).
func render_snapshot(snap: Dictionary, focus_zone: int) -> void:
	var agents: Dictionary = snap.get("agents", {})
	var key := str(focus_zone)
	if not agents.has(key):
		_hide_from(0)
		return
	var a: Dictionary = agents[key]
	var pos: Array = a.get("positions", [])
	var state: Array = a.get("state", [])
	var activity: Array = a.get("activity", [])
	var citizen_id: Array = a.get("citizen_id", [])
	var named: Array = a.get("named", [])
	var area: float = float(a.get("area_size", 100.0))
	var half := area * 0.5

	var n := pos.size()
	for i in range(n):
		var inst := _instance(i)
		var p: Array = pos[i]
		# Centre the zone torus on the origin so the bubble sits around the player.
		inst.position = Vector3(float(p[0]) - half, Y, float(p[1]) - half)
		var is_named: bool = named.size() > i and bool(named[i])
		inst.scale = Vector3.ONE * (NAMED_SCALE if is_named else AGENT_SCALE)
		inst.material_override = _material(int(state[i]),
			int(activity[i]) if activity.size() > i else 0,
			int(citizen_id[i]) if citizen_id.size() > i else -1,
			is_named)
		_update_label(inst, int(citizen_id[i]) if citizen_id.size() > i else -1, is_named)
	_hide_from(n)


func _instance(i: int) -> MeshInstance3D:
	while _pool.size() <= i:
		var m := MeshInstance3D.new()
		m.mesh = _mesh
		add_child(m)
		_pool.append(m)
	_pool[i].visible = true
	return _pool[i]


func _hide_from(n: int) -> void:
	for i in range(n, _pool.size()):
		_pool[i].visible = false


func _material(state: int, activity: int, cid: int, named: bool) -> StandardMaterial3D:
	var mat := StandardMaterial3D.new()
	var base: Color = STATE_COLOR[clampi(state, 0, STATE_COLOR.size() - 1)]
	if named and cid >= 0:
		# Stable per-person tint so the same citizen looks the same on return.
		var seed := _visual_seed(cid)
		var hue := float(seed % 360) / 360.0
		base = base.lerp(Color.from_hsv(hue, 0.5, 0.9), 0.35)
		mat.emission_enabled = true
		mat.emission = base * 0.25
	mat.albedo_color = base
	return mat


func _update_label(inst: MeshInstance3D, cid: int, named: bool) -> void:
	# Nameplate only for named roster members, so the player can track continuity.
	if not named or cid < 0:
		if _labels.has(cid):
			_labels[cid].visible = false
		return
	var lbl: Label3D = _labels.get(cid)
	if lbl == null:
		lbl = Label3D.new()
		lbl.billboard = BaseMaterial3D.BILLBOARD_ENABLED
		lbl.no_depth_test = true
		lbl.pixel_size = 0.004
		add_child(lbl)
		_labels[cid] = lbl
	lbl.text = "Citizen %d" % cid
	lbl.visible = true
	lbl.position = inst.position + Vector3(0, 1.0, 0)


## Mirror of asphodel.npc.visual_seed (same splitmix), so named appearances match
## whatever the authoritative side reports.
func _visual_seed(cid: int) -> int:
	if cid < 0:
		return 0
	var x := (cid * 0x9E3779B1 + 0x7F4A7C15) & 0xFFFFFFFF
	x ^= (x >> 16)
	x = (x * 0x85EBCA6B) & 0xFFFFFFFF
	x ^= (x >> 13)
	return x & 0x7FFFFFFF
