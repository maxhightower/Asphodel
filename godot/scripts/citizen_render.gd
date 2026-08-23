extends Node3D

## CitizenRender — draws the authoritative citizen simulation from a live snapshot
## (M6 / BW4), scalably. The renderer is a pure *consumer* of `World.snapshot()`:
## it never decides behaviour, only shows what the authoritative Python world
## reports. It may interpolate between snapshots for smoothness, but the truth is
## always the last snapshot.
##
## Visual LOD (so 15 000 *simulated* agents are never 15 000 expensive nodes):
##   V0/V1 crowd  -> ONE MultiMeshInstance3D, per-instance transform + colour by
##                   disease state; named roster members scaled up + tinted by a
##                   stable per-citizen visual seed (mirrors asphodel.npc.visual_seed)
##                   so they are recognisable on return.
##   V2 named     -> a Label3D nameplate per roster member, pooled and reused.
##
## Executed headless in tests/live_bench.gd; wired into street_world for play.

const AGENT_H := 1.0                 # capsule centre height
const NAMED_SCALE := 1.6
const CROWD_SCALE := 1.0

# Disease-state colours (indices match STATE_NAMES: S,E,Ia,Is,R,D).
const STATE_COLOR := [
	Color(0.70, 0.72, 0.78), Color(0.95, 0.85, 0.35), Color(0.95, 0.55, 0.20),
	Color(0.90, 0.25, 0.20), Color(0.35, 0.65, 0.85), Color(0.15, 0.15, 0.17),
]

var _mmi: MultiMeshInstance3D
var _mm: MultiMesh
var _labels: Array[Label3D] = []
var last_instance_count := 0


func _ready() -> void:
	var mesh := CapsuleMesh.new()
	mesh.radius = 0.25
	mesh.height = 1.2
	var mat := StandardMaterial3D.new()
	mat.vertex_color_use_as_albedo = true          # per-instance colours show
	mesh.material = mat
	_mm = MultiMesh.new()
	_mm.transform_format = MultiMesh.TRANSFORM_3D
	_mm.use_colors = true
	_mm.mesh = mesh
	_mmi = MultiMeshInstance3D.new()
	_mmi.multimesh = _mm
	add_child(_mmi)


## Draw one authoritative snapshot's agents for `focus_zone`. Returns the number
## of agents rendered.
func render_snapshot(snap: Dictionary, focus_zone: int,
		world_offset: Vector3 = Vector3.ZERO) -> int:
	var agents: Dictionary = snap.get("agents", {})
	var a: Dictionary = agents.get(str(focus_zone), {})
	var pos: Array = a.get("positions", [])
	var state: Array = a.get("state", [])
	var citizen_id: Array = a.get("citizen_id", [])
	var named: Array = a.get("named", [])
	var area: float = float(a.get("area_size", 100.0))
	var half := area * 0.5
	var n := pos.size()

	_mm.instance_count = n
	var label_i := 0
	for i in range(n):
		var p: Array = pos[i]
		var is_named: bool = named.size() > i and bool(named[i])
		var s: float = NAMED_SCALE if is_named else CROWD_SCALE
		# Torus-local position, centred on the zone's world location (offset), so
		# the promoted bubble renders around the player rather than at the origin.
		var origin := world_offset + Vector3(float(p[0]) - half, AGENT_H, float(p[1]) - half)
		var basis := Basis().scaled(Vector3(s, s, s))
		_mm.set_instance_transform(i, Transform3D(basis, origin))
		var cid: int = int(citizen_id[i]) if citizen_id.size() > i else -1
		_mm.set_instance_color(i, _color(int(state[i]), cid, is_named))
		if is_named and cid >= 0:
			var lbl := _label(label_i)
			label_i += 1
			lbl.text = "Citizen %d" % cid
			lbl.position = origin + Vector3(0, 1.0, 0)
			lbl.visible = true
	for j in range(label_i, _labels.size()):
		_labels[j].visible = false               # no stale nameplates after churn
	last_instance_count = n
	return n


func _color(state: int, cid: int, named: bool) -> Color:
	var base: Color = STATE_COLOR[clampi(state, 0, STATE_COLOR.size() - 1)]
	if named and cid >= 0:
		var hue := float(_visual_seed(cid) % 360) / 360.0
		base = base.lerp(Color.from_hsv(hue, 0.55, 0.95), 0.4)
	return base


func _label(i: int) -> Label3D:
	while _labels.size() <= i:
		var lbl := Label3D.new()
		lbl.billboard = BaseMaterial3D.BILLBOARD_ENABLED
		lbl.no_depth_test = true
		lbl.pixel_size = 0.004
		add_child(lbl)
		_labels.append(lbl)
	return _labels[i]


## Mirror of asphodel.npc.visual_seed (same 32-bit splitmix) so a named citizen's
## tint is identical across despawn/return and save/load.
func _visual_seed(cid: int) -> int:
	if cid < 0:
		return 0
	var x := (cid * 0x9E3779B1 + 0x7F4A7C15) & 0xFFFFFFFF
	x ^= (x >> 16)
	x = (x * 0x85EBCA6B) & 0xFFFFFFFF
	x ^= (x >> 13)
	return x & 0x7FFFFFFF
