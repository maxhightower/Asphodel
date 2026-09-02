extends RefCounted
class_name WorldMaterials

## P0-A1 — one shared semantic material system for the exterior world.
##
## The renderer must not mint a material per building (that would destroy the
## MultiMesh/one-mesh-per-chunk batching the city stream depends on). Instead a
## compact *material-family ID* rides in each vertex's COLOR.a, while COLOR.rgb
## keeps the existing facade/roof/ground tint. A single ShaderMaterial per surface
## domain (buildings, ground) reads that ID and applies a restrained low-poly
## procedural treatment — brick courses, siding bands, metal seams, stylized
## opaque glass, asphalt, concrete joints — so different physical materials stop
## collapsing into differently coloured matte clay, all without extra draw calls.
##
## Surface coordinates are derived in-shader from world position + face normal
## (walls: distance-along-wall × height; horizontal: world XZ), so a rotated house
## still has its siding running horizontally and its seams vertical — no per-vertex
## UV bookkeeping in the geometry emitters.
##
## Encoding: COLOR.a = (family_id + 0.5) / 64.0  (up to 64 families; shader floors).

const FAM_SCALE := 64.0

# ---- building material families (facade 0–9, roof 10–14, neutral detail 15) ----
const B_BRICK := 0
const B_PAINTED_BRICK := 1
const B_SIDING := 2
const B_STUCCO := 3
const B_CONCRETE := 4
const B_STONE := 5
const B_METAL_PANEL := 6
const B_WOOD := 7
const B_GLASS_CURTAIN := 8
const B_PAINTED_MASONRY := 9
const B_ROOF_ASPHALT := 10
const B_ROOF_STANDING_SEAM := 11
const B_ROOF_MEMBRANE := 12
const B_ROOF_TILE := 13
const B_ROOF_GENERIC := 14
const B_NEUTRAL := 15          # windows, doors, trim, HVAC, porches — stays flat matte

const _FACADE_FAMILY := {
	"brick": B_BRICK, "painted_brick": B_PAINTED_BRICK, "siding": B_SIDING,
	"stucco": B_STUCCO, "concrete": B_CONCRETE, "stone": B_STONE,
	"metal_panel": B_METAL_PANEL, "wood": B_WOOD, "glass_curtain": B_GLASS_CURTAIN,
	"painted_masonry": B_PAINTED_MASONRY,
}
const _ROOF_FAMILY := {
	"asphalt_shingle": B_ROOF_ASPHALT, "standing_seam_metal": B_ROOF_STANDING_SEAM,
	"flat_membrane": B_ROOF_MEMBRANE, "tile": B_ROOF_TILE, "roof_generic": B_ROOF_GENERIC,
}

# ---- ground material families: identical to the surface-class ids (S_ROAD … ) ---
# ROAD 0, SIDEWALK 1, PARKING 2, OTHER_IMPERVIOUS 3, MAINTAINED_GRASS 4,
# ROUGH_VEGETATION 5, TREE_CANOPY 6, BARE_GROUND 7, WATER 8, BUILDING 9.

static var _building_mat: ShaderMaterial = null
static var _ground_mat: ShaderMaterial = null


static func facade_family(name: String) -> int:
	return int(_FACADE_FAMILY.get(name, B_PAINTED_MASONRY))


static func roof_family(name: String) -> int:
	return int(_ROOF_FAMILY.get(name, B_ROOF_GENERIC))


## Fold a family id into a base colour's alpha for the shader to read back.
static func encode(base: Color, family: int) -> Color:
	return Color(base.r, base.g, base.b, (float(family) + 0.5) / FAM_SCALE)


static func building_material() -> ShaderMaterial:
	if _building_mat == null:
		_building_mat = _load("res://shaders/building_surface.gdshader")
	return _building_mat


static func ground_material() -> ShaderMaterial:
	if _ground_mat == null:
		_ground_mat = _load("res://shaders/ground_surface.gdshader")
	return _ground_mat


static func _load(path: String) -> ShaderMaterial:
	var m := ShaderMaterial.new()
	var sh: Shader = load(path)
	m.shader = sh
	return m
