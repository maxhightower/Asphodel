class_name RoadBuilder
extends RefCounted

## Turns the bundle's real OSM road polylines into drivable-width street
## geometry: flat asphalt ribbons per highway class (with rounded joints so
## bends don't gap), plus dashed center markings on major roads. Everything is
## batched into two meshes so even a few thousand segments stay cheap.

const WIDTHS := {
	"motorway": 22.0, "trunk": 18.0, "primary": 13.0, "secondary": 10.0,
	"tertiary": 8.0, "unclassified": 7.0, "residential": 6.5,
	"living_street": 6.0, "service": 4.0, "pedestrian": 3.5,
}
const DEFAULT_WIDTH := 7.0
const MAJOR := ["motorway", "trunk", "primary", "secondary", "tertiary"]

# Wider roads render a hair higher so overlapping classes never z-fight.
const _Y_MINOR := 0.03
const _Y_MAJOR := 0.05
const _Y_MARK := 0.08


static func build(parent: Node3D, roads: Dictionary, style: CityStyle) -> void:
	var polylines: Array = roads.get("polylines", [])
	if polylines.is_empty():
		return

	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var marks := SurfaceTool.new()
	marks.begin(Mesh.PRIMITIVE_TRIANGLES)
	var any_marks := false

	for pl in polylines:
		var pts: Array = pl.get("points", [])
		if pts.size() < 2:
			continue
		var cls: String = str(pl.get("class", ""))
		var width: float = WIDTHS.get(cls, DEFAULT_WIDTH)
		var major := MAJOR.has(cls)
		var y: float = _Y_MAJOR if major else _Y_MINOR
		var col: Color = style.asphalt if major else style.asphalt_minor
		_ribbon(st, pts, width, y, col)
		if major and width >= 8.0:
			any_marks = _dashes(marks, pts, y, style.marking) or any_marks

	parent.add_child(_commit(st, false))
	if any_marks:
		parent.add_child(_commit(marks, true))


static func _commit(st: SurfaceTool, unshaded: bool) -> MeshInstance3D:
	var mat := StandardMaterial3D.new()
	mat.vertex_color_use_as_albedo = true
	mat.vertex_color_is_srgb = true
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	mat.roughness = 1.0
	if unshaded:
		mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	st.set_material(mat)
	var mi := MeshInstance3D.new()
	mi.mesh = st.commit()
	return mi


static func _quad(st: SurfaceTool, a: Vector3, b: Vector3, c: Vector3, d: Vector3, col: Color) -> void:
	# a-b-c-d wound as two up-facing triangles (CCW seen from +Y in Godot)
	st.set_color(col)
	st.set_normal(Vector3.UP)
	for v in [a, c, b, a, d, c]:
		st.add_vertex(v)


static func _ribbon(st: SurfaceTool, pts: Array, width: float, y: float, col: Color) -> void:
	var half := width * 0.5
	var prev := Vector2(float(pts[0][0]), float(pts[0][1]))
	for i in range(1, pts.size()):
		var cur := Vector2(float(pts[i][0]), float(pts[i][1]))
		var d := cur - prev
		if d.length() < 0.05:
			continue
		var n := Vector2(-d.y, d.x).normalized() * half
		_quad(st,
			Vector3(prev.x + n.x, y, prev.y + n.y),
			Vector3(cur.x + n.x, y, cur.y + n.y),
			Vector3(cur.x - n.x, y, cur.y - n.y),
			Vector3(prev.x - n.x, y, prev.y - n.y),
			col)
		_joint(st, cur, half, y, col)
		prev = cur
	_joint(st, Vector2(float(pts[0][0]), float(pts[0][1])), half, y, col)


static func _joint(st: SurfaceTool, c: Vector2, r: float, y: float, col: Color) -> void:
	# octagon patch hides the seam where two segments meet at an angle
	var center := Vector3(c.x, y, c.y)
	st.set_color(col)
	st.set_normal(Vector3.UP)
	for k in range(8):
		var a0 := TAU * k / 8.0
		var a1 := TAU * (k + 1) / 8.0
		st.add_vertex(center)
		st.add_vertex(center + Vector3(cos(a0) * r, 0.0, sin(a0) * r))
		st.add_vertex(center + Vector3(cos(a1) * r, 0.0, sin(a1) * r))


static func _dashes(st: SurfaceTool, pts: Array, _road_y: float, col: Color) -> bool:
	var added := false
	var dash := 2.5
	var gap := 3.5
	var hw := 0.12
	var carry := 0.0
	for i in range(1, pts.size()):
		var a := Vector2(float(pts[i - 1][0]), float(pts[i - 1][1]))
		var b := Vector2(float(pts[i][0]), float(pts[i][1]))
		var seg := b - a
		var seg_len := seg.length()
		if seg_len < 0.05:
			continue
		var dir := seg / seg_len
		var n := Vector2(-dir.y, dir.x) * hw
		var t := carry
		while t + dash <= seg_len:
			var p0 := a + dir * t
			var p1 := a + dir * (t + dash)
			_quad(st,
				Vector3(p0.x + n.x, _Y_MARK, p0.y + n.y),
				Vector3(p1.x + n.x, _Y_MARK, p1.y + n.y),
				Vector3(p1.x - n.x, _Y_MARK, p1.y - n.y),
				Vector3(p0.x - n.x, _Y_MARK, p0.y - n.y),
				col)
			added = true
			t += dash + gap
		carry = t - seg_len
	return added


## Closest point on any road polyline to `target` (for spawning on a street).
static func closest_road_point(roads: Dictionary, target: Vector2) -> Vector2:
	var best := target
	var best_d := INF
	for pl in roads.get("polylines", []):
		for p in pl.get("points", []):
			var v := Vector2(float(p[0]), float(p[1]))
			var d := v.distance_squared_to(target)
			if d < best_d:
				best_d = d
				best = v
	return best
