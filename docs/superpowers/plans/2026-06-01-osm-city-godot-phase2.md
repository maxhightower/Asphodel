# OSM City — Godot Scene Generation (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. NOTE: there is no Godot CLI in this environment, so tasks are **verified in the Godot editor by the user**, not by an automated test runner. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make pressing **Play** in the Godot project load the checked-in sample bundle and render a low-poly 3D "block city" (density-scaled boxes + major roads + framed camera), so there is finally something runnable on screen.

**Architecture:** A small scripted Godot 4.4 scene. `bundle_loader.gd` parses the four bundle JSON files. `city_builder.gd` (attached to the scene root) reads the bundle and builds the world at runtime: zone blocks via a single `MultiMeshInstance3D` (per-instance transform + color, colored by zone density), roads as line strips, a ground plane, a directional light, and a camera framed to the city bbox. `project.godot` is pointed at this scene as `run/main_scene` so Play works.

**Tech Stack:** Godot 4.4 (Forward+), GDScript. No addons, no external assets (procedural `BoxMesh` blocks — Kenney `.glb` swap is a later polish). Reads the bundle produced by `asphodel/osm_city` (Phase 1).

**Spec:** `docs/superpowers/specs/2026-06-01-osm-city-scene-design.md` (Phase 2 portion)

---

## File Structure

| File | Responsibility |
|---|---|
| `godot/sample_bundle/` | Checked-in sample bundle (meta/zones/roads/timeline JSON) generated offline — the data Phase 2 renders. Already created. |
| `godot/scripts/bundle_loader.gd` | Pure loader: read the four JSON files from a dir into a typed `Dictionary`; validate; clear errors. |
| `godot/scripts/city_builder.gd` | Scene-root script: load bundle, build block MultiMesh (colored by density), roads, ground, light, camera. |
| `godot/CityScene.tscn` | Main scene: a `Node3D` root with `city_builder.gd` attached. |
| `godot/project.godot` (modify) | Set `run/main_scene="res://CityScene.tscn"`. |

Coordinate mapping: bundle `xy = [x_east, z_north]` meters → Godot `(x, ?, z)` with building height along `+Y`. The city is a few km across; the camera is placed accordingly. Blocks are scaled up from the bundle's realistic-but-tiny footprints to a readable stylized size via exported knobs.

---

## Task 1: Commit the sample bundle + the (currently untracked) Godot project

**Files:**
- Add: `godot/sample_bundle/*.json`, `godot/project.godot`, `godot/icon.svg`, `godot/icon.svg.import`, `godot/.editorconfig`, `godot/.gitattributes`, `godot/.gitignore`

- [ ] **Step 1: Confirm the sample bundle exists**

Run: `py -c "import json,os; d='godot/sample_bundle'; print({n: bool(os.path.exists(os.path.join(d,n+'.json'))) for n in ['meta','zones','roads','timeline']})"`
Expected: all four `True`.

- [ ] **Step 2: Confirm godot/.gitignore won't exclude the bundle**

Run: `py -c "print(open('godot/.gitignore').read())"`
Expected: it ignores `.godot/` and `/android/` only — `sample_bundle/` is NOT ignored. (If it is, stop and report.)

- [ ] **Step 3: Commit the Godot project + sample bundle**

```bash
git add godot/.editorconfig godot/.gitattributes godot/.gitignore godot/project.godot godot/icon.svg godot/icon.svg.import godot/sample_bundle
git commit -m "chore(godot): track the Godot project + checked-in sample bundle"
```

---

## Task 2: Bundle loader

**Files:**
- Create: `godot/scripts/bundle_loader.gd`

- [ ] **Step 1: Create `godot/scripts/bundle_loader.gd`**

```gdscript
class_name BundleLoader
extends RefCounted

## Loads an Asphodel city bundle (the 4 JSON files produced by
## `python -m asphodel.osm_city`) from a res:// or user:// directory into a
## typed Dictionary: { "meta":Dictionary, "zones":Array, "roads":Dictionary,
## "timeline":Dictionary }. Returns an empty Dictionary and pushes a clear error
## if anything is missing or malformed.

const _PARTS := ["meta", "zones", "roads", "timeline"]


static func load_bundle(dir_path: String) -> Dictionary:
	var bundle := {}
	for part in _PARTS:
		var path := dir_path.path_join(part + ".json")
		if not FileAccess.file_exists(path):
			push_error("Bundle file missing: %s" % path)
			return {}
		var text := FileAccess.get_file_as_string(path)
		if text.is_empty():
			push_error("Bundle file empty or unreadable: %s" % path)
			return {}
		var parsed: Variant = JSON.parse_string(text)
		if parsed == null:
			push_error("Bundle file is not valid JSON: %s" % path)
			return {}
		bundle[part] = parsed

	var meta: Dictionary = bundle["meta"]
	if not meta.has("version"):
		push_error("Bundle meta.json missing 'version' — not an Asphodel bundle?")
		return {}
	return bundle
```

- [ ] **Step 2: Commit**

```bash
git add godot/scripts/bundle_loader.gd
git commit -m "feat(godot): bundle loader (4-file JSON -> typed Dictionary)"
```

---

## Task 3: City builder — blocks, roads, ground, light, camera

**Files:**
- Create: `godot/scripts/city_builder.gd`

- [ ] **Step 1: Create `godot/scripts/city_builder.gd`**

```gdscript
extends Node3D

## Builds the low-poly block city from an Asphodel bundle at runtime.
## Zone blocks are drawn as a single MultiMeshInstance3D of boxes, colored by
## zone density; major roads as line strips; plus a ground plane, a sun, and a
## camera framed to the city. The bundle directory is exported so Phase 3 can
## point it at a freshly generated city.

@export var bundle_dir: String = "res://sample_bundle"
## Blocks come from realistic (small) footprints; scale them up to a readable
## stylized size. Horizontal size is a fraction of the mean cell side.
@export var block_footprint_frac: float = 0.16
@export var block_height_scale: float = 3.0
@export var low_density_color: Color = Color(0.35, 0.45, 0.55)
@export var high_density_color: Color = Color(0.95, 0.85, 0.55)

var _meta: Dictionary
var _zones: Array


func _ready() -> void:
	var bundle := BundleLoader.load_bundle(bundle_dir)
	if bundle.is_empty():
		push_error("city_builder: failed to load bundle at %s — see errors above." % bundle_dir)
		return
	_meta = bundle["meta"]
	_zones = bundle["zones"]
	_add_environment_and_light()
	_build_ground()
	_build_blocks()
	_build_roads(bundle["roads"])
	_frame_camera()
	print("Asphodel: built '%s' — %d zones, %d block instances."
		% [_meta.get("name", "?"), _zones.size(), _count_blocks()])


func _count_blocks() -> int:
	var n := 0
	for z in _zones:
		n += (z.get("blocks", []) as Array).size()
	return n


func _cell_side() -> float:
	var grid: Dictionary = _meta.get("grid", {})
	return float(grid.get("cell_m", 100.0))


func _add_environment_and_light() -> void:
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.07, 0.09, 0.13)
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color(0.5, 0.55, 0.6)
	env.ambient_light_energy = 0.5
	var we := WorldEnvironment.new()
	we.environment = env
	add_child(we)

	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-55.0, -45.0, 0.0)
	sun.light_energy = 1.1
	sun.shadow_enabled = true
	add_child(sun)


func _world_bounds() -> Rect2:
	# Axis-aligned XZ bounds of all zone centers (+ half-extent), in meters.
	var min_x := INF
	var min_z := INF
	var max_x := -INF
	var max_z := -INF
	for z in _zones:
		var c: Array = z["center_xy"]
		var e: Array = z["extent"]
		min_x = min(min_x, float(c[0]) - float(e[0]) * 0.5)
		max_x = max(max_x, float(c[0]) + float(e[0]) * 0.5)
		min_z = min(min_z, float(c[1]) - float(e[1]) * 0.5)
		max_z = max(max_z, float(c[1]) + float(e[1]) * 0.5)
	return Rect2(min_x, min_z, max_x - min_x, max_z - min_z)


func _build_ground() -> void:
	var b := _world_bounds()
	var plane := PlaneMesh.new()
	plane.size = Vector2(b.size.x * 1.2, b.size.y * 1.2)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.12, 0.14, 0.17)
	plane.material = mat
	var mi := MeshInstance3D.new()
	mi.mesh = plane
	mi.position = Vector3(b.position.x + b.size.x * 0.5, 0.0, b.position.y + b.size.y * 0.5)
	add_child(mi)


func _build_blocks() -> void:
	# One box mesh, instanced once per block, colored per-instance by density.
	var total := _count_blocks()
	if total == 0:
		return
	var side := _cell_side() * block_footprint_frac

	var box := BoxMesh.new()
	box.size = Vector3(1.0, 1.0, 1.0)  # unit cube; per-instance transform scales it
	var mat := StandardMaterial3D.new()
	mat.vertex_color_use_as_albedo = true  # let per-instance colors show
	mat.roughness = 0.9
	box.material = mat

	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.use_colors = true
	mm.mesh = box
	mm.instance_count = total

	var i := 0
	for z in _zones:
		var density := float(z.get("density", 0.0))
		var col := low_density_color.lerp(high_density_color, clampf(density, 0.0, 1.0))
		for blk in (z.get("blocks", []) as Array):
			var bxy: Array = blk["xy"]
			var h := float(blk["height"]) * block_height_scale
			var basis := Basis().scaled(Vector3(side, h, side))
			var origin := Vector3(float(bxy[0]), h * 0.5, float(bxy[1]))
			mm.set_instance_transform(i, Transform3D(basis, origin))
			mm.set_instance_color(i, col)
			i += 1

	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	add_child(mmi)


func _build_roads(roads: Dictionary) -> void:
	var polylines: Array = roads.get("polylines", [])
	if polylines.is_empty():
		return
	var im := ImmediateMesh.new()
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_color = Color(0.9, 0.9, 0.95)
	for pl in polylines:
		var pts: Array = pl.get("points", [])
		if pts.size() < 2:
			continue
		im.surface_begin(Mesh.PRIMITIVE_LINE_STRIP, mat)
		for p in pts:
			im.surface_add_vertex(Vector3(float(p[0]), 1.0, float(p[1])))
		im.surface_end()
	var mi := MeshInstance3D.new()
	mi.mesh = im
	add_child(mi)


func _frame_camera() -> void:
	var b := _world_bounds()
	var center := Vector3(b.position.x + b.size.x * 0.5, 0.0, b.position.y + b.size.y * 0.5)
	var span := maxf(b.size.x, b.size.y)
	var cam := Camera3D.new()
	cam.far = span * 6.0 + 1000.0
	# Angled bird's-eye view from the +X/+Z corner, looking at the city center.
	var eye := center + Vector3(span * 0.7, span * 0.8, span * 0.7)
	cam.position = eye
	cam.current = true
	add_child(cam)
	cam.look_at(center, Vector3.UP)  # after add_child so global transform is set
```

- [ ] **Step 2: Commit**

```bash
git add godot/scripts/city_builder.gd
git commit -m "feat(godot): procedural block-city builder (blocks/roads/ground/camera)"
```

---

## Task 4: Main scene + wire up Play

**Files:**
- Create: `godot/CityScene.tscn`
- Modify: `godot/project.godot`

- [ ] **Step 1: Create `godot/CityScene.tscn`**

```
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://scripts/city_builder.gd" id="1_city"]

[node name="CityScene" type="Node3D"]
script = ExtResource("1_city")
```

- [ ] **Step 2: Set the main scene in `godot/project.godot`**

In the `[application]` section, add a `run/main_scene` line so it reads:

```
[application]

config/name="Asphodel"
run/main_scene="res://CityScene.tscn"
config/features=PackedStringArray("4.4", "Forward Plus")
config/icon="res://icon.svg"
```

- [ ] **Step 3: Commit**

```bash
git add godot/CityScene.tscn godot/project.godot
git commit -m "feat(godot): CityScene main scene + wire run/main_scene"
```

---

## Task 5: Editor verification (user-driven)

There is no Godot CLI here, so this is verified by the user in the editor.

- [ ] **Step 1:** Open the project at `godot/` in Godot 4.4 (Project Manager → Import → `godot/project.godot`).
- [ ] **Step 2:** Press **Play** (F5).
- [ ] **Step 3: Expected:** a window opens showing a dark ground plane with a grid of pale-blue→amber boxes (taller/amber where density is higher), thin white road lines, viewed from an angled bird's-eye camera. The Output panel prints `Asphodel: built 'Sampleton' — 56 zones, N block instances.`
- [ ] **Step 4: If the screen is empty or boxes are off-screen:** check the Output/Debugger panel for the `push_error` messages from the loader (missing/!valid bundle), and report them; the most likely tweak is the camera `span` multipliers or `block_height_scale` in `city_builder.gd`.

---

## Done criteria (Phase 2)

- Pressing Play renders the sample city (blocks + roads + framed camera); the Output panel confirms zone/instance counts.
- The Godot project and the sample bundle are committed (no longer untracked).
- `bundle_dir` is exported so Phase 3 can point the same scene at a freshly generated city.

**Next:** Phase 3 — city-select screen → invoke the Python pipeline (subprocess) → load the produced bundle → timeline play/pause/scrub that re-colors blocks by belief over time.
