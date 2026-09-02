shader_type spatial;
render_mode cull_disabled, diffuse_burley;

// P0-A4 — semantic ground surface. COLOR.rgb is the land-cover tint; COLOR.a
// carries the surface-class id (ROAD 0, SIDEWALK 1, PARKING 2, OTHER_IMPERVIOUS 3,
// MAINTAINED_GRASS 4, ROUGH_VEGETATION 5, TREE_CANOPY 6, BARE_GROUND 7, WATER 8).
// Coordinates are world XZ in metres — the ground is horizontal, so no rotation
// handling is needed. Patterns are broad + derivative-antialiased.

varying vec3 v_world;
varying float v_fam;

float hash21(vec2 p) {
	p = fract(p * vec2(123.34, 345.45));
	p += dot(p, p + 34.345);
	return fract(p.x * p.y);
}

float vnoise(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	f = f * f * (3.0 - 2.0 * f);
	float a = hash21(i);
	float b = hash21(i + vec2(1.0, 0.0));
	float c = hash21(i + vec2(0.0, 1.0));
	float d = hash21(i + vec2(1.0, 1.0));
	return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float joints(vec2 p, float period, float line_w) {
	vec2 t = abs(fract(p / period - 0.5) - 0.5) * 2.0 * period;
	vec2 aa = fwidth(p) + 0.001;
	float gx = smoothstep(line_w + aa.x, line_w - aa.x, t.x);
	float gy = smoothstep(line_w + aa.y, line_w - aa.y, t.y);
	return max(gx, gy);
}

void vertex() {
	v_world = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	v_fam = COLOR.a;
}

void fragment() {
	int fam = int(floor(v_fam * 64.0));
	vec2 uv = v_world.xz;
	vec3 albedo = COLOR.rgb;
	float rough = 1.0;

	if (fam == 0) {                     // road: dark asphalt, subtle aggregate
		albedo *= 0.95 + vnoise(uv * 2.5) * 0.06 + (hash21(floor(uv * 3.0)) - 0.5) * 0.03;
		rough = 0.92;
	} else if (fam == 1) {              // sidewalk: concrete + expansion joints (~1.5 m)
		float j = joints(uv, 1.5, 0.03);
		albedo *= 0.97 + vnoise(uv * 3.0) * 0.05;
		albedo = mix(albedo, albedo * 0.82, j);
		rough = 0.95;
	} else if (fam == 2) {              // parking: lighter, weathered asphalt
		albedo *= 0.97 + vnoise(uv * 1.6) * 0.08 + (hash21(floor(uv * 2.5)) - 0.5) * 0.04;
		rough = 0.9;
	} else if (fam == 3) {              // other impervious: generic concrete hardscape
		float j = joints(uv, 3.0, 0.03);
		albedo *= 0.97 + vnoise(uv * 2.0) * 0.05;
		albedo = mix(albedo, albedo * 0.88, j * 0.5);
		rough = 0.95;
	} else if (fam == 4) {              // maintained grass: soft low-frequency green
		float g = vnoise(uv * 1.1) * 0.10 + vnoise(uv * 5.0) * 0.04;
		albedo *= 0.93 + g;
		rough = 1.0;
	} else if (fam == 5) {              // rough vegetation: browner, less uniform
		float g = vnoise(uv * 0.9) * 0.14 + vnoise(uv * 4.5) * 0.06;
		albedo = mix(albedo, albedo * vec3(1.06, 0.98, 0.82), vnoise(uv * 0.6));
		albedo *= 0.9 + g;
		rough = 1.0;
	} else if (fam == 6) {              // tree canopy ground: dark green mottle
		albedo *= 0.88 + vnoise(uv * 1.4) * 0.14;
		rough = 1.0;
	} else if (fam == 7) {              // bare ground: tan variation
		albedo *= 0.9 + vnoise(uv * 1.8) * 0.12;
		rough = 1.0;
	} else if (fam == 8) {              // water: flat, faint ripple value
		albedo = mix(albedo, albedo * 1.1, vnoise(uv * 0.8) * 0.5);
		rough = 0.25;
	} else {
		albedo *= 0.97 + vnoise(uv * 2.0) * 0.05;
	}

	ALBEDO = clamp(albedo, vec3(0.0), vec3(1.0));
	ROUGHNESS = rough;
}
