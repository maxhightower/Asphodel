extends RefCounted
class_name ResidentialHouseRenderer

## Residential Architecture V1 renderer (mission R15).
##
## Consumes the compiled ResidentialArchitectureV1 record on a detached-house
## building dict and emits batched, style-driven geometry into the shared
## per-chunk SurfaceTool. It NEVER re-rolls style/porch/garage/foundation: every
## architectural decision was already made authoritatively in Python
## (asphodel/world_source/residential_grammar.py). This renderer only turns that
## decision into vertices.
##
## Batching: all geometry goes into the caller's SurfaceTool (one mesh per chunk)
## using the shared WorldMaterials.building_material() shader. Material regions
## ride in COLOR.a (family id) exactly like the rest of the exterior renderer, so
## adding houses does not add draw calls or materials. No Node3D per window/post.
##
## Determinism: any per-house jitter reuses the compiled record fields
## (mirrored / plan_variant) and a stable bid hash — same bundle, same house.

# --- material-family + tint per residential facade subtype (Python
# FACADE_SUBTYPE_TO_FAMILY mirror; colour is a tint, the shader adds texture). ---
# Family ids are the WorldMaterials.B_* constants written as literals so this
# stays a valid GDScript const (cross-class const refs aren't allowed in a const
# initializer): BRICK 0, PAINTED_BRICK 1, SIDING 2, STUCCO 3, CONCRETE 4,
# STONE 5, METAL_PANEL 6, WOOD 7, GLASS_CURTAIN 8, PAINTED_MASONRY 9,
# ROOF_ASPHALT 10, ROOF_STANDING_SEAM 11, ROOF_MEMBRANE 12, ROOF_TILE 13,
# ROOF_GENERIC 14, NEUTRAL 15.
const _SUBTYPE := {
	"wood_lap":         {"fam": 2, "col": Color(0.78, 0.76, 0.70)},
	"fiber_cement_lap": {"fam": 2, "col": Color(0.74, 0.75, 0.72)},
	"board_and_batten": {"fam": 2, "col": Color(0.72, 0.70, 0.64)},
	"wood_shingle":     {"fam": 7, "col": Color(0.62, 0.54, 0.44)},
	"red_brick":        {"fam": 0, "col": Color(0.58, 0.34, 0.28)},
	"buff_brick":       {"fam": 0, "col": Color(0.74, 0.66, 0.52)},
	"dark_brick":       {"fam": 0, "col": Color(0.40, 0.28, 0.26)},
	"painted_brick":    {"fam": 1, "col": Color(0.82, 0.80, 0.76)},
	"stone_veneer":     {"fam": 5, "col": Color(0.66, 0.62, 0.55)},
	"smooth_stucco":    {"fam": 3, "col": Color(0.82, 0.78, 0.70)},
	"metal_panel":      {"fam": 6, "col": Color(0.66, 0.67, 0.68)},
	"none":             {"fam": 2, "col": Color(0.78, 0.76, 0.70)},
}
const _ROOF_FAM := {
	"asphalt_shingle": 10, "standing_seam_metal": 11,
	"tile": 13, "flat_membrane": 12, "roof_generic": 14,
}
const _NEUTRAL := 15
const _FAM_BRICK := 0
const _FAM_SIDING := 2

# pitch = rise / half-span (a tan factor): STEEP roofs really spike, VERY_LOW
# roofs read as shallow. eave = how far the roof overhangs the wall (metres).
const _PITCH_RISE := {"VERY_LOW": 0.24, "LOW": 0.48, "MEDIUM": 0.80, "STEEP": 1.20}
const _EAVE_OUT := {"TIGHT": 0.30, "NORMAL": 0.55, "WIDE": 0.95, "VERY_WIDE": 1.25}
const _ROOF_T := 0.34   # roof slab thickness → visible fascia + shadow at iso

const DOOR_COL := Color(0.10, 0.08, 0.07)
const WIN_COL := Color(0.12, 0.15, 0.20)
const TRIM_COL := Color(0.90, 0.89, 0.85)


## Entry point. Returns emitted vertex count, or -1 when the building carries no
## architecture record (caller then falls back to the legacy detail path).
static func emit(st: SurfaceTool, b: Dictionary, cells: PackedByteArray,
		origin: Vector2) -> int:
	var arch: Dictionary = b.get("architecture", {})
	if arch.is_empty():
		return -1
	var poly: Array = b.get("poly", [])
	if poly.size() < 3:
		return 0
	var ring := PackedVector2Array()
	for p in poly:
		ring.append(Vector2(float(p[0]), float(p[1])))
	var n := ring.size()

	var h := float(b.get("h", 4.0))
	var bid := int(b.get("bid", 0))
	var ent: Dictionary = b.get("entrance", {})
	var ent_edge := int(ent.get("edge", -1))
	var ent_t := clampf(float(ent.get("t", 0.5)), 0.05, 0.95)
	var ent_w := float(ent.get("w", 1.2))
	if ent_edge < 0 or ent_edge >= n:
		ent_edge = _longest_edge(ring)

	var facade: Dictionary = arch.get("facade", {})
	var roof: Dictionary = arch.get("roof", {})
	var found: Dictionary = arch.get("foundation", {})
	var porch: Dictionary = arch.get("porch", {})
	var win: Dictionary = arch.get("windows", {})
	var mods: Array = arch.get("modifications", [])
	var details: Array = arch.get("details", [])

	var found_h := clampf(float(found.get("height_m", 0.12)), 0.0, 1.6)
	var floors_top := h                        # wall top (observed/derived height)
	var body_lo := found_h                     # finished-floor level above grade

	# region tints/materials
	var front_m := _mat(String(facade.get("front", "wood_lap")))
	var side_m := _mat(String(facade.get("side_rear", "wood_lap")))
	var gable_m := _mat(String(facade.get("gable", "wood_lap")))
	var found_m := _mat(String(facade.get("foundation", "smooth_stucco")))
	# renovation: painted brick recolours front to a painted family.
	if "PAINTED_BRICK" in mods and int(front_m["fam"]) == _FAM_BRICK:
		front_m = _mat("painted_brick")
	if "REPLACEMENT_SIDING" in mods and int(front_m["fam"]) == _FAM_SIDING:
		front_m = {"fam": _FAM_SIDING, "col": front_m["col"].lightened(0.06)}

	var verts := 0

	# ---- R10 foundation skirt (visible base band above grade) ----
	if found_h > 0.02:
		verts += _skirt(st, ring, 0.0, found_h, found_m)

	# ---- walls: front region on the entrance edge (+ the two flanking front
	# edges), side/rear elsewhere. Gable material rides the pitched-roof gables. --
	var front_edges := _front_edge_set(ring, ent_edge)
	for i in range(n):
		var a := ring[i]
		var c := ring[(i + 1) % n]
		var seg := c - a
		var length := seg.length()
		if length <= 0.4:
			continue
		var region: Dictionary = front_m if front_edges.has(i) else side_m
		verts += _wall(st, a, c, body_lo, floors_top, region)

	var style := String(arch.get("style", {}).get("value", ""))
	var two_story := int(arch.get("massing", {}).get("story_profile", "ONE") == "TWO")

	# roof colour is needed by the porch roof too, so resolve it first.
	var roof_fam := int(_ROOF_FAM.get(String(roof.get("material", "asphalt_shingle")), 10))
	if "METAL_ROOF_RETROFIT" in mods:
		roof_fam = 11   # standing seam metal
	var roof_col := _roof_color(roof, roof_fam, bid)

	# ---- R9 windows (framed, per grammar) + entrance door ----
	verts += _fenestration(st, ring, ent_edge, ent_t, ent_w, body_lo, floors_top,
		front_edges, String(win.get("family", "SIMPLE_VERTICAL")),
		bool(win.get("symmetric", false)), two_story, bid)

	# ---- projecting bay window (Queen Anne / Victorian character) ----
	if "bay_projection" in details:
		verts += _bay(st, ring, ent_edge, body_lo, floors_top, front_m, two_story)

	# ---- arched entry surround on the facade (Spanish / Tudor / arched styles) ----
	if "arched_entry" in details or style == "SPANISH_ECLECTIC" or style == "TUDOR_REVIVAL":
		verts += _entry_arch(st, ring, ent_edge, ent_t, ent_w, body_lo, front_m)

	# ---- R11 porch / entry -> a real terrace: platform, balustrade, columns,
	#      porch roof, and an arched opening where the style calls for it ----
	verts += _porch(st, ring, ent_edge, ent_t, ent_w, body_lo, porch, found_h, bid,
		style, details, roof_col, front_m)

	# ---- R12 garage / carport ----
	verts += _parking(st, ring, ent_edge, body_lo, String(arch.get("parking", "SIDE_DRIVE")), bid)

	# ---- exterior side staircase up to a raised (pier-and-beam) floor ----
	if found_h > 0.45:
		verts += _side_stairs(st, ring, ent_edge, found_h, bid)

	# ---- R8 roof (solid, overhanging, with gable walls) ----
	verts += _roof(st, ring, floors_top, String(roof.get("family", "SIDE_GABLE")),
		String(roof.get("pitch", "MEDIUM")), String(roof.get("eave", "NORMAL")),
		roof_col, roof_fam, gable_m, ent_edge)

	# ---- details: chimney / dormer / gable decoration ----
	verts += _details(st, ring, floors_top, details, roof, gable_m, bid, ent_edge)

	return verts


# =========================================================================
# low-level batched primitives (self-contained; no coupling to ExteriorWorld)
# =========================================================================
static func _quad(st: SurfaceTool, p0: Vector3, p1: Vector3, p2: Vector3,
		p3: Vector3, nrm: Vector3, col: Color) -> int:
	st.set_color(col)
	for v in [p0, p1, p2, p0, p2, p3]:
		st.set_normal(nrm)
		st.add_vertex(v)
	return 6


static func _tri(st: SurfaceTool, p0: Vector3, p1: Vector3, p2: Vector3,
		nrm: Vector3, col: Color) -> int:
	st.set_color(col)
	for v in [p0, p1, p2]:
		st.set_normal(nrm)
		st.add_vertex(v)
	return 3


## An oriented box (center, edge tangent `along`, outward `out`, half sizes).
static func _box(st: SurfaceTool, center: Vector3, along: Vector3, out: Vector3,
		hw: float, hd: float, hh: float, col: Color) -> int:
	var up := Vector3(0.0, hh, 0.0)
	var a := along * hw
	var bb := out * hd
	var ppp := center + a + bb + up
	var ppm := center + a + bb - up
	var pmp := center + a - bb + up
	var pmm := center + a - bb - up
	var mpp := center - a + bb + up
	var mpm := center - a + bb - up
	var mmp := center - a - bb + up
	var mmm := center - a - bb - up
	var v := 0
	v += _quad(st, mpm, ppm, ppp, mpp, out, col)
	v += _quad(st, pmm, mmm, mmp, pmp, -out, col)
	v += _quad(st, mmp, mpp, ppp, pmp, Vector3.UP, col)
	v += _quad(st, mmm, pmm, ppm, mpm, Vector3.DOWN, col)
	v += _quad(st, pmm, ppm, ppp, pmp, along, col)
	v += _quad(st, mpm, mmm, mmp, mpp, -along, col)
	return v


static func _mat(subtype: String) -> Dictionary:
	return _SUBTYPE.get(subtype, _SUBTYPE["none"])


static func _enc(col: Color, fam: int) -> Color:
	return WorldMaterials.encode(col, fam)


static func _hash(a: int, b: int) -> int:
	var x: int = (a * 0x9E3779B1) ^ (b * 0x85EBCA6B)
	x = x & 0x7FFFFFFF
	x ^= (x >> 13)
	x = (x * 0x2545F491) & 0x7FFFFFFF
	return x


static func _longest_edge(ring: PackedVector2Array) -> int:
	var n := ring.size()
	var best := 0
	var best_len := -1.0
	for i in range(n):
		var l := (ring[(i + 1) % n] - ring[i]).length()
		if l > best_len:
			best_len = l
			best = i
	return best


## The entrance edge plus its two neighbours read as the street-facing "front"
## and share the front material region.
static func _front_edge_set(ring: PackedVector2Array, ent_edge: int) -> Dictionary:
	var n := ring.size()
	var s := {}
	s[ent_edge] = true
	if n >= 4:
		s[(ent_edge + 1) % n] = true
		s[(ent_edge - 1 + n) % n] = true
	return s


# =========================================================================
# walls / foundation
# =========================================================================
static func _wall(st: SurfaceTool, a: Vector2, c: Vector2, y0: float, y1: float,
		region: Dictionary) -> int:
	var nrm2 := Vector2((c.y - a.y), -(c.x - a.x)).normalized()
	var nrm := Vector3(nrm2.x, 0.0, nrm2.y)
	var col := _enc(region["col"], region["fam"])
	return _quad(st, Vector3(a.x, y0, a.y), Vector3(c.x, y0, c.y),
		Vector3(c.x, y1, c.y), Vector3(a.x, y1, a.y), nrm, col)


static func _skirt(st: SurfaceTool, ring: PackedVector2Array, y0: float, y1: float,
		region: Dictionary) -> int:
	var n := ring.size()
	var v := 0
	var col := _enc(region["col"].darkened(0.12), region["fam"])
	for i in range(n):
		var a := ring[i]
		var c := ring[(i + 1) % n]
		if (c - a).length() <= 0.3:
			continue
		var nrm2 := Vector2((c.y - a.y), -(c.x - a.x)).normalized()
		# push the skirt out a hair so it reads as a base ledge
		var o := nrm2 * 0.08
		v += _quad(st, Vector3(a.x + o.x, y0, a.y + o.y), Vector3(c.x + o.x, y0, c.y + o.y),
			Vector3(c.x + o.x, y1, c.y + o.y), Vector3(a.x + o.x, y1, a.y + o.y),
			Vector3(nrm2.x, 0.0, nrm2.y), col)
	return v


# =========================================================================
# R9 windows + entrance door
# =========================================================================
static func _fenestration(st: SurfaceTool, ring: PackedVector2Array, ent_edge: int,
		ent_t: float, ent_w: float, y0: float, y1: float, front_edges: Dictionary,
		grammar: String, symmetric: bool, two_story: int, bid: int) -> int:
	var n := ring.size()
	var body := y1 - y0
	var v := 0
	var floors := 2 if two_story == 1 else 1
	var fh := body / float(floors)
	for i in range(n):
		var a := ring[i]
		var c := ring[(i + 1) % n]
		var seg := c - a
		var length := seg.length()
		if length <= 2.0:
			continue
		var dir := seg / length
		var nrm2 := Vector2(seg.y, -seg.x).normalized()
		var nrm := Vector3(nrm2.x, 0.0, nrm2.y)
		var is_ent := (i == ent_edge)
		var is_front: bool = front_edges.has(i)
		# door span on the entrance edge (windows avoid it)
		var door_lo := -1.0
		var door_hi := -1.0
		if is_ent:
			var dt := (ent_w * 0.5 + 0.5) / length
			door_lo = ent_t - dt
			door_hi = ent_t + dt
			# entrance door
			var dc := a.lerp(c, ent_t)
			var e0 := dc - dir * (ent_w * 0.5) + nrm2 * 0.05
			var e1 := dc + dir * (ent_w * 0.5) + nrm2 * 0.05
			v += _quad(st, Vector3(e0.x, y0, e0.y), Vector3(e1.x, y0, e1.y),
				Vector3(e1.x, y0 + 2.1, e1.y), Vector3(e0.x, y0 + 2.1, e0.y), nrm, DOOR_COL)
		var specs := _window_specs(grammar, length, is_front, symmetric, bid, i)
		for f in range(floors):
			var wy := y0 + f * fh + fh * 0.32
			var wh := fh * (0.5 if grammar != "MCM_HORIZONTAL" else 0.42)
			for spec in specs:
				var t: float = spec[0]
				var ww: float = spec[1]
				var hscale: float = spec[2]
				if f == 0 and door_lo >= 0.0 and t > door_lo and t < door_hi:
					continue
				var center := a.lerp(c, t)
				var hw := minf(ww, length / float(specs.size() + 1) * 0.9) * 0.5
				var top := wy + wh * hscale
				if is_front:
					var muntins := grammar not in ["MCM_HORIZONTAL", "RANCH_PICTURE"]
					v += _window(st, center, dir, nrm2, hw, wy, top, muntins)
				else:
					var w0 := center - dir * hw + nrm2 * 0.04
					var w1 := center + dir * hw + nrm2 * 0.04
					v += _quad(st, Vector3(w0.x, wy, w0.y), Vector3(w1.x, wy, w1.y),
						Vector3(w1.x, top, w1.y), Vector3(w0.x, top, w0.y), nrm, WIN_COL)
	return v


## A framed window: recessed dark pane + trim surround (jambs/head), a protruding
## sill ledge, and optional muntin bars — so windows read as windows at iso.
static func _window(st: SurfaceTool, center: Vector2, dir: Vector2, nrm2: Vector2,
		hw: float, wy: float, top: float, muntins: bool) -> int:
	var nrm := Vector3(nrm2.x, 0.0, nrm2.y)
	var along := Vector3(dir.x, 0.0, dir.y)
	var trim := _enc(TRIM_COL, _NEUTRAL)
	var midy := (wy + top) * 0.5
	var hh := (top - wy) * 0.5
	var cen3 := Vector3(center.x, midy, center.y)
	var fo := nrm * 0.055
	var v := 0
	# glass pane
	var p := nrm2 * 0.03
	var g0 := center - dir * hw + p
	var g1 := center + dir * hw + p
	v += _quad(st, Vector3(g0.x, wy, g0.y), Vector3(g1.x, wy, g1.y),
		Vector3(g1.x, top, g1.y), Vector3(g0.x, top, g0.y), nrm, WIN_COL)
	# surround: two jambs, a head lintel, a protruding sill
	v += _box(st, cen3 + along * (hw + 0.06) + fo, along, nrm, 0.05, 0.035, hh + 0.1, trim)
	v += _box(st, cen3 - along * (hw + 0.06) + fo, along, nrm, 0.05, 0.035, hh + 0.1, trim)
	v += _box(st, Vector3(center.x, top + 0.07, center.y) + fo, along, nrm, hw + 0.13, 0.035, 0.05, trim)
	v += _box(st, Vector3(center.x, wy - 0.05, center.y) + nrm * 0.1, along, nrm, hw + 0.16, 0.09, 0.05, trim.darkened(0.05))
	if muntins:
		v += _box(st, cen3 + nrm * 0.045, along, nrm, 0.022, 0.03, hh, trim)
		v += _box(st, cen3 + nrm * 0.045, along, nrm, hw, 0.03, 0.022, trim)
	return v


## Return [[t_center, width_m, height_scale], ...] for one edge, per window
## grammar. Placement + proportion are what distinguish styles; geometry stays
## low-poly (flat recessed quads).
static func _window_specs(grammar: String, length: float, is_front: bool,
		symmetric: bool, bid: int, edge: int) -> Array:
	var out: Array = []
	match grammar:
		"MCM_HORIZONTAL":
			# one long horizontal band on the front; a strip elsewhere.
			if is_front:
				out.append([0.5, minf(length * 0.72, 6.0), 0.7])
			else:
				out.append([0.5, minf(length * 0.5, 4.0), 0.55])
		"RANCH_PICTURE":
			if is_front:
				out.append([0.34, minf(length * 0.34, 3.2), 1.0])   # picture window
				out.append([0.72, 1.0, 0.8])
			else:
				var cnt := maxi(1, int(round(length / 4.2)))
				for k in range(cnt):
					out.append([(k + 0.5) / cnt, 1.0, 0.8])
		"COLONIAL_SYMMETRIC":
			# strictly symmetric pairs about centre; even count.
			var pairs := clampi(int(round(length / 3.0)), 1, 3)
			for k in range(pairs):
				var off := (k + 1) * 0.5 / (pairs + 1)
				out.append([0.5 - off, 0.9, 1.0])
				out.append([0.5 + off, 0.9, 1.0])
		"FOURSQUARE_REGULAR":
			var cnt2 := clampi(int(round(length / 3.2)), 2, 4)
			for k in range(cnt2):
				out.append([(k + 0.5) / cnt2, 0.95, 1.0])
		"CRAFTSMAN_GROUPED":
			# grouped 2-3 near the ends.
			var groups := [0.28, 0.72] if length > 7.0 else [0.5]
			for g in groups:
				out.append([g - 0.06, 0.7, 0.95])
				out.append([g + 0.06, 0.7, 0.95])
		"TUDOR_GROUPED_VERTICAL":
			out.append([0.34, 0.6, 1.15])
			out.append([0.42, 0.6, 1.15])
			out.append([0.5, 0.6, 1.15])
		"VICTORIAN_ASYMMETRIC":
			out.append([0.28, 0.75, 1.2])
			out.append([0.6, 0.85, 1.0])
			if length > 8.0:
				out.append([0.82, 0.7, 0.9])
		"SUBURBAN_REGULAR":
			var cnt3 := clampi(int(round(length / 3.6)), 1, 4)
			for k in range(cnt3):
				out.append([(k + 0.5) / cnt3, 0.95, 0.95])
		_:   # SIMPLE_VERTICAL
			var cnt4 := clampi(int(round(length / 4.0)), 1, 4)
			for k in range(cnt4):
				out.append([(k + 0.5) / cnt4, 0.8, 1.1])
	return out


# =========================================================================
# R11 porch / entry
# =========================================================================
static func _porch(st: SurfaceTool, ring: PackedVector2Array, ent_edge: int,
		ent_t: float, ent_w: float, y0: float, porch: Dictionary, found_h: float,
		bid: int, style: String, details: Array, roof_col: Color,
		front_m: Dictionary) -> int:
	var family := String(porch.get("family", "NONE"))
	if family == "NONE":
		return 0
	var n := ring.size()
	var a := ring[ent_edge]
	var c := ring[(ent_edge + 1) % n]
	var seg := c - a
	var length := seg.length()
	if length <= 2.0:
		return 0
	var dir := seg / length
	var nrm2 := Vector2(seg.y, -seg.x).normalized()
	var nrm := Vector3(nrm2.x, 0.0, nrm2.y)
	var along := Vector3(dir.x, 0.0, dir.y)
	var depth := clampf(float(porch.get("depth_m", 2.0)), 1.2, 3.4)
	var wfrac := clampf(float(porch.get("width_fraction", 0.5)), 0.14, 1.0)
	var support := String(porch.get("support", "SIMPLE_POST"))
	var pw := minf(length * wfrac, length - 0.4)
	var t_center: float = 0.5 if wfrac > 0.65 else ent_t
	t_center = clampf(t_center, (pw * 0.5 + 0.2) / length, 1.0 - (pw * 0.5 + 0.2) / length)
	var dc := a.lerp(c, t_center)
	var dc3 := Vector3(dc.x, 0.0, dc.y)
	var v := 0
	var deck_col := _enc(Color(0.72, 0.70, 0.66), _NEUTRAL)
	var trim := _enc(TRIM_COL, _NEUTRAL)

	var recessed := family == "RECESSED"
	var floor_y := y0                                  # finished-floor height
	var eave_y := 2.55 + y0
	# recessed porches are shallow arcaded loggias (Spanish/Tudor), not a box.
	if recessed:
		depth = minf(depth, 1.7)
	var half := pw * 0.5
	var arcade := "arched_entry" in details or style == "SPANISH_ECLECTIC"
	var col_h := eave_y - floor_y

	# raised deck slab (a real terrace floor)
	v += _box(st, dc3 + nrm * (depth * 0.5) + Vector3(0.0, floor_y * 0.5, 0.0),
		along, nrm, half + 0.12, depth * 0.5, maxf(0.1, floor_y * 0.5), deck_col)

	# columns along the porch front (+ intermediates for wide porches)
	var cols: Array = [-1.0, 1.0]
	if pw > 6.5:
		cols = [-1.0, -0.5, 0.0, 0.5, 1.0]
	elif pw > 5.0:
		cols = [-1.0, -0.34, 0.34, 1.0]
	elif pw > 3.2:
		cols = [-1.0, 0.0, 1.0]
	var prev_top := Vector3.ZERO
	var have_prev := false
	for s in cols:
		var sf := float(s)
		var cbase := dc3 + along * (sf * (half - 0.18)) + nrm * (depth - 0.22) \
			+ Vector3(0.0, floor_y, 0.0)
		v += _column(st, cbase, col_h, support, along, nrm, trim, front_m)
		var top := cbase + Vector3(0.0, col_h, 0.0)
		if have_prev and arcade:
			v += _arch(st, prev_top, top, along, nrm, _enc(front_m["col"].lightened(0.15), front_m["fam"]))
		prev_top = top
		have_prev = true

	# balustrade between the end columns for open terraces
	if not recessed and family in ["FULL_WIDTH", "PARTIAL_FRONT", "WRAP_PARTIAL", "PROJECTING_GABLE"]:
		var lc := dc3 + along * (-(half - 0.18)) + nrm * (depth - 0.22) + Vector3(0, floor_y, 0)
		var rc := dc3 + along * ((half - 0.18)) + nrm * (depth - 0.22) + Vector3(0, floor_y, 0)
		v += _railing(st, lc, rc, along, 0.95, trim.darkened(0.05))

	# porch roof: front gable for PROJECTING_GABLE, else a low slab that ties into
	# the wall (with a beam/entablature the columns carry).
	var rcol := _enc(roof_col, _NEUTRAL)
	if family == "PROJECTING_GABLE":
		var pbase := dc3 + nrm * (depth * 0.5) + Vector3(0.0, eave_y, 0.0)
		v += _gable(st, pbase, along, nrm, half + 0.2, depth * 0.5 + 0.2, 0.25,
			clampf(half * 0.7, 0.8, 2.2), roof_col, _enc(front_m["col"], front_m["fam"]),
			_enc(roof_col.darkened(0.3), _NEUTRAL), true, false)
	else:
		# entablature beam the columns support
		v += _box(st, dc3 + nrm * (depth - 0.18) + Vector3(0.0, eave_y - 0.05, 0.0),
			along, nrm, half + 0.16, 0.1, 0.16, _enc(TRIM_COL, _NEUTRAL))
		v += _box(st, dc3 + nrm * (depth * 0.5) + Vector3(0.0, eave_y + 0.12, 0.0),
			along, nrm, half + 0.22, depth * 0.5 + 0.22, 0.12, rcol)

	# classical portico pediment (a front gable over the entry columns)
	if support == "CLASSICAL_SIMPLE" or "columns" in details:
		var pc := dc3 + nrm * (depth + 0.02) + Vector3(0.0, eave_y + 0.16, 0.0)
		var pl := pc - along * (half + 0.28)
		var pr := pc + along * (half + 0.28)
		var apex := (pl + pr) * 0.5 + Vector3(0.0, clampf(half * 0.6, 0.55, 1.05), 0.0)
		var ped := _enc(TRIM_COL, _NEUTRAL)
		var bk := nrm * -0.34
		v += _tri(st, pl, apex, pr, nrm, ped)
		v += _tri(st, pr + bk, apex + bk, pl + bk, -nrm, ped)
		v += _quad(st, pl + bk, pr + bk, pr, pl, Vector3.UP, ped.darkened(0.12))

	# front steps up to the deck
	v += _steps(st, dc3, along, nrm, minf(pw, ent_w + 1.8), depth, maxf(floor_y, 0.25))
	return v


## One porch support, styled. Round classical columns are an octagonal shaft with
## a base + capital; brick-pier columns are a masonry plinth under a tapered post;
## MCM posts are thin; tapered posts are frusta.
static func _column(st: SurfaceTool, base: Vector3, height: float, support: String,
		along: Vector3, nrm: Vector3, trim: Color, front_m: Dictionary) -> int:
	var v := 0
	var pier_col := _enc(front_m["col"].darkened(0.05), front_m["fam"])
	match support:
		"CLASSICAL_SIMPLE":
			# plinth + round (octagonal) shaft + a flared capital — a real column
			v += _box(st, base + Vector3(0, 0.1, 0), along, nrm, 0.22, 0.22, 0.1, trim)
			v += _octo(st, base + Vector3(0, height * 0.5, 0), 0.16, height * 0.92, trim)
			v += _box(st, base + Vector3(0, height - 0.08, 0), along, nrm, 0.24, 0.24, 0.12, trim)
		"TAPERED_POST_BRICK_PIER":
			v += _box(st, base + Vector3(0, height * 0.3, 0), along, nrm, 0.24, 0.24, height * 0.3, pier_col)
			v += _tapered_post(st, base + Vector3(0, height * 0.62, 0), 0.17, 0.11, height * 0.4, along, nrm, trim)
		"TAPERED_POST":
			v += _tapered_post(st, base + Vector3(0, height * 0.5, 0), 0.19, 0.12, height, along, nrm, trim)
		"PAIRED_POST":
			for o in [-0.15, 0.15]:
				v += _box(st, base + along * float(o) + Vector3(0, height * 0.5, 0), along, nrm, 0.07, 0.07, height * 0.5, trim)
			v += _box(st, base + Vector3(0, height - 0.05, 0), along, nrm, 0.26, 0.1, 0.08, trim)
		"MCM_THIN":
			v += _box(st, base + Vector3(0, height * 0.5, 0), along, nrm, 0.06, 0.06, height * 0.5, trim.darkened(0.25))
		"MCM_SLANTED":
			v += _box(st, base + nrm * 0.16 + Vector3(0, height * 0.5, 0), along, nrm, 0.06, 0.06, height * 0.52, trim.darkened(0.25))
		"NONE":
			pass
		_:
			v += _box(st, base + Vector3(0, height * 0.5, 0), along, nrm, 0.11, 0.11, height * 0.5, trim)
			v += _box(st, base + Vector3(0, height - 0.05, 0), along, nrm, 0.15, 0.15, 0.06, trim)
	return v


## Octagonal vertical prism (a round-ish column shaft), centred at `center`.
static func _octo(st: SurfaceTool, center: Vector3, r: float, hh: float,
		col: Color) -> int:
	var v := 0
	var up := Vector3(0, hh * 0.5, 0)
	var prev := Vector3.ZERO
	for i in range(9):
		var ang := TAU * float(i) / 8.0
		var p := Vector3(cos(ang) * r, 0, sin(ang) * r)
		if i > 0:
			var n := (prev + p).normalized()
			v += _quad(st, center + prev - up, center + p - up, center + p + up,
				center + prev + up, Vector3(n.x, 0, n.z), col)
		prev = p
	return v


## Square post that narrows toward the top (a frustum): 4 trapezoids.
static func _tapered_post(st: SurfaceTool, center: Vector3, rb: float, rt: float,
		hh: float, along: Vector3, nrm: Vector3, col: Color) -> int:
	var up := Vector3(0, hh * 0.5, 0)
	var v := 0
	var ab := along
	var nb := nrm
	# four faces
	var corners_b := [ab * rb + nb * rb, ab * rb - nb * rb, -ab * rb - nb * rb, -ab * rb + nb * rb]
	var corners_t := [ab * rt + nb * rt, ab * rt - nb * rt, -ab * rt - nb * rt, -ab * rt + nb * rt]
	for i in range(4):
		var b0: Vector3 = center - up + corners_b[i]
		var b1: Vector3 = center - up + corners_b[(i + 1) % 4]
		var t1: Vector3 = center + up + corners_t[(i + 1) % 4]
		var t0: Vector3 = center + up + corners_t[i]
		var fn := (b0 + b1 - center * 2.0 + Vector3(0, 0, 0)).normalized()
		v += _quad(st, b0, b1, t1, t0, fn, col)
	return v


## A porch balustrade between two posts: top rail, bottom rail, and balusters.
static func _railing(st: SurfaceTool, p0: Vector3, p1: Vector3, along: Vector3,
		height: float, col: Color) -> int:
	var v := 0
	var span := (p1 - p0)
	var length := span.length()
	if length < 0.4:
		return 0
	var dir := span / length
	var mid := (p0 + p1) * 0.5
	# top + bottom rails
	v += _box(st, mid + Vector3(0, height, 0), dir, Vector3(0, 0, 1), length * 0.5, 0.05, 0.06, col)
	v += _box(st, mid + Vector3(0, 0.12, 0), dir, Vector3(0, 0, 1), length * 0.5, 0.05, 0.05, col)
	# balusters
	var count := clampi(int(length / 0.32), 2, 18)
	for k in range(count + 1):
		var t := float(k) / float(count)
		var bp := p0 + span * t + Vector3(0, height * 0.5, 0)
		v += _box(st, bp, dir, Vector3(0, 0, 1), 0.025, 0.025, height * 0.5, col)
	return v


## A shallow arch spanning between two column tops (Spanish / arched entries):
## a stepped set of chords approximating a semicircle, filled as a thin band.
static func _arch(st: SurfaceTool, l: Vector3, r: Vector3, along: Vector3,
		nrm: Vector3, col: Color) -> int:
	var span := r - l
	var length := span.length()
	if length < 0.6 or length > 6.0:
		return 0
	var dir := span / length
	var rise := minf(length * 0.4, 0.9)
	var segs := 5
	var v := 0
	var prev := l
	for k in range(1, segs + 1):
		var t := float(k) / float(segs)
		var y := sin(PI * t) * rise
		var p := l + span * t + Vector3(0, y, 0)
		# a thin downward band under the arch chord
		v += _quad(st, prev, p, p - Vector3(0, 0.16, 0), prev - Vector3(0, 0.16, 0),
			nrm, col)
		prev = p
	return v


## An arched entry surround raised on the facade over the front door (Spanish /
## Tudor / arched styles): a curved molding band following a semicircle above the
## door head, protruding from the wall so it reads as a real arch at iso.
static func _entry_arch(st: SurfaceTool, ring: PackedVector2Array, ent_edge: int,
		ent_t: float, ent_w: float, y0: float, front_m: Dictionary) -> int:
	var n := ring.size()
	var a := ring[ent_edge]
	var c := ring[(ent_edge + 1) % n]
	var seg := c - a
	var length := seg.length()
	if length < 2.4:
		return 0
	var dir := seg / length
	var nrm2 := Vector2(seg.y, -seg.x).normalized()
	var nrm := Vector3(nrm2.x, 0.0, nrm2.y)
	var along := Vector3(dir.x, 0.0, dir.y)
	var dc := a.lerp(c, ent_t)
	var dc3 := Vector3(dc.x, 0.0, dc.y)
	var hw := ent_w * 0.62
	var spring_y := y0 + 2.05
	var rise := hw * 0.95
	var col := _enc(front_m["col"].lightened(0.18), front_m["fam"])
	var fo := nrm * 0.07
	var band := 0.16
	var segs := 7
	var v := 0
	var prev := dc3 - along * hw + Vector3(0.0, spring_y, 0.0) + fo
	# vertical jamb moldings up to the springline
	v += _box(st, dc3 - along * hw + Vector3(0.0, spring_y * 0.5 + y0 * 0.5, 0.0) + nrm * 0.05,
		along, nrm, 0.07, 0.05, (spring_y - y0) * 0.5, col)
	v += _box(st, dc3 + along * hw + Vector3(0.0, spring_y * 0.5 + y0 * 0.5, 0.0) + nrm * 0.05,
		along, nrm, 0.07, 0.05, (spring_y - y0) * 0.5, col)
	for k in range(1, segs + 1):
		var tt := float(k) / float(segs)
		var ang := PI * tt
		var p := dc3 + along * (hw * cos(PI - ang)) \
			+ Vector3(0.0, spring_y + sin(ang) * rise, 0.0) + fo
		v += _quad(st, prev, p, p - Vector3(0.0, band, 0.0), prev - Vector3(0.0, band, 0.0), nrm, col)
		prev = p
	return v


## A projecting bay window (Queen Anne / Victorian): a canted 3-face box out of
## the FRONT (entrance) wall, offset to one side of the door, each face carrying a
## tall window. Placed on the entrance edge so it always faces the street.
static func _bay(st: SurfaceTool, ring: PackedVector2Array, ent_edge: int,
		y0: float, y1: float, front_m: Dictionary, two_story: int) -> int:
	var n := ring.size()
	var e := ent_edge
	var a := ring[e]
	var c := ring[(e + 1) % n]
	var seg := c - a
	var length := seg.length()
	if length < 5.0:
		# entrance edge too short — try a neighbour
		e = (ent_edge + 1) % n
		a = ring[e]
		c = ring[(e + 1) % n]
		seg = c - a
		length = seg.length()
		if length < 4.0:
			return 0
	var dir := seg / length
	var nrm2 := Vector2(seg.y, -seg.x).normalized()
	var nrm := Vector3(nrm2.x, 0.0, nrm2.y)
	var along := Vector3(dir.x, 0.0, dir.y)
	var bw := minf(2.8, length * 0.34)
	# offset the bay to a side of the door (door sits ~mid the entrance edge)
	var t := clampf(0.78, (bw * 0.6) / length, 1.0 - (bw * 0.6) / length)
	if e != ent_edge:
		t = 0.5
	var proj := 1.15
	var fh := (y1 - y0) / (2.0 if two_story == 1 else 1.0)
	var top := y0 + fh * 0.95        # a ground-floor bay window
	var col := _enc(front_m["col"], front_m["fam"])
	var wcol := WIN_COL
	var cen := a.lerp(c, t)
	var cen3 := Vector3(cen.x, 0.0, cen.y)
	# three canted faces: left, front, right
	var l0 := cen3 - along * (bw * 0.5)
	var r0 := cen3 + along * (bw * 0.5)
	var lf := l0 + nrm * proj + along * (bw * 0.18)
	var rf := r0 + nrm * proj - along * (bw * 0.18)
	var v := 0
	var faces := [[l0, lf], [lf, rf], [rf, r0]]
	for f in faces:
		var p0: Vector3 = f[0]
		var p1: Vector3 = f[1]
		var fn2 := Vector2((p1.z - p0.z), -(p1.x - p0.x)).normalized()
		var fn := Vector3(fn2.x, 0, fn2.y)
		# wall panel
		v += _quad(st, Vector3(p0.x, y0, p0.z), Vector3(p1.x, y0, p1.z),
			Vector3(p1.x, top, p1.z), Vector3(p0.x, top, p0.z), fn, col)
		# window on the panel
		var wp0 := p0.lerp(p1, 0.2)
		var wp1 := p0.lerp(p1, 0.8)
		var wy := y0 + (top - y0) * 0.28
		var wt := y0 + (top - y0) * 0.82
		v += _quad(st, Vector3(wp0.x, wy, wp0.z) + fn * 0.02, Vector3(wp1.x, wy, wp1.z) + fn * 0.02,
			Vector3(wp1.x, wt, wp1.z) + fn * 0.02, Vector3(wp0.x, wt, wp0.z) + fn * 0.02, fn, wcol)
	# little hip roof cap over the bay
	var capc := (lf + rf) * 0.5
	v += _box(st, Vector3(capc.x, top + 0.18, capc.z), along, nrm, bw * 0.55, proj * 0.7, 0.16,
		_enc(Color(0.33, 0.31, 0.31), _NEUTRAL))
	return v


## Exterior side staircase up to a raised (pier-and-beam) finished floor.
static func _side_stairs(st: SurfaceTool, ring: PackedVector2Array, ent_edge: int,
		found_h: float, bid: int) -> int:
	var n := ring.size()
	var e := (ent_edge + 1) % n
	var a := ring[e]
	var c := ring[(e + 1) % n]
	var seg := c - a
	var length := seg.length()
	if length < 4.0:
		return 0
	var dir := seg / length
	var nrm2 := Vector2(seg.y, -seg.x).normalized()
	var nrm := Vector3(nrm2.x, 0.0, nrm2.y)
	var along := Vector3(dir.x, 0.0, dir.y)
	var t := 0.28 if (_hash(bid, 77) & 1) == 0 else 0.72
	var base := Vector3(a.lerp(c, t).x, 0.0, a.lerp(c, t).y)
	var steps := clampi(int(round(found_h / 0.18)), 2, 6)
	var col := _enc(Color(0.64, 0.62, 0.58), _NEUTRAL)
	var v := 0
	for k in range(steps):
		var y := found_h * (1.0 - float(k + 1) / float(steps))
		var out := 0.35 + k * 0.3
		var ctr := base + nrm * out + Vector3(0.0, y + 0.06, 0.0)
		v += _box(st, ctr, along, nrm, 0.75, 0.16, 0.07, col)
	return v


static func _steps(st: SurfaceTool, dc3: Vector3, along: Vector3, nrm: Vector3,
		w: float, depth: float, rise: float) -> int:
	var n_steps := clampi(int(round(rise / 0.18)), 1, 4)
	var col := _enc(Color(0.66, 0.64, 0.60), _NEUTRAL)
	var v := 0
	for k in range(n_steps):
		var y := rise * (1.0 - float(k + 1) / float(n_steps))
		var out := depth + 0.2 + k * 0.28
		var ctr := dc3 + nrm * out + Vector3(0.0, y + 0.05, 0.0)
		v += _box(st, ctr, along, nrm, w * 0.5, 0.14, 0.06, col)
	return v


# =========================================================================
# R12 garage / carport
# =========================================================================
static func _parking(st: SurfaceTool, ring: PackedVector2Array, ent_edge: int,
		y0: float, family: String, bid: int) -> int:
	if family == "NONE" or family == "SIDE_DRIVE" or family == "DETACHED_REAR_OBSERVED":
		return 0
	var n := ring.size()
	# choose the front edge (entrance edge or a neighbour) with room; mirrored plan
	# swaps the side. Attached-side uses a side edge.
	var use_edge := ent_edge
	if family == "ATTACHED_SIDE":
		use_edge = (ent_edge + 1) % n
	var a := ring[use_edge]
	var c := ring[(use_edge + 1) % n]
	var seg := c - a
	var length := seg.length()
	if length < 5.0:
		return 0
	var dir := seg / length
	var nrm2 := Vector2(seg.y, -seg.x).normalized()
	var nrm := Vector3(nrm2.x, 0.0, nrm2.y)
	var along := Vector3(dir.x, 0.0, dir.y)
	var two := family in ["ATTACHED_FRONT_TWO", "INTEGRATED_TWO"]
	var door_w := 4.6 if two else 2.6
	door_w = minf(door_w, length * 0.7)
	var side := 1.0 if (_hash(bid, 91) & 1) == 0 else -1.0     # deterministic garage side
	var t := clampf(0.5 + side * 0.24, door_w * 0.5 / length, 1.0 - door_w * 0.5 / length)
	var gc := a.lerp(c, t)
	var gc3 := Vector3(gc.x, 0.0, gc.y)
	var v := 0
	var integrated := family in ["INTEGRATED_ONE", "INTEGRATED_TWO"]
	var carport := family == "CARPORT"
	if carport:
		# open carport: a flat roof slab on two thin posts, no door.
		var cd := 5.0
		v += _box(st, gc3 + nrm * (cd * 0.5) + Vector3(0.0, 2.5, 0.0), along, nrm,
			door_w * 0.5 + 0.2, cd * 0.5, 0.08, _enc(Color(0.5, 0.5, 0.52), _NEUTRAL))
		for s in [-1.0, 1.0]:
			v += _box(st, gc3 + along * (float(s) * door_w * 0.5) + nrm * (cd - 0.3) + Vector3(0.0, 1.25, 0.0),
				along, nrm, 0.06, 0.06, 1.25, _enc(TRIM_COL, _NEUTRAL))
		return v
	# attached / integrated garage door panel
	var gh := 2.15
	var g0 := gc - dir * (door_w * 0.5) + nrm2 * 0.03
	var g1 := gc + dir * (door_w * 0.5) + nrm2 * 0.03
	v += _quad(st, Vector3(g0.x, y0 + 0.05, g0.y), Vector3(g1.x, y0 + 0.05, g1.y),
		Vector3(g1.x, y0 + gh, g1.y), Vector3(g0.x, y0 + gh, g0.y), nrm,
		_enc(Color(0.60, 0.58, 0.55), _NEUTRAL))
	v += _box(st, gc3 + Vector3(0.0, y0 + gh + 0.08, 0.0), along, nrm,
		door_w * 0.5 + 0.12, 0.08, 0.08, _enc(TRIM_COL, _NEUTRAL))
	# a front-projecting single garage gets a small forward mass (reads as a wing)
	if not integrated and family in ["ATTACHED_FRONT_ONE", "ATTACHED_FRONT_TWO"]:
		var proj := 1.6
		v += _quad(st, Vector3(g0.x, y0, g0.y), Vector3(g0.x + nrm2.x * proj, y0, g0.y + nrm2.y * proj),
			Vector3(g0.x + nrm2.x * proj, y0 + gh + 0.4, g0.y + nrm2.y * proj),
			Vector3(g0.x, y0 + gh + 0.4, g0.y), along, _enc(Color(0.7, 0.68, 0.63), _NEUTRAL))
	return v


# =========================================================================
# R8 roof
# =========================================================================
static func _roof_color(roof: Dictionary, fam: int, bid: int) -> Color:
	# fam: 13 tile, 11 standing-seam, 12 membrane, 10 asphalt (per WorldMaterials).
	var base := Color(0.32, 0.31, 0.33)
	if fam == 13:
		base = Color(0.55, 0.34, 0.26)
	elif fam == 11:
		base = Color(0.40, 0.42, 0.45)
	elif fam == 12:
		base = Color(0.30, 0.30, 0.32)
	else:
		var pick := _hash(bid, 23) % 4
		base = [Color(0.30, 0.30, 0.34), Color(0.36, 0.29, 0.25),
			Color(0.27, 0.31, 0.38), Color(0.33, 0.34, 0.31)][pick]
	return _enc(base, fam)


static func _obb(ring: PackedVector2Array) -> Dictionary:
	# principal axis via longest edge direction; centre = vertex average.
	var e := _longest_edge(ring)
	var n := ring.size()
	var dir := (ring[(e + 1) % n] - ring[e]).normalized()
	var perp := Vector2(-dir.y, dir.x)
	var cx := 0.0
	var cz := 0.0
	for p in ring:
		cx += p.x
		cz += p.y
	var ctr := Vector2(cx / n, cz / n)
	var lo_u := 1e9
	var hi_u := -1e9
	var lo_w := 1e9
	var hi_w := -1e9
	for p in ring:
		var d := p - ctr
		var u := d.dot(dir)
		var w := d.dot(perp)
		lo_u = minf(lo_u, u); hi_u = maxf(hi_u, u)
		lo_w = minf(lo_w, w); hi_w = maxf(hi_w, w)
	return {"ctr": ctr, "dir": dir, "perp": perp,
		"half_u": (hi_u - lo_u) * 0.5, "half_w": (hi_w - lo_w) * 0.5,
		"cu": (hi_u + lo_u) * 0.5, "cw": (hi_w + lo_w) * 0.5}


static func _roof(st: SurfaceTool, ring: PackedVector2Array, h: float, family: String,
		pitch: String, eave: String, roof_col: Color, roof_fam: int,
		gable_m: Dictionary, ent_edge: int) -> int:
	var ob := _obb(ring)
	var dir: Vector2 = ob["dir"]
	var perp: Vector2 = ob["perp"]
	var ctr: Vector2 = ob["ctr"] + dir * float(ob["cu"]) + perp * float(ob["cw"])
	var hu: float = ob["half_u"]
	var hw: float = ob["half_w"]
	var eo: float = _EAVE_OUT.get(eave, 0.55)
	var pf: float = _PITCH_RISE.get(pitch, 0.8)
	var v := 0
	var gcol := _enc(gable_m["col"], gable_m["fam"])
	var fascia := _enc(roof_col.darkened(0.32), _NEUTRAL)
	var d3 := Vector3(dir.x, 0.0, dir.y)
	var p3 := Vector3(perp.x, 0.0, perp.y)
	var base := Vector3(ctr.x, h, ctr.y)

	match family:
		"FLAT":
			v += _flat_roof(st, ring, h, roof_col, fascia)
		"SHED_COMPOSITE":
			var rise := clampf(minf(hu, hw) * 2.0 * pf, 0.8, 5.5)
			v += _gable(st, base, d3, p3, hu, hw, eo, rise, roof_col, gcol, fascia, false, true)
		"LOW_HIP", "HIP", "CROSS_HIP", "COMPLEX_HIP_GABLE":
			var rise := clampf(minf(hu, hw) * pf, 0.6, 6.0)
			v += _hip(st, base, d3, p3, hu, hw, eo, rise, roof_col, fascia)
		"FRONT_GABLE":
			var rise := clampf(hw * pf, 0.9, 7.0)
			v += _gable(st, base, d3, p3, hu, hw, eo, rise, roof_col, gcol, fascia, true, false)
		_:   # SIDE_GABLE / CROSS_GABLE / LOW_GABLE
			var rise := clampf(hw * pf, 0.8, 7.0)
			v += _gable(st, base, d3, p3, hu, hw, eo, rise, roof_col, gcol, fascia, false, false)
	return v


## Solid gable roof: two thick sloped planes overhanging the walls, closed by a
## fascia band all round (so the overhang reads as a real eave with a shadow),
## triangular gable-end walls at the WALL line in gable material, and a ridge cap.
## `shed` collapses one slope for a mono-pitch (MCM) roof.
static func _gable(st: SurfaceTool, base: Vector3, d3: Vector3, p3: Vector3,
		hu: float, hw: float, eo: float, rise: float, roof_col: Color,
		gable_col: Color, fascia: Color, front: bool, shed: bool) -> int:
	var v := 0
	var ridge_axis := d3 if not front else p3
	var slope_axis := p3 if not front else d3
	var rl_wall: float = hu if not front else hw
	var sw_wall: float = hw if not front else hu
	var rl := rl_wall + eo
	var sw := sw_wall + eo
	var t := _ROOF_T
	var up := Vector3(0.0, rise, 0.0)
	var tv := Vector3(0.0, t, 0.0)
	# ridge line (shed: ridge sits over the +slope eave instead of the centre)
	var rcenter := base if not shed else base + slope_axis * sw
	var ridge0 := rcenter - ridge_axis * rl + up
	var ridge1 := rcenter + ridge_axis * rl + up
	var eA0 := base - ridge_axis * rl - slope_axis * sw
	var eA1 := base + ridge_axis * rl - slope_axis * sw
	var eB0 := base - ridge_axis * rl + slope_axis * sw
	var eB1 := base + ridge_axis * rl + slope_axis * sw
	# top slope surfaces
	v += _quad(st, eA0, eA1, ridge1, ridge0, Vector3.UP, roof_col)      # - side
	if not shed:
		v += _quad(st, eB1, eB0, ridge0, ridge1, Vector3.UP, roof_col)  # + side
	else:
		# shed: the high side is a vertical wall band in gable material
		v += _quad(st, eB0, eB1, ridge1, ridge0, slope_axis, gable_col)
	# underside (soffit) + eave fascia along the two long eaves
	v += _eave_edge(st, eA0, eA1, t, fascia)
	if not shed:
		v += _eave_edge(st, eB1, eB0, t, fascia)
	# rake fascia (sloped gable edges) both ends
	v += _quad(st, eA0, eA0 - tv, ridge0 - tv, ridge0, -ridge_axis, fascia)
	v += _quad(st, ridge1, ridge1 - tv, eA1 - tv, eA1, ridge_axis, fascia)
	if not shed:
		v += _quad(st, ridge0, ridge0 - tv, eB0 - tv, eB0, -ridge_axis, fascia)
		v += _quad(st, eB1, eB1 - tv, ridge1 - tv, ridge1, ridge_axis, fascia)
	# gable-end walls at the WALL line (triangles, gable material)
	if not shed:
		var gneg0 := base - ridge_axis * rl_wall - slope_axis * sw_wall
		var gneg1 := base - ridge_axis * rl_wall + slope_axis * sw_wall
		var gnegR := rcenter - ridge_axis * rl_wall + up
		v += _tri(st, gneg0, gnegR, gneg1, -ridge_axis, gable_col)
		var gpos0 := base + ridge_axis * rl_wall - slope_axis * sw_wall
		var gpos1 := base + ridge_axis * rl_wall + slope_axis * sw_wall
		var gposR := rcenter + ridge_axis * rl_wall + up
		v += _tri(st, gpos0, gposR, gpos1, ridge_axis, gable_col)
		# ridge cap board
		v += _box(st, (ridge0 + ridge1) * 0.5, ridge_axis, slope_axis,
			rl, 0.12, 0.1, fascia.lightened(0.1))
	return v


## A downward fascia band + soffit under one eave edge (e0->e1 at eave height).
static func _eave_edge(st: SurfaceTool, e0: Vector3, e1: Vector3, t: float,
		fascia: Color) -> int:
	var tv := Vector3(0.0, t, 0.0)
	var outn := Vector3(0, -1, 0)
	var v := 0
	v += _quad(st, e0, e1, e1 - tv, e0 - tv, outn, fascia)   # fascia face
	return v


static func _hip(st: SurfaceTool, base: Vector3, d3: Vector3, p3: Vector3,
		hu: float, hw: float, eo: float, rise: float, roof_col: Color,
		fascia: Color) -> int:
	var v := 0
	var eu := hu + eo
	var ew := hw + eo
	var t := _ROOF_T
	var tv := Vector3(0.0, t, 0.0)
	var up := Vector3(0.0, rise, 0.0)
	var rlen := maxf(0.2, hu - hw)     # ridge length for a true hip
	var ridge0 := base - d3 * rlen + up
	var ridge1 := base + d3 * rlen + up
	var e00 := base - d3 * eu - p3 * ew
	var e01 := base - d3 * eu + p3 * ew
	var e10 := base + d3 * eu - p3 * ew
	var e11 := base + d3 * eu + p3 * ew
	# four hip faces
	v += _quad(st, e00, e10, ridge1, ridge0, Vector3.UP, roof_col)
	v += _quad(st, e11, e01, ridge0, ridge1, Vector3.UP, roof_col)
	v += _tri(st, e00, ridge0, e01, -d3, roof_col)
	v += _tri(st, e10, e11, ridge1, d3, roof_col)
	# perimeter fascia band (all four eaves)
	v += _quad(st, e00, e10, e10 - tv, e00 - tv, -p3, fascia)
	v += _quad(st, e11, e01, e01 - tv, e11 - tv, p3, fascia)
	v += _quad(st, e10, e11, e11 - tv, e10 - tv, d3, fascia)
	v += _quad(st, e01, e00, e00 - tv, e01 - tv, -d3, fascia)
	v += _box(st, (ridge0 + ridge1) * 0.5, d3, p3, rlen, 0.12, 0.1,
		fascia.lightened(0.1))
	return v


static func _flat_roof(st: SurfaceTool, ring: PackedVector2Array, h: float,
		roof_col: Color, fascia: Color) -> int:
	var tris := Geometry2D.triangulate_polygon(ring)
	if tris.is_empty():
		return 0
	var v := 0
	# raised parapet band so a flat roof reads as a defined edge, not a cut box
	var n := ring.size()
	var ph := 0.35
	for i in range(n):
		var a := ring[i]
		var c := ring[(i + 1) % n]
		if (c - a).length() <= 0.3:
			continue
		var nrm2 := Vector2((c.y - a.y), -(c.x - a.x)).normalized()
		var nrm := Vector3(nrm2.x, 0.0, nrm2.y)
		v += _quad(st, Vector3(a.x, h, a.y), Vector3(c.x, h, c.y),
			Vector3(c.x, h + ph, c.y), Vector3(a.x, h + ph, a.y), nrm, fascia)
	st.set_color(roof_col)
	for i in range(0, tris.size(), 3):
		for k in [tris[i], tris[i + 1], tris[i + 2]]:
			st.set_normal(Vector3.UP)
			st.add_vertex(Vector3(ring[k].x, h + 0.08, ring[k].y))
		v += 3
	return v


# =========================================================================
# details (chimney / dormer / stone accent) — only what reads at iso scale
# =========================================================================
static func _details(st: SurfaceTool, ring: PackedVector2Array, h: float,
		details: Array, roof: Dictionary, gable_m: Dictionary, bid: int,
		ent_edge: int) -> int:
	var v := 0
	var ob := _obb(ring)
	var dirv: Vector2 = ob["dir"]
	var perpv: Vector2 = ob["perp"]
	var half_u: float = ob["half_u"]
	var half_w: float = ob["half_w"]
	var ctr: Vector2 = ob["ctr"] + dirv * float(ob["cu"]) + perpv * float(ob["cw"])
	var d3 := Vector3(dirv.x, 0.0, dirv.y)
	var p3 := Vector3(perpv.x, 0.0, perpv.y)
	if ("chimney_prominent" in details) or ("chimney_modest" in details):
		var big: bool = "chimney_prominent" in details
		var off := (float(_hash(bid, 61) % 100) / 100.0 - 0.5) * half_u
		var cpos := Vector3(ctr.x, h, ctr.y) + d3 * off + p3 * (half_w * 0.6)
		var ch := 1.6 if big else 1.0
		var cw := 0.5 if big else 0.35
		v += _box(st, cpos + Vector3(0.0, ch * 0.5, 0.0), d3, p3, cw, cw, ch,
			_enc(Color(0.46, 0.30, 0.26), _FAM_BRICK))
	if "dormer_front" in details and roof.get("family", "") != "FLAT":
		var dc := Vector3(ctr.x, h + 0.6, ctr.y) + p3 * (half_w * 0.4)
		v += _box(st, dc, d3, p3, 0.9, 0.5, 0.5, _enc(gable_m["col"], gable_m["fam"]))
	return v
