shader_type spatial;
render_mode cull_disabled, diffuse_burley, specular_schlick_ggx;

// P0-A2 — restrained low-poly building surface. COLOR.rgb is the facade/roof tint;
// COLOR.a carries a material-family id (see world_materials.gd). Surface coords are
// derived from world position + face normal so patterns keep the right scale and
// direction on rotated buildings (walls: U along wall, V = height; roofs: world XZ).
// Patterns are deliberately broad and derivative-antialiased so they read at the
// close camera and dissolve gracefully — never moiré — at the wide camera.

varying vec3 v_world;
varying vec3 v_wnorm;
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

// A soft dark line every `period` metres along `x`, `line_w` metres wide,
// antialiased by the on-screen derivative so it never aliases when small.
float grooves(float x, float period, float line_w) {
	float t = abs(fract(x / period - 0.5) - 0.5) * 2.0 * period; // metres from nearest line
	float aa = fwidth(x) + 0.0008;
	return smoothstep(line_w + aa, line_w - aa, t); // 1 on the line, 0 on the field
}

void vertex() {
	v_world = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	v_wnorm = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
	v_fam = COLOR.a;
}

void fragment() {
	int fam = int(floor(v_fam * 64.0));
	vec3 tint = COLOR.rgb;
	vec3 n = normalize(v_wnorm);
	bool horiz = abs(n.y) > 0.6;

	// Meter-scaled local surface coordinates.
	vec2 uv;
	if (horiz) {
		uv = v_world.xz;
	} else {
		vec2 tang = normalize(vec2(-n.z, n.x)); // along the wall, horizontal
		uv = vec2(dot(v_world.xz, tang), v_world.y);
	}

	// Per-building macro value variation (coarse cells → a whole wall shares a tone,
	// neighbours differ) so same-material buildings are not identical.
	float macro = vnoise(floor(v_world.xz / 7.0) + 0.5) - 0.5;

	vec3 albedo = tint;
	float rough = 0.9;
	float metallic = 0.0;
	float spec = 0.5;

	if (fam == 0) {                     // brick: courses + per-brick value break
		float courses = grooves(uv.y, 0.28, 0.03);
		float head = grooves(uv.x + floor(uv.y / 0.28) * 0.14, 0.24, 0.03);
		float mortar = max(courses, head);
		float brick = (hash21(floor(vec2(uv.x / 0.24 + floor(uv.y / 0.28) * 0.5, uv.y / 0.28))) - 0.5) * 0.16;
		albedo *= 1.0 + brick + macro * 0.12;
		albedo = mix(albedo, albedo * 0.58 + vec3(0.06, 0.055, 0.05), mortar);
		rough = 0.95;
	} else if (fam == 1) {              // painted brick: weaker courses
		float mortar = grooves(uv.y, 0.30, 0.02);
		albedo *= 1.0 + macro * 0.07;
		albedo = mix(albedo, albedo * 0.8, mortar * 0.7);
		rough = 0.85;
	} else if (fam == 2) {              // siding: horizontal lap bands
		float lap = grooves(uv.y, 0.22, 0.03);
		float shade = sin(uv.y / 0.22 * 6.2831) * 0.05;
		albedo *= 1.0 + shade + macro * 0.06;
		albedo = mix(albedo, albedo * 0.8, lap);
		rough = 0.8;
	} else if (fam == 3) {              // stucco: soft coarse mottle
		float m = vnoise(uv * 3.5) * 0.10 + vnoise(uv * 12.0) * 0.04;
		albedo *= 0.96 + m + macro * 0.06;
		rough = 0.95;
	} else if (fam == 4) {              // concrete: large low-frequency mottling
		float m = vnoise(uv * 0.9) * 0.12 + vnoise(uv * 4.0) * 0.03;
		albedo *= 0.94 + m + macro * 0.08;
		rough = 0.9;
	} else if (fam == 5) {              // stone: larger irregular value regions
		float regions = vnoise(uv * 0.7) * 0.16 + vnoise(uv * 2.3) * 0.06;
		float joint = max(grooves(uv.y, 0.55, 0.02), grooves(uv.x, 0.9, 0.02));
		albedo *= 0.92 + regions + macro * 0.06;
		albedo = mix(albedo, albedo * 0.8, joint * 0.5);
		rough = 0.92;
	} else if (fam == 6) {              // metal panel: vertical + horizontal seams, spec
		float seams = max(grooves(uv.x, 0.9, 0.025), grooves(uv.y, 1.8, 0.02));
		albedo *= 1.0 + macro * 0.05;
		albedo = mix(albedo, albedo * 0.72, seams);
		rough = 0.45;
		metallic = 0.25;
		spec = 0.6;
	} else if (fam == 7) {              // wood: directional broad grain
		float grain = sin(uv.x * 5.0 + vnoise(uv * vec2(0.4, 6.0)) * 6.0) * 0.05;
		albedo *= 1.0 + grain + macro * 0.06;
		rough = 0.8;
	} else if (fam == 8) {              // glass curtain: dark cool, mullion grid, hot spec
		vec3 cool = mix(tint, vec3(0.10, 0.14, 0.20), 0.5);
		float mull = max(grooves(uv.x, 1.4, 0.03), grooves(uv.y, 1.2, 0.03));
		float sheen = vnoise(uv * vec2(0.2, 0.6)) * 0.12;
		albedo = cool * (1.0 + sheen);
		albedo = mix(albedo, albedo * 0.5, mull);
		rough = 0.12;
		metallic = 0.1;
		spec = 0.9;
	} else if (fam == 9) {              // painted masonry: near flat, slight variation
		albedo *= 0.98 + macro * 0.05 + vnoise(uv * 2.0) * 0.03;
		rough = 0.85;
	} else if (fam == 10) {             // asphalt shingle roof: horizontal courses
		float courses = grooves(uv.y, 0.34, 0.04);
		float tab = grooves(uv.x + floor(uv.y / 0.34) * 0.3, 0.5, 0.03);
		albedo *= 0.96 + macro * 0.06 + (hash21(floor(uv / 0.34)) - 0.5) * 0.10;
		albedo = mix(albedo, albedo * 0.74, max(courses, tab * 0.7));
		rough = 0.95;
	} else if (fam == 11) {             // standing-seam metal: strong directional seams
		float seams = grooves(uv.x, 0.45, 0.025);
		albedo *= 1.0 + macro * 0.04;
		albedo = mix(albedo, albedo * 1.15, grooves(uv.x, 0.45, 0.01)); // raised highlight
		albedo = mix(albedo, albedo * 0.8, seams);
		rough = 0.4;
		metallic = 0.3;
		spec = 0.65;
	} else if (fam == 12) {             // flat membrane: very flat, faint patch seams
		float patch = vnoise(uv * 0.5) * 0.06;
		float seam = grooves(uv.x, 2.0, 0.02) + grooves(uv.y, 2.0, 0.02);
		albedo *= 0.97 + patch;
		albedo = mix(albedo, albedo * 0.95, clamp(seam, 0.0, 1.0) * 0.4);
		rough = 0.97;
	} else if (fam == 13) {             // tile roof: broad repeating ridge rhythm
		float ridge = sin(uv.x / 0.3 * 6.2831) * 0.5 + 0.5;
		float rows = grooves(uv.y, 0.42, 0.03);
		albedo *= 0.9 + ridge * 0.16 + macro * 0.05;
		albedo = mix(albedo, albedo * 0.82, rows);
		rough = 0.85;
	} else if (fam == 14) {             // roof generic: flat with slight break
		albedo *= 0.97 + macro * 0.05;
		rough = 0.9;
	} else {                            // neutral detail (windows/doors/trim/HVAC)
		albedo = tint;
		rough = 0.8;
	}

	ALBEDO = clamp(albedo, vec3(0.0), vec3(1.0));
	ROUGHNESS = rough;
	METALLIC = metallic;
	SPECULAR = spec;
}
