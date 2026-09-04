shader_type spatial;
render_mode cull_back, diffuse_burley, specular_schlick_ggx;

// CitizenMaterial — the ONE shared NPC appearance material (H2).
//
// A single ShaderMaterial paints every humanoid region from a curated palette so
// we never allocate a Material per citizen and never a surface-per-region blow-up
// (H12). Per-vertex UV2 selects the region and carries the walk-swing lever; the
// per-instance colour + custom data carry that citizen's deterministic palette
// (from CitizenVisualIdentity). The exact same instance data therefore produces
// the exact same look in the batched crowd and on a near avatar (H4/H15).
//
//   UV2.x            material region id (0..6, see CitizenMeshes.R_*)
//   UV2.y            signed limb lever for the GPU gait (0 on torso/head)
//   INSTANCE_COLOR   rgb = top clothing colour; a = gait amplitude (0/0.5/1)
//   INSTANCE_CUSTOM  r = skin idx, g = hair idx, b = bottom idx,
//                    a = shoe idx<<1 | sleeve bit   (all quantised (i+0.5)/32)

// Palettes (filled from CitizenVisualIdentity so GDScript + shader agree).
uniform vec4 skin_palette[16];
uniform vec4 hair_palette[16];
uniform vec4 bottom_palette[16];
uniform vec4 shoe_palette[16];

uniform float anim_time = 0.0;        // seconds; driven by the renderer
uniform float swing_gain = 0.35;      // fore-aft limb throw (metres at the tip)
uniform float bob_gain = 0.035;       // vertical bob (metres)

// Debug disease overlay (H7): OFF by default so production NPCs keep real clothes.
uniform float debug_tint : hint_range(0.0, 1.0) = 0.0;
uniform vec4 debug_color : source_color = vec4(0.9, 0.25, 0.2, 1.0);

const float PACK_DEN = 32.0;

varying flat vec4 v_custom;
varying flat vec4 v_color;
varying float v_region;

int unpack_idx(float v) {
	return int(clamp(v * PACK_DEN, 0.0, 15.0));
}

void vertex() {
	v_custom = INSTANCE_CUSTOM;
	v_color = COLOR;                        // MultiMesh per-instance colour
	v_region = UV2.x;

	// --- procedural walk: a cheap pendulum swing entirely on the GPU (H5) ----
	float amp = COLOR.a * 1.6;              // 0 idle, 0.5 walk -> 0.8, 1.0 run -> 1.6
	if (amp > 0.001) {
		// Per-instance phase from world position so the crowd never marches in
		// lock-step (presentation only; never fed back to the sim).
		vec3 wp = MODEL_MATRIX[3].xyz;
		float phase = fract((wp.x + wp.z) * 0.37) * 6.2831853;
		float t = anim_time * (4.0 + amp * 3.0) + phase;
		float sw = sin(t);
		VERTEX.z += UV2.y * sw * swing_gain * amp;   // signed lever -> opposed limbs
		VERTEX.y += abs(sw) * bob_gain * amp;        // slight bob
	}
}

void fragment() {
	int region = int(v_region + 0.5);
	vec3 albedo;
	if (region == 0) {                       // skin
		albedo = skin_palette[unpack_idx(v_custom.r)].rgb;
	} else if (region == 1) {                // hair
		albedo = hair_palette[unpack_idx(v_custom.g)].rgb;
	} else if (region == 2) {                // top
		albedo = v_color.rgb;
	} else if (region == 3) {                // bottom
		albedo = bottom_palette[unpack_idx(v_custom.b)].rgb;
	} else if (region == 4) {                // shoes  (shoe idx in high bits)
		int packed = int(clamp(v_custom.a * PACK_DEN, 0.0, 31.0));
		albedo = shoe_palette[clamp(packed >> 1, 0, 15)].rgb;
	} else if (region == 6) {                // forearm: sleeve bit picks skin/top
		int packed = int(clamp(v_custom.a * PACK_DEN, 0.0, 31.0));
		int sleeve = packed & 1;
		albedo = (sleeve == 1) ? v_color.rgb : skin_palette[unpack_idx(v_custom.r)].rgb;
	} else {                                 // accent -> a shade of the top colour
		albedo = v_color.rgb * 0.72;
	}

	albedo = mix(albedo, debug_color.rgb, debug_tint * debug_color.a);
	ALBEDO = albedo;
	ROUGHNESS = 0.92;
	METALLIC = 0.0;
	SPECULAR = 0.15;
}
