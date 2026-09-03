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

const _PITCH_RISE := {"VERY_LOW": 0.14, "LOW": 0.28, "MEDIUM": 0.5, "STEEP": 0.85}
const _EAVE_OUT := {"TIGHT": 0.15, "NORMAL": 0.45, "WIDE": 0.8, "VERY_WIDE": 1.1}

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

	# ---- R9 windows (rhythm/proportion per grammar) + entrance door ----
	verts += _fenestration(st, ring, ent_edge, ent_t, ent_w, body_lo, floors_top,
		front_edges, String(win.get("family", "SIMPLE_VERTICAL")),
		bool(win.get("symmetric", false)), int(arch.get("massing", {}).get(
			"story_profile", "ONE") == "TWO"), bid)

	# ---- R11 porch / entry ----
	verts += _porch(st, ring, ent_edge, ent_t, ent_w, body_lo, porch, found_h, bid)

	# ---- R12 garage / carport ----
	verts += _parking(st, ring, ent_edge, body_lo, String(arch.get("parking", "SIDE_DRIVE")), bid)

	# ---- R8 roof (family + pitch + eave), with gable material ----
	var roof_fam := int(_ROOF_FAM.get(String(roof.get("material", "asphalt_shingle")), 10))
	if "METAL_ROOF_RETROFIT" in mods:
		roof_fam = 11   # standing seam metal
	var roof_col := _roof_color(roof, roof_fam, bid)
	verts += _roof(st, ring, floors_top, String(roof.get("family", "SIDE_GABLE")),
		String(roof.get("pitch", "MEDIUM")), String(roof.get("eave", "NORMAL")),
		roof_col, roof_fam, gable_m, ent_edge)

	# ---- details: chimney / dormer / stone accent (only what reads at iso) ----
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
				var w0 := center - dir * hw + nrm2 * 0.04
				var w1 := center + dir * hw + nrm2 * 0.04
				var top := wy + wh * hscale
				v += _quad(st, Vector3(w0.x, wy, w0.y), Vector3(w1.x, wy, w1.y),
					Vector3(w1.x, top, w1.y), Vector3(w0.x, top, w0.y), nrm, WIN_COL)
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
		bid: int) -> int:
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
	var depth := clampf(float(porch.get("depth_m", 2.0)), 0.6, 3.2)
	var wfrac := clampf(float(porch.get("width_fraction", 0.5)), 0.1, 1.0)
	var support := String(porch.get("support", "SIMPLE_POST"))
	var pw := length * wfrac
	# porch centre: full/near-full width centres on the edge; partial hugs the door.
	var t_center: float = 0.5 if wfrac > 0.7 else ent_t
	t_center = clampf(t_center, pw * 0.5 / length, 1.0 - pw * 0.5 / length)
	var dc := a.lerp(c, t_center)
	var dc3 := Vector3(dc.x, 0.0, dc.y)
	var v := 0
	# platform at finished-floor height (foundation raises the porch too)
	var plat := dc3 + nrm * (depth * 0.5) + Vector3(0.0, y0 * 0.5, 0.0)
	v += _box(st, plat + Vector3(0.0, 0.06, 0.0), along, nrm, pw * 0.5, depth * 0.5,
		maxf(0.08, y0 * 0.5 + 0.06), _enc(Color(0.70, 0.68, 0.64), _NEUTRAL))
	# roof over the porch (skip for RECESSED — that reads as cut into the mass)
	var roof_h := 2.6 + y0
	if family != "RECESSED":
		var proj := 0.28 if family == "PROJECTING_GABLE" else 0.18
		v += _box(st, dc3 + nrm * (depth * 0.5) + Vector3(0.0, roof_h, 0.0), along, nrm,
			pw * 0.5 + proj, depth * 0.5 + proj, 0.09, _enc(Color(0.34, 0.30, 0.27), _NEUTRAL))
	# supports
	v += _porch_posts(st, dc3, along, nrm, pw, depth, roof_h, support, y0)
	# steps up to the finished floor when raised
	if y0 > 0.25:
		v += _steps(st, dc3, along, nrm, minf(pw, ent_w + 1.4), depth, y0)
	return v


static func _porch_posts(st: SurfaceTool, dc3: Vector3, along: Vector3, nrm: Vector3,
		pw: float, depth: float, roof_h: float, support: String, y0: float) -> int:
	var col := _enc(TRIM_COL, _NEUTRAL)
	var pier_col := _enc(Color(0.56, 0.34, 0.28), _FAM_BRICK)
	var v := 0
	var half := pw * 0.5 - 0.15
	var post_h := (roof_h - y0) * 0.5
	for s in [-1.0, 1.0]:
		var sf := float(s)
		var base := dc3 + along * (sf * half) + nrm * (depth - 0.2) + Vector3(0.0, y0, 0.0)
		match support:
			"TAPERED_POST_BRICK_PIER":
				v += _box(st, base + Vector3(0.0, 0.5, 0.0), along, nrm, 0.16, 0.16, 0.5, pier_col)
				v += _box(st, base + Vector3(0.0, 1.0 + post_h * 0.5, 0.0), along, nrm,
					0.09, 0.09, post_h, col)
			"PAIRED_POST":
				for o in [-0.12, 0.12]:
					v += _box(st, base + along * float(o) + Vector3(0.0, post_h, 0.0), along, nrm,
						0.06, 0.06, post_h, col)
			"CLASSICAL_SIMPLE":
				v += _box(st, base + Vector3(0.0, post_h, 0.0), along, nrm, 0.11, 0.11, post_h, col)
			"MCM_THIN":
				v += _box(st, base + Vector3(0.0, post_h, 0.0), along, nrm, 0.05, 0.05, post_h, col)
			"MCM_SLANTED":
				# a thin post nudged outward at the top reads as a slanted MCM support
				v += _box(st, base + nrm * 0.12 + Vector3(0.0, post_h, 0.0), along, nrm,
					0.05, 0.05, post_h, col)
			"TAPERED_POST":
				v += _box(st, base + Vector3(0.0, post_h, 0.0), along, nrm, 0.12, 0.12, post_h, col)
			"NONE":
				pass
			_:
				v += _box(st, base + Vector3(0.0, post_h, 0.0), along, nrm, 0.09, 0.09, post_h, col)
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
	var ctr: Vector2 = ob["ctr"] + dir * ob["cu"] + perp * ob["cw"]
	var hu: float = ob["half_u"]
	var hw: float = ob["half_w"]
	var eo: float = _EAVE_OUT.get(eave, 0.45)
	var pr: float = _PITCH_RISE.get(pitch, 0.5)
	var short := minf(hu, hw)
	var rise := clampf(short * pr * 2.0, 0.4, 6.5)
	var v := 0
	var gcol := _enc(gable_m["col"], gable_m["fam"])
	var eu := hu + eo
	var ew := hw + eo

	# corners in world space of the eave rectangle
	var d3 := Vector3(dir.x, 0.0, dir.y)
	var p3 := Vector3(perp.x, 0.0, perp.y)
	var base := Vector3(ctr.x, h, ctr.y)

	match family:
		"FLAT":
			v += _flat_cap(st, ring, h, roof_col)
		"SHED_COMPOSITE":
			# single slope from one long side up to the other.
			var lo := base - p3 * ew
			var hi := base + p3 * ew + Vector3(0.0, rise, 0.0)
			var c0 := lo - d3 * eu
			var c1 := lo + d3 * eu
			var c2 := hi + d3 * eu
			var c3 := hi - d3 * eu
			v += _quad(st, c0, c1, c2, c3, Vector3.UP, roof_col)
			v += _flat_cap(st, ring, h, roof_col.darkened(0.1))
		"LOW_HIP", "HIP", "CROSS_HIP", "COMPLEX_HIP_GABLE":
			v += _hip(st, base, d3, p3, eu, ew, rise, roof_col)
		"FRONT_GABLE":
			v += _gable(st, base, d3, p3, eu, ew, rise, roof_col, gcol, true)
		_:   # SIDE_GABLE / CROSS_GABLE / LOW_GABLE
			v += _gable(st, base, d3, p3, eu, ew, rise, roof_col, gcol, false)
	return v


## Gable roof: ridge runs along the long axis (side gable) or short axis
## (front_gable). Two slope planes + two triangular gable ends in gable material.
static func _gable(st: SurfaceTool, base: Vector3, d3: Vector3, p3: Vector3,
		eu: float, ew: float, rise: float, roof_col: Color, gable_col: Color,
		front: bool) -> int:
	var v := 0
	var ridge_axis := d3 if not front else p3
	var slope_axis := p3 if not front else d3
	var rl: float = eu if not front else ew        # half-length along ridge
	var sw: float = ew if not front else eu         # half-width of slope
	var up := Vector3(0.0, rise, 0.0)
	var ridge0 := base - ridge_axis * rl + up
	var ridge1 := base + ridge_axis * rl + up
	var eaveA0 := base - ridge_axis * rl - slope_axis * sw
	var eaveA1 := base + ridge_axis * rl - slope_axis * sw
	var eaveB0 := base - ridge_axis * rl + slope_axis * sw
	var eaveB1 := base + ridge_axis * rl + slope_axis * sw
	# two slope planes
	v += _quad(st, eaveA0, eaveA1, ridge1, ridge0, Vector3.UP, roof_col)
	v += _quad(st, eaveB1, eaveB0, ridge0, ridge1, Vector3.UP, roof_col)
	# two gable-end triangles (gable material)
	v += _tri(st, eaveA0, ridge0, eaveB0, -ridge_axis, gable_col)
	v += _tri(st, eaveA1, eaveB1, ridge1, ridge_axis, gable_col)
	return v


static func _hip(st: SurfaceTool, base: Vector3, d3: Vector3, p3: Vector3,
		eu: float, ew: float, rise: float, roof_col: Color) -> int:
	var v := 0
	var up := Vector3(0.0, rise, 0.0)
	var inset := minf(eu, ew) * 0.5
	var ridge0 := base - d3 * (eu - inset) + up
	var ridge1 := base + d3 * (eu - inset) + up
	var e00 := base - d3 * eu - p3 * ew
	var e01 := base - d3 * eu + p3 * ew
	var e10 := base + d3 * eu - p3 * ew
	var e11 := base + d3 * eu + p3 * ew
	# four hip faces
	v += _quad(st, e00, e10, ridge1, ridge0, Vector3.UP, roof_col)   # -p side
	v += _quad(st, e11, e01, ridge0, ridge1, Vector3.UP, roof_col)   # +p side
	v += _tri(st, e00, ridge0, e01, -d3, roof_col)                   # -u hip end
	v += _tri(st, e10, e11, ridge1, d3, roof_col)                    # +u hip end
	return v


static func _flat_cap(st: SurfaceTool, ring: PackedVector2Array, h: float,
		roof_col: Color) -> int:
	var tris := Geometry2D.triangulate_polygon(ring)
	if tris.is_empty():
		return 0
	st.set_color(roof_col)
	var v := 0
	for i in range(0, tris.size(), 3):
		for k in [tris[i], tris[i + 1], tris[i + 2]]:
			st.set_normal(Vector3.UP)
			st.add_vertex(Vector3(ring[k].x, h + 0.05, ring[k].y))
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
