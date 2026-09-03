extends RefCounted
class_name CitizenVisualIdentity

## CitizenVisualIdentity — the ONE authority for what a citizen looks like (H0).
##
## Every NPC render path (outdoor crowd, interior occupants, near avatars, the
## gallery/tests) derives appearance from here and NOWHERE else, so a citizen
## looks identical:
##   * outdoors and indoors,
##   * after zone demotion / re-promotion,
##   * after leaving and returning,
##   * after save/load,
##   * after roster promotion.
##
## Appearance is a PURE, DETERMINISTIC function of `citizen_id` (via a stable
## splitmix `visual_seed`). It must NEVER depend on array slot, zone, frame
## number, spawn order, node id, `randomize()`, or the wall clock, and it NEVER
## consumes simulation RNG (the epidemic curve is untouched — H16). This mirrors
## `asphodel.npc.visual_seed` so Python and Godot agree, but appearance itself
## lives entirely on the presentation side (H17).
##
## Anonymous statistical fill (`citizen_id == -1`) has no persisted identity; the
## renderer derives its look from a stable per-sample key instead, and it must
## never masquerade as a named person.

# --- deterministic seed (mirror of asphodel.npc.visual_seed) -----------------

static func visual_seed(cid: int) -> int:
	if cid < 0:
		return 0
	var x := (cid * 0x9E3779B1 + 0x7F4A7C15) & 0xFFFFFFFF
	x ^= (x >> 16)
	x = (x * 0x85EBCA6B) & 0xFFFFFFFF
	x ^= (x >> 13)
	return x & 0x7FFFFFFF

## A salted re-mix of a seed, so several independent appearance fields can be
## drawn from one citizen id without correlation and without any RNG.
static func _mix(seed: int, salt: int) -> int:
	var x := (seed + salt * 0x9E3779B1 + 0x7F4A7C15) & 0xFFFFFFFF
	x ^= (x >> 15)
	x = (x * 0x85EBCA6B) & 0xFFFFFFFF
	x ^= (x >> 13)
	x = (x * 0xC2B2AE35) & 0xFFFFFFFF
	x ^= (x >> 16)
	return x & 0x7FFFFFFF


# --- geometry variant counts (bounded, enumerable) ---------------------------
# Body proportion templates (H1). Order fixed — indices are identity.
const BODY_COMPACT := 0
const BODY_AVERAGE_A := 1
const BODY_AVERAGE_B := 2
const BODY_TALL_SLENDER := 3
const BODY_BROAD := 4
const BODY_SHORT_STOCKY := 5
const N_BODY := 6

# Lower-body clothing silhouette (the one true geometry axis for clothing; sleeve
# length and coat are expressed as colour regions, not extra meshes — H3).
const LOWER_TROUSERS := 0
const LOWER_SKIRT := 1
const N_LOWER := 2

# Hair silhouette families (H3). Kept extremely low-poly; index is identity.
const HAIR_BALD := 0
const HAIR_CROP := 1
const HAIR_SHORT := 2
const HAIR_MEDIUM := 3
const HAIR_BUN := 4
const HAIR_LONG := 5
const N_HAIR := 6


# --- deterministic colour palettes (shared with the shader) ------------------
# Skin: a curated stylized range, broad but not garish.
const SKIN_PALETTE: Array[Color] = [
	Color(0.96, 0.80, 0.69), Color(0.91, 0.73, 0.60), Color(0.85, 0.66, 0.52),
	Color(0.78, 0.58, 0.44), Color(0.68, 0.49, 0.36), Color(0.57, 0.40, 0.29),
	Color(0.46, 0.32, 0.23), Color(0.36, 0.25, 0.18), Color(0.90, 0.75, 0.66),
	Color(0.63, 0.45, 0.33),
]

# Hair: natural tones only — no procedural rainbow (H2).
const HAIR_PALETTE: Array[Color] = [
	Color(0.09, 0.08, 0.08), Color(0.20, 0.13, 0.09), Color(0.33, 0.22, 0.13),
	Color(0.48, 0.34, 0.20), Color(0.79, 0.66, 0.38), Color(0.55, 0.24, 0.13),
	Color(0.62, 0.62, 0.64), Color(0.86, 0.86, 0.87),
]

# Clothing: restrained, Asphodel-appropriate, with a few brighter accents used
# sparingly. Used for both tops and bottoms.
const CLOTHING_PALETTE: Array[Color] = [
	Color(0.22, 0.23, 0.26), Color(0.16, 0.21, 0.34), Color(0.28, 0.40, 0.58),
	Color(0.33, 0.44, 0.31), Color(0.63, 0.35, 0.22), Color(0.42, 0.31, 0.22),
	Color(0.78, 0.72, 0.58), Color(0.86, 0.86, 0.82), Color(0.62, 0.26, 0.24),
	Color(0.79, 0.64, 0.26), Color(0.24, 0.48, 0.49), Color(0.47, 0.40, 0.60),
]

# Shoes: mostly dark/neutral.
const SHOE_PALETTE: Array[Color] = [
	Color(0.10, 0.10, 0.11), Color(0.30, 0.22, 0.16), Color(0.35, 0.36, 0.38),
	Color(0.80, 0.80, 0.78), Color(0.52, 0.44, 0.34),
]


# --- appearance descriptor (H15/H17) -----------------------------------------
## A compact, presentation-only appearance record. Equality of two of these is
## the identity gate the tests assert. Colours that live in a shader uniform
## palette are stored as indices (so the shader and this agree); the top colour
## is stored directly because it is fed straight to INSTANCE_COLOR.
# Appearance is a pure function of the seed, so it is memoised: named citizens
# recur in every snapshot and recomputing 10 hash mixes + a dict each time is the
# dominant render-apply cost. The cache is keyed by seed and shared by every
# render path (crowd, avatar, interior). Read-only for callers.
static var _APP_CACHE: Dictionary = {}

static func appearance(cid: int) -> Dictionary:
	if cid < 0:
		# Anonymous fill has no personal identity; callers pass a stable sample
		# key as `cid` only to keep a given fill dot visually steady, never to
		# imply a persisted person.
		return appearance_from_seed(0)
	return appearance_from_seed(visual_seed(cid))


## Appearance from a raw seed (also used for anonymous fill keyed by sample slot).
static func appearance_from_seed(seed: int) -> Dictionary:
	var s := seed & 0x7FFFFFFF
	var cached: Variant = _APP_CACHE.get(s)
	if cached != null:
		return cached
	var a := _appearance_from_seed(s)
	_APP_CACHE[s] = a
	return a


static func _appearance_from_seed(seed: int) -> Dictionary:
	var body := _mix(seed, 1) % N_BODY
	var lower := _mix(seed, 2) % N_LOWER
	var hair := _mix(seed, 3) % N_HAIR
	var sleeve := _mix(seed, 4) % 2                 # 0 short, 1 long (colour only)
	var coat := 1 if (_mix(seed, 5) % 5 == 0) else 0  # ~20% wear an outer accent
	var skin := _mix(seed, 6) % SKIN_PALETTE.size()
	var hair_color := _mix(seed, 7) % HAIR_PALETTE.size()
	var top := _mix(seed, 8) % CLOTHING_PALETTE.size()
	var bottom := _mix(seed, 9) % CLOTHING_PALETTE.size()
	var shoe := _mix(seed, 10) % SHOE_PALETTE.size()
	# A bald head has no hair colour bearing; keep it defined for stable equality.
	return {
		"body": body,
		"stature": body_stature(body),
		"lower": lower,
		"hair": hair,
		"sleeve": sleeve,
		"coat": coat,
		"skin": skin,
		"hair_color": hair_color,
		"top": top,
		"bottom": bottom,
		"shoe": shoe,
	}


# --- body proportion table (H1) ----------------------------------------------
## Neutral proportion templates. Do NOT infer personality/gameplay stats from
## these; they exist purely to vary silhouettes. Height "h", "torso" and "leg"
## are lengths (metres); "shoulder", "hip", "depth" and "head" are HALF-extents
## (so full shoulder span ~ 2*shoulder). Height is roughly 1.65–1.90 m across
## templates. Named status does NOT change stature.
const BODY_TABLE := {
	BODY_COMPACT:      {"h": 1.66, "shoulder": 0.20, "torso": 0.48, "hip": 0.15, "leg": 0.78, "depth": 0.12, "head": 0.115},
	BODY_AVERAGE_A:    {"h": 1.74, "shoulder": 0.21, "torso": 0.50, "hip": 0.155, "leg": 0.84, "depth": 0.12, "head": 0.115},
	BODY_AVERAGE_B:    {"h": 1.78, "shoulder": 0.225, "torso": 0.52, "hip": 0.16, "leg": 0.86, "depth": 0.13, "head": 0.12},
	BODY_TALL_SLENDER: {"h": 1.90, "shoulder": 0.21, "torso": 0.54, "hip": 0.145, "leg": 0.92, "depth": 0.115, "head": 0.115},
	BODY_BROAD:        {"h": 1.80, "shoulder": 0.26, "torso": 0.52, "hip": 0.19, "leg": 0.84, "depth": 0.155, "head": 0.125},
	BODY_SHORT_STOCKY: {"h": 1.68, "shoulder": 0.245, "torso": 0.47, "hip": 0.18, "leg": 0.76, "depth": 0.15, "head": 0.12},
}

static func body_params(body: int) -> Dictionary:
	return BODY_TABLE.get(clampi(body, 0, N_BODY - 1), BODY_TABLE[BODY_AVERAGE_A])

static func body_stature(body: int) -> float:
	return float(body_params(body)["h"])


# --- colour accessors (used by tests + interior tint fallbacks) --------------
static func skin_color(a: Dictionary) -> Color:
	return SKIN_PALETTE[clampi(int(a.get("skin", 0)), 0, SKIN_PALETTE.size() - 1)]

static func hair_color(a: Dictionary) -> Color:
	return HAIR_PALETTE[clampi(int(a.get("hair_color", 0)), 0, HAIR_PALETTE.size() - 1)]

static func top_color(a: Dictionary) -> Color:
	return CLOTHING_PALETTE[clampi(int(a.get("top", 0)), 0, CLOTHING_PALETTE.size() - 1)]

static func bottom_color(a: Dictionary) -> Color:
	return CLOTHING_PALETTE[clampi(int(a.get("bottom", 0)), 0, CLOTHING_PALETTE.size() - 1)]

static func shoe_color(a: Dictionary) -> Color:
	return SHOE_PALETTE[clampi(int(a.get("shoe", 0)), 0, SHOE_PALETTE.size() - 1)]


# --- packing helpers for the shared shader (H2) ------------------------------
# The shader keeps the palettes above as uniform arrays; each instance carries
# palette INDICES packed into INSTANCE_CUSTOM and the top colour in INSTANCE_COLOR.
# Indices are quantised as (idx + 0.5) / PACK_DEN so the shader recovers them
# with int(v * PACK_DEN). PACK_DEN (32) comfortably exceeds every palette size.
const PACK_DEN := 32.0

static func pack_index(idx: int) -> float:
	return (float(idx) + 0.5) / PACK_DEN

## The vec4 written with MultiMesh.set_instance_custom_data / avatar instance
## custom. Channels: (skin, hair_color, bottom, shoe<<1 | sleeve). The sleeve bit
## rides in the shoe channel's low bit so the shader can paint the forearm
## (R_SLEEVE) as skin (short) or top (long) per instance — no extra geometry
## bucket and no extra channel. shoe*2+sleeve <= 9, well under PACK_DEN.
static func instance_custom(a: Dictionary) -> Color:
	var shoe_sleeve := int(a.get("shoe", 0)) * 2 + (int(a.get("sleeve", 0)) & 1)
	return Color(
		pack_index(int(a.get("skin", 0))),
		pack_index(int(a.get("hair_color", 0))),
		pack_index(int(a.get("bottom", 0))),
		pack_index(shoe_sleeve))


## The vec4 written to INSTANCE_COLOR: rgb = top clothing colour, a = gait
## amplitude (0 idle, 0.5 walk, 1.0 run). Kept here so every render path packs
## instance data identically.
static func instance_color(a: Dictionary, gait: float) -> Color:
	var c := top_color(a)
	c.a = clampf(gait, 0.0, 1.0)
	return c


# --- shared material (H2) ----------------------------------------------------
const SHADER_PATH := "res://shaders/citizen_material.gdshader"

static func _pad16(src) -> PackedColorArray:
	var out := PackedColorArray()
	for c in src:
		out.append(c)
	while out.size() < 16:
		out.append(Color(0, 0, 0, 1))
	return out

## One ShaderMaterial shared by every NPC render path, palettes preloaded. Never
## build one of these per citizen — build it once and reuse it.
static func build_material() -> ShaderMaterial:
	var mat := ShaderMaterial.new()
	mat.shader = load(SHADER_PATH)
	mat.set_shader_parameter("skin_palette", _pad16(SKIN_PALETTE))
	mat.set_shader_parameter("hair_palette", _pad16(HAIR_PALETTE))
	mat.set_shader_parameter("bottom_palette", _pad16(CLOTHING_PALETTE))
	mat.set_shader_parameter("shoe_palette", _pad16(SHOE_PALETTE))
	return mat
