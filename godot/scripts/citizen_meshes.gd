extends RefCounted
class_name CitizenMeshes

## CitizenMeshes — procedural low-poly humanoid geometry (H1).
##
## Every visible NPC — batched crowd, near avatar, interior occupant — is one of a
## BOUNDED, ENUMERABLE set of combined `ArrayMesh`es built here and CACHED. We
## never build a mesh per citizen at runtime and never build one per frame (H12).
##
## A body is ONE combined mesh (not dozens of child MeshInstance3D nodes): head,
## neck, torso, pelvis, arms (upper/lower/hands), legs (thigh/shin/feet), merged
## into a single surface. Hair is a separate tiny mesh (so the crowd can batch a
## small set of hair silhouettes independently) at the head anchor.
##
## Per-vertex data drives the shared shader (H2):
##   * UV2.x = material REGION id (skin / hair / top / bottom / shoes / accent)
##   * UV2.y = signed limb "lever" for the GPU walk swing (0 on torso/head; grows
##             toward hands/feet; sign opposes across the body so arms and legs
##             swing in natural opposition — H5). Feet/hands inherit their limb.
##
## Geometry variety in the batched crowd is the key (body, lower-clothing)
## silhouette; colour + sleeve come per-instance from the shader. The full,
## independent appearance (skin/hair/clothing palettes, sleeve) is expressed by
## colour so a citizen looks identical across LOD transitions — only triangle
## fidelity changes (H4).

const V = preload("res://scripts/citizen_visual_identity.gd")

# Material region ids (must match citizen_material.gdshader).
const R_SKIN := 0
const R_HAIR := 1
const R_TOP := 2
const R_BOTTOM := 3
const R_SHOES := 4
const R_ACCENT := 5
const R_SLEEVE := 6   # forearm: skin (short sleeve) or top (long sleeve), per-instance

# LOD tiers (triangle budgets, H1): 0 far/simple, 1 normal, 2 near/rich.
const LOD_FAR := 0
const LOD_NORMAL := 1
const LOD_NEAR := 2

# Reference head radius for the body-INDEPENDENT canonical hair meshes. A hair
# MultiMesh is shared across all bodies; each instance transform lifts it to that
# body's head centre and scales it by (head_radius / REF_HEAD_R) to fit. This
# keeps the crowd to 12 body + 6 hair MultiMeshes instead of one per (body,hair).
const REF_HEAD_R := 0.14

# --- caches ------------------------------------------------------------------
static var _body_cache: Dictionary = {}   # key "body_lower_lod" -> ArrayMesh
static var _hair_cache: Dictionary = {}   # key "hair_lod" -> ArrayMesh (canonical)
static var _combined_cache: Dictionary = {}  # key "body_lower_hair_sleeve_lod" -> ArrayMesh


# --- public: cached body mesh for a (body, lower, lod) bucket -----------------
static func body_mesh(body: int, lower: int, lod: int) -> ArrayMesh:
	var key := "%d_%d_%d" % [body, lower, lod]
	var m: ArrayMesh = _body_cache.get(key, null)
	if m == null:
		m = _build_body(body, lower, lod)
		_body_cache[key] = m
	return m


## Cached CANONICAL hair mesh for a (hair, lod) bucket, centred on the origin with
## a REF_HEAD_R head. The crowd renderer lifts + scales each instance onto its
## body's head, so this mesh is shared across all bodies (see head_center_y /
## head_radius). Returns null for bald.
static func hair_mesh(hair: int, lod: int) -> ArrayMesh:
	if hair == V.HAIR_BALD:
		return null
	var key := "%d_%d" % [hair, lod]
	var m: ArrayMesh = _hair_cache.get(key, null)
	if m == null:
		var arrays := _new_arrays()
		_emit_hair(arrays, 0.0, REF_HEAD_R, hair, lod)
		m = _finish(arrays)
		_hair_cache[key] = m
	return m


## World-space head-centre height for a body (hair instance lift).
static func head_center_y(body: int) -> float:
	var g := _geom(body)
	return (g["head_bot"] + g["head_top"]) * 0.5

## Head radius for a body (hair instance scale = head_radius / REF_HEAD_R).
static func head_radius(body: int) -> float:
	return float(_geom(body)["head_r"])


## Full combined mesh (body + hair merged) for near avatars / gallery close-ups.
## Cached on the (body, lower, hair, sleeve, lod) geometry key — a BOUNDED set —
## so a moving near avatar never rebuilds a mesh (H12).
static func combined_mesh(a: Dictionary, lod: int = LOD_NEAR) -> ArrayMesh:
	var body := int(a.get("body", 0))
	var lower := int(a.get("lower", 0))
	var hair := int(a.get("hair", 0))
	var sleeve := int(a.get("sleeve", 0))
	var key := "%d_%d_%d_%d_%d" % [body, lower, hair, sleeve, lod]
	var m: ArrayMesh = _combined_cache.get(key, null)
	if m != null:
		return m
	var arrays := _new_arrays()
	_emit_body(arrays, body, lower, lod, sleeve)
	if hair != V.HAIR_BALD:
		_emit_hair(arrays, head_center_y(body), head_radius(body), hair, lod)
	m = _finish(arrays)
	_combined_cache[key] = m
	return m


static func head_height(body: int) -> float:
	## Y of the top of the head for a body — used to anchor nameplates/markers.
	var g := _geom(body)
	return g["head_top"]


# =========================================================================
# geometry assembly
# =========================================================================

static func _new_arrays() -> Array:
	return [PackedVector3Array(), PackedVector3Array(), PackedVector2Array()]

static func _finish(arrays: Array) -> ArrayMesh:
	var mesh := ArrayMesh.new()
	var surf := []
	surf.resize(Mesh.ARRAY_MAX)
	surf[Mesh.ARRAY_VERTEX] = arrays[0]
	surf[Mesh.ARRAY_NORMAL] = arrays[1]
	surf[Mesh.ARRAY_TEX_UV2] = arrays[2]
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, surf)
	return mesh


static func _build_body(body: int, lower: int, lod: int) -> ArrayMesh:
	var arrays := _new_arrays()
	# Default sleeve for the batched-crowd cached mesh is "long" (forearm = R_SLEEVE
	# region), and the shader decides skin vs top per instance. For a combined near
	# mesh the caller passes the citizen's real sleeve to bake skin directly.
	_emit_body(arrays, body, lower, lod, -1)
	return _finish(arrays)



## Vertical layout (metres) for a body variant. Returns key anchor heights.
static func _geom(body: int) -> Dictionary:
	var p := V.body_params(body)
	var leg: float = float(p["leg"])
	var torso: float = float(p["torso"])
	var head_r: float = float(p["head"])
	var foot_h := 0.06
	var shin := leg * 0.5
	var thigh := leg - shin
	var pelvis_h := 0.16
	var neck_h := 0.06
	var hip_y := leg                       # top of legs / bottom of pelvis
	var pelvis_top := hip_y + pelvis_h
	var shoulder_y := pelvis_top + torso   # top of torso
	var neck_top := shoulder_y + neck_h
	var head_bot := neck_top
	var head_top := head_bot + head_r * 2.0
	return {
		"shoulder_w": float(p["shoulder"]), "hip_w": float(p["hip"]),
		"depth": float(p["depth"]), "head_r": head_r,
		"foot_h": foot_h, "shin": shin, "thigh": thigh,
		"hip_y": hip_y, "pelvis_top": pelvis_top,
		"shoulder_y": shoulder_y, "neck_top": neck_top,
		"head_bot": head_bot, "head_top": head_top,
	}


static func _emit_body(arrays: Array, body: int, lower: int, lod: int, sleeve: int) -> void:
	var g := _geom(body)
	var sw: float = g["shoulder_w"]
	var hw: float = g["hip_w"]
	var dep: float = g["depth"]
	var hr: float = g["head_r"]
	var shoulder_y: float = g["shoulder_y"]
	var hip_y: float = g["hip_y"]
	var pelvis_top: float = g["pelvis_top"]

	# --- torso: tapered prism, shoulders wider than waist --------------------
	_box(arrays, R_TOP, pelvis_top, shoulder_y, hw * 1.05, dep * 0.85, sw, dep, 0.0, 0.0, 0.0, 0.0)
	# --- pelvis / lower clothing --------------------------------------------
	if lower == V.LOWER_SKIRT:
		# flared skirt/dress silhouette from waist to just above the knee
		var hem_y: float = hip_y - g["thigh"] * 0.55
		_box(arrays, R_BOTTOM, hem_y, pelvis_top, hw * 1.5, dep * 1.15, hw * 1.02, dep * 0.95, 0.0, 0.0, 0.0, 0.0)
		_legs(arrays, g, lod, true)
	else:
		_box(arrays, R_BOTTOM, hip_y, pelvis_top, hw * 1.02, dep * 0.9, hw * 1.05, dep * 0.92, 0.0, 0.0, 0.0, 0.0)
		_legs(arrays, g, lod, false)

	# --- neck ----------------------------------------------------------------
	if lod != LOD_FAR:
		_box(arrays, R_SKIN, shoulder_y, g["neck_top"], hr * 0.45, hr * 0.45, hr * 0.4, hr * 0.4, 0.0, 0.0, 0.0, 0.0)
	# --- head ----------------------------------------------------------------
	_head(arrays, g, lod)
	# --- arms ----------------------------------------------------------------
	_arms(arrays, g, lod, sleeve)


static func _head(arrays: Array, g: Dictionary, lod: int) -> void:
	var hr: float = g["head_r"]
	var y0: float = g["head_bot"]
	var y1: float = g["head_top"]
	if lod == LOD_FAR:
		_box(arrays, R_SKIN, y0, y1, hr, hr, hr, hr, 0.0, 0.0, 0.0, 0.0)
		return
	# a lightly faceted head: narrower jaw at the bottom, flat crown
	var mid := (y0 + y1) * 0.5
	_box(arrays, R_SKIN, y0, mid, hr * 0.82, hr * 0.82, hr, hr, 0.0, 0.0, 0.0, 0.0)
	_box(arrays, R_SKIN, mid, y1, hr, hr, hr * 0.9, hr * 0.9, 0.0, 0.0, 0.0, 0.0)


static func _legs(arrays: Array, g: Dictionary, lod: int, skirt: bool) -> void:
	var hw: float = g["hip_w"]
	var dep: float = g["depth"]
	var hip_y: float = g["hip_y"]
	var foot_h: float = g["foot_h"]
	var shin: float = g["shin"]
	var knee_y := foot_h + shin
	var stance := hw * 0.55
	for side in [-1.0, 1.0]:
		var sd: float = side
		var cx := sd * stance
		# legs oppose arms: right leg (cx>0) swings with left arm. Use +sign on the
		# side that matches (see _arms). Lever grows downward from the hip pivot.
		var sgn := 1.0 if sd > 0.0 else -1.0
		# thigh (hidden under a skirt hem)
		if not skirt:
			_box(arrays, R_BOTTOM, knee_y, hip_y, hw * 0.5, dep * 0.55, hw * 0.55, dep * 0.6, cx, 0.0,
				_lev(hip_y, knee_y, hip_y, sgn), _lev(hip_y, hip_y, hip_y, sgn))
		# shin (bare below a skirt hem -> skin, else trouser -> bottom)
		var shin_reg := R_BOTTOM if not skirt else R_SKIN
		_box(arrays, shin_reg, foot_h, knee_y, hw * 0.42, dep * 0.5, hw * 0.46, dep * 0.52, cx, 0.0,
			_lev(hip_y, foot_h, hip_y, sgn), _lev(hip_y, knee_y, hip_y, sgn))
		# foot (extends forward in +Z), inherits the leg's swing
		if lod == LOD_FAR:
			_box(arrays, R_SHOES, 0.0, foot_h, hw * 0.44, dep * 1.4, hw * 0.44, dep * 1.4, cx, dep * 0.5,
				_lev(hip_y, foot_h, hip_y, sgn), _lev(hip_y, foot_h, hip_y, sgn))
		else:
			_box(arrays, R_SHOES, 0.0, foot_h, hw * 0.46, dep * 1.7, hw * 0.4, dep * 1.2, cx, dep * 0.7,
				_lev(hip_y, foot_h, hip_y, sgn), _lev(hip_y, foot_h, hip_y, sgn))


static func _arms(arrays: Array, g: Dictionary, lod: int, sleeve: int) -> void:
	var sw: float = g["shoulder_w"]
	var dep: float = g["depth"]
	var hr: float = g["head_r"]
	var shoulder_y: float = g["shoulder_y"]
	var hip_yf: float = g["hip_y"]
	var pelvis_topf: float = g["pelvis_top"]
	var arm_len := (shoulder_y - hip_yf) + pelvis_topf - hip_yf  # ~ torso+pelvis
	var upper := arm_len * 0.5
	var lower := arm_len * 0.42
	var hand := arm_len * 0.12
	var top_y := shoulder_y - 0.02
	var elbow_y := top_y - upper
	var wrist_y := elbow_y - lower
	var hand_y := wrist_y - hand
	var aw := hr * 0.5                      # arm half-thickness
	var ax := sw + aw * 0.95               # hang just outside the shoulder edge
	for side in [-1.0, 1.0]:
		var sd: float = side
		var cx := sd * ax
		# Left arm (cx<0) swings WITH the right leg; use opposite sign to the leg on
		# the same side so the body counter-rotates naturally.
		var sgn := -1.0 if sd > 0.0 else 1.0
		# upper arm (region top = shoulder covered)
		_box(arrays, R_TOP, elbow_y, top_y, aw, aw, aw * 1.05, aw * 1.1, cx, 0.0,
			_lev(top_y, elbow_y, top_y, sgn), _lev(top_y, top_y, top_y, sgn))
		# forearm: R_SLEEVE region -> shader paints skin (short) or top (long); when a
		# concrete sleeve is baked (near mesh), use it directly.
		var fore_reg := R_SLEEVE
		if sleeve == 0:
			fore_reg = R_SKIN
		elif sleeve == 1:
			fore_reg = R_TOP
		_box(arrays, fore_reg, wrist_y, elbow_y, aw * 0.9, aw * 0.9, aw, aw, cx, 0.0,
			_lev(top_y, wrist_y, top_y, sgn), _lev(top_y, elbow_y, top_y, sgn))
		# hand (skin), inherits the arm swing
		if lod != LOD_FAR:
			_box(arrays, R_SKIN, hand_y, wrist_y, aw * 0.85, aw * 0.85, aw * 0.85, aw * 0.85, cx, 0.0,
				_lev(top_y, hand_y, top_y, sgn), _lev(top_y, wrist_y, top_y, sgn))


static func _emit_hair(arrays: Array, center_y: float, radius: float, hair: int, lod: int) -> void:
	var hr: float = radius
	var y0: float = center_y - radius       # head bottom
	var y1: float = center_y + radius       # head top
	var crown := y1
	match hair:
		V.HAIR_CROP:
			_box(arrays, R_HAIR, y1 - hr * 0.35, crown + hr * 0.06, hr * 1.02, hr * 1.02, hr * 0.9, hr * 0.9, 0.0, 0.0, 0.0, 0.0)
		V.HAIR_SHORT:
			_box(arrays, R_HAIR, y1 - hr * 0.7, crown + hr * 0.12, hr * 1.06, hr * 1.06, hr * 0.95, hr * 0.98, 0.0, 0.0, 0.0, 0.0)
			# small fringe forward
			_box(arrays, R_HAIR, y1 - hr * 0.5, y1 - hr * 0.1, hr * 0.9, hr * 0.35, hr * 0.9, hr * 0.3, 0.0, hr * 0.85, 0.0, 0.0)
		V.HAIR_MEDIUM:
			_box(arrays, R_HAIR, y1 - hr * 1.1, crown + hr * 0.12, hr * 1.1, hr * 1.1, hr * 1.0, hr * 1.02, 0.0, 0.0, 0.0, 0.0)
		V.HAIR_BUN:
			_box(arrays, R_HAIR, y1 - hr * 0.7, crown + hr * 0.1, hr * 1.05, hr * 1.05, hr * 0.95, hr * 0.98, 0.0, 0.0, 0.0, 0.0)
			# bun at the back
			var by := y1 - hr * 0.1
			_box(arrays, R_HAIR, by - hr * 0.4, by + hr * 0.4, hr * 0.5, hr * 0.5, hr * 0.45, hr * 0.45, 0.0, -hr * 0.95, 0.0, 0.0)
		V.HAIR_LONG:
			_box(arrays, R_HAIR, y1 - hr * 1.2, crown + hr * 0.14, hr * 1.12, hr * 1.12, hr * 1.02, hr * 1.04, 0.0, 0.0, 0.0, 0.0)
			# fall down the back roughly to the shoulders (radius-relative)
			_box(arrays, R_HAIR, y0 - hr * 2.2, y1 - hr * 0.2, hr * 1.0, hr * 0.5, hr * 1.05, hr * 0.55, 0.0, -hr * 0.7, 0.0, 0.0)
		_:
			pass


# --- primitive: a tapered box (8 verts, 12 flat triangles) -------------------
# From y0..y1, half-extents (hw0,hd0) at bottom and (hw1,hd1) at top, centred at
# (cx,cz). lev0/lev1 are the signed limb lever written to UV2.y at bottom/top.
static func _box(arrays: Array, region: int, y0: float, y1: float,
		hw0: float, hd0: float, hw1: float, hd1: float,
		cx: float, cz: float, lev0: float, lev1: float) -> void:
	var verts: PackedVector3Array = arrays[0]
	var norms: PackedVector3Array = arrays[1]
	var uv2: PackedVector2Array = arrays[2]
	# 8 corners
	var b := [
		Vector3(cx - hw0, y0, cz - hd0), Vector3(cx + hw0, y0, cz - hd0),
		Vector3(cx + hw0, y0, cz + hd0), Vector3(cx - hw0, y0, cz + hd0),
	]
	var t := [
		Vector3(cx - hw1, y1, cz - hd1), Vector3(cx + hw1, y1, cz - hd1),
		Vector3(cx + hw1, y1, cz + hd1), Vector3(cx - hw1, y1, cz + hd1),
	]
	var lb := lev0
	var lt := lev1
	# faces as (corner list, is_top_face) with per-vertex lever
	# bottom (y0), top (y1), and 4 sides
	_quad(verts, norms, uv2, region, b[0], b[3], b[2], b[1], lb, lb, lb, lb)  # bottom (down)
	_quad(verts, norms, uv2, region, t[0], t[1], t[2], t[3], lt, lt, lt, lt)  # top (up)
	_quad(verts, norms, uv2, region, b[0], b[1], t[1], t[0], lb, lb, lt, lt)  # -Z
	_quad(verts, norms, uv2, region, b[1], b[2], t[2], t[1], lb, lb, lt, lt)  # +X
	_quad(verts, norms, uv2, region, b[2], b[3], t[3], t[2], lb, lb, lt, lt)  # +Z
	_quad(verts, norms, uv2, region, b[3], b[0], t[0], t[3], lb, lb, lt, lt)  # -X


static func _quad(verts: PackedVector3Array, norms: PackedVector3Array,
		uv2: PackedVector2Array, region: int,
		p0: Vector3, p1: Vector3, p2: Vector3, p3: Vector3,
		l0: float, l1: float, l2: float, l3: float) -> void:
	var n := (p1 - p0).cross(p2 - p0)
	if n.length() < 1e-9:
		n = Vector3.UP
	else:
		n = n.normalized()
	var r := float(region)
	verts.append(p0); verts.append(p1); verts.append(p2)
	norms.append(n); norms.append(n); norms.append(n)
	uv2.append(Vector2(r, l0)); uv2.append(Vector2(r, l1)); uv2.append(Vector2(r, l2))
	verts.append(p0); verts.append(p2); verts.append(p3)
	norms.append(n); norms.append(n); norms.append(n)
	uv2.append(Vector2(r, l0)); uv2.append(Vector2(r, l2)); uv2.append(Vector2(r, l3))


# Signed limb lever at height y, given the pivot at pivot_y and the far end at
# end_y. 0 at the pivot, ~1 at the free end; sign encodes the swing phase group.
static func _lev(pivot_y: float, y: float, end_y: float, sgn: float) -> float:
	var span: float = abs(pivot_y - end_y)
	if span < 1e-5:
		return 0.0
	var f: float = clampf(abs(pivot_y - y) / span, 0.0, 1.0)
	return sgn * f
