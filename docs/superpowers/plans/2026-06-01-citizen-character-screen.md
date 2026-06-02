# Random Citizen + Character Screen (Sub-projects 1 & 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Python tasks are TDD (run `py` on Windows — `python`/`python3` are broken). Godot tasks have **no automated runner here** and are **verified in the editor by the user**. Steps use checkbox (`- [ ]`) syntax.

**Goal:** After Load City, randomly pick a spawn-config archetype + citizen and show the player an ARK-style character screen describing who they are.

**Architecture:** First merge the `citizen-spawn-configs` branch onto trunk (Sub-project 1). Then a new `asphodel/osm_city/citizens.py` bakes a *population* of spawnable citizens (across the `generic/capital/harbor/university` profiles, each with its occupation's signature predicament + a generated name) into each bundle as `citizens.json`. Godot loads it on Load City, random-picks one into the `Session` autoload, and shows `CharacterScreen` before entering the city.

**Tech Stack:** Python 3 (`py`), numpy, existing `asphodel` package + the merged `asphodel.citizen`/`signatures`; Godot 4.4 GDScript. No new deps.

**Spec:** `docs/superpowers/specs/2026-06-01-citizen-first-person-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| (merge) `asphodel/citizen.py`, `signatures.py`, `cities/*.yaml`, … | Brought onto trunk by Sub-project 1. |
| `asphodel/osm_city/citizens.py` | Bake a render-ready citizen population from the city profiles + catalog. |
| `asphodel/osm_city/__main__.py` (modify) | After writing the bundle, also write `citizens.json`. |
| `tests/test_citizens_bake.py` | Tests for the bake (shape, determinism, signatures attached). |
| `godot/scripts/bundle_loader.gd` (modify) | Add `load_citizens(dir) -> Array`. |
| `godot/scripts/session.gd` (modify) | Add `var citizen: Dictionary`. |
| `godot/scripts/city_select.gd` (modify) | On Load: pick a random citizen → Session → go to CharacterScreen. |
| `godot/CharacterScreen.tscn` + `godot/scripts/character_screen.gd` | The ARK-style screen. |

Flow after this plan: `CitySelect ──Load City──▶ CharacterScreen ──Continue──▶ CityScene` (Sub-project 3 later repoints Continue → StreetScene).

---

## Task 1: Integrate the `citizen-spawn-configs` branch

**Files:** merge; conflict surface is only `README.md` and `asphodel/__init__.py`.

- [ ] **Step 1: Confirm clean tree + fetch**

Run: `git status --short` (expect clean) then `git fetch origin`.

- [ ] **Step 2: Start the merge**

```bash
git merge --no-ff origin/claude/citizen-spawn-configs-K4iZW -m "merge: integrate citizen-spawn-configs (citizen model, signatures, city profiles)"
```
Expected: conflicts in `asphodel/__init__.py` and `README.md` (everything else auto-merges as additions).

- [ ] **Step 3: Resolve `asphodel/__init__.py`**

Open the file; for each `<<<<<<< / ======= / >>>>>>>` block, **keep BOTH sides' content** (union of exports — trunk's `World`/osm/orchestrator exports *and* the branch's citizen/world exports). Remove the conflict markers. If both sides export a symbol with the same name, keep one copy. Verify no `<<<<<<<` remain: `grep -n "^<<<<<<<\|^>>>>>>>" asphodel/__init__.py` → no output.

- [ ] **Step 4: Resolve `README.md`**

Keep both sides' sections (trunk's OSM/Godot sections and the branch's citizen sections). Remove markers. `grep -n "^<<<<<<<\|^>>>>>>>" README.md` → no output.

- [ ] **Step 5: Verify imports resolve**

Run: `py -c "import asphodel.citizen, asphodel.signatures, asphodel.osm_city.pipeline, asphodel.orchestrator; print('imports ok')"`
Expected: `imports ok` (no ImportError).

- [ ] **Step 6: Run the FULL test suite (trunk + branch tests)**

Run: `py -m pytest -q`
Expected: all pass — trunk's (osm/model/phase4a/orchestrator/topology/interventions) **and** the branch's (`test_citizen`, `test_world`, `test_environments`, `test_vehicles`, `test_gametime`, `test_signatures`, `test_travel_events`). If a branch test fails because it imports a symbol trunk renamed, STOP and report the specific failure (do not paper over it).

- [ ] **Step 7: Commit the merge**

```bash
git add asphodel/__init__.py README.md
git commit --no-edit
```

---

## Task 2: Citizen bake module

**Files:**
- Create: `asphodel/osm_city/citizens.py`
- Test: `tests/test_citizens_bake.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_citizens_bake.py`:

```python
"""Tests for baking a spawnable citizen population into a bundle."""
from __future__ import annotations

from asphodel.osm_city import citizens as cz

_REQUIRED_KEYS = {
    "profile", "name", "age", "occupation", "shift", "home_district",
    "work_district", "spawn_hour", "current_activity", "current_location",
    "inventory", "signature_title", "signature_location",
    "signature_situation", "signature_dilemma",
}


def test_population_count_and_profiles():
    pop = cz.build_citizen_population("cities", n_per_profile=5, seed=0)
    assert len(pop) == 5 * len(cz.DEFAULT_PROFILES)
    assert {r["profile"] for r in pop} == set(cz.DEFAULT_PROFILES)


def test_records_have_required_keys_and_types():
    pop = cz.build_citizen_population("cities", n_per_profile=3, seed=1)
    for r in pop:
        assert _REQUIRED_KEYS <= set(r.keys())
        assert isinstance(r["name"], str) and r["name"]
        assert isinstance(r["age"], int) and r["age"] > 0
        assert isinstance(r["inventory"], dict)


def test_signatures_attached_for_common_jobs():
    # At least some citizens carry a non-empty signature title.
    pop = cz.build_citizen_population("cities", n_per_profile=20, seed=2)
    assert any(r["signature_title"] for r in pop)


def test_bake_is_deterministic():
    a = cz.build_citizen_population("cities", n_per_profile=8, seed=7)
    b = cz.build_citizen_population("cities", n_per_profile=8, seed=7)
    assert a == b
```

- [ ] **Step 2: Run to verify it fails**

Run: `py -m pytest tests/test_citizens_bake.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'asphodel.osm_city.citizens'`.

- [ ] **Step 3: Implement `asphodel/osm_city/citizens.py`**

```python
"""Bake a population of spawnable citizens into a city bundle.

Loads the citizen-spawn configs (CityProfile archetypes + the shared catalog),
spawns N citizens per profile, attaches each occupation's signature scenario,
assigns a generated display name, and flattens to render-ready dicts that Godot
reads from the bundle's citizens.json. No game-engine or network dependency.
"""
from __future__ import annotations

import json
import os

from ..citizen import CityProfile, CitizenSpawnCatalog, spawn_population
from ..signatures import default_signatures

DEFAULT_PROFILES = ["generic", "capital", "harbor", "university"]

_FIRST = ["Maria", "James", "Aisha", "Wei", "Carlos", "Nadia", "Tom", "Priya",
          "Diego", "Sara", "Omar", "Grace", "Leo", "Hana", "Ruth", "Andre"]
_LAST = ["Reyes", "Okafor", "Nguyen", "Patel", "Johnson", "Khan", "Garcia",
         "Mensah", "Silva", "Brooks", "Costa", "Ahmed", "Rivera", "Park",
         "Cohen", "Diallo"]


def _name_for(citizen_id: int, profile: str) -> str:
    """Deterministic display name (Python's hash() is salted, so derive our own)."""
    base = citizen_id * 1000 + sum(ord(ch) for ch in profile)
    return f"{_FIRST[base % len(_FIRST)]} {_LAST[(base // len(_FIRST)) % len(_LAST)]}"


def _flatten(profile_name: str, citizen, signatures: dict) -> dict:
    sig = signatures.get(citizen.occupation)
    return {
        "profile": profile_name,
        "name": _name_for(citizen.citizen_id, profile_name),
        "age": int(citizen.age),
        "occupation": citizen.occupation,
        "shift": citizen.shift,
        "home_district": citizen.home_district,
        "work_district": citizen.work_district or "",
        "spawn_hour": round(float(citizen.spawn_hour), 2),
        "current_activity": citizen.current_activity,
        "current_location": citizen.current_location,
        "inventory": dict(citizen.inventory),
        "signature_title": sig.name if sig else "",
        "signature_location": sig.location if sig else "",
        "signature_situation": sig.situation if sig else "",
        "signature_dilemma": sig.dilemma if sig else "",
    }


def build_citizen_population(cities_dir: str, profiles=None,
                             n_per_profile: int = 15, seed: int = 0) -> list[dict]:
    """Spawn n_per_profile citizens for each profile archetype; return flat dicts."""
    profiles = profiles or DEFAULT_PROFILES
    catalog = CitizenSpawnCatalog.from_yaml(os.path.join(cities_dir, "_catalog.yaml"))
    signatures = default_signatures()
    out: list[dict] = []
    for i, profile_name in enumerate(profiles):
        city = CityProfile.from_yaml(os.path.join(cities_dir, f"{profile_name}.yaml"))
        for citizen in spawn_population(city, catalog, n=n_per_profile, seed=seed + i):
            out.append(_flatten(profile_name, citizen, signatures))
    return out


def write_citizens(bundle_dir: str, cities_dir: str = "cities",
                   n_per_profile: int = 15, seed: int = 0) -> int:
    """Write <bundle_dir>/citizens.json; return the number of citizens written."""
    pop = build_citizen_population(cities_dir, n_per_profile=n_per_profile, seed=seed)
    os.makedirs(bundle_dir, exist_ok=True)
    path = os.path.join(bundle_dir, "citizens.json")
    with open(path, "w") as f:
        json.dump(pop, f, indent=2, sort_keys=True)
        f.write("\n")
    return len(pop)
```

Note: if `CityProfile.from_yaml` / `CitizenSpawnCatalog.from_yaml` / `spawn_population` have slightly different signatures than assumed, adapt the calls to the real ones (read `asphodel/citizen.py`) and report the adjustment — do not guess silently.

- [ ] **Step 4: Run to verify it passes**

Run: `py -m pytest tests/test_citizens_bake.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add asphodel/osm_city/citizens.py tests/test_citizens_bake.py
git commit -m "feat(osm): bake spawnable citizen population (citizens.json)"
```

---

## Task 3: Wire citizens into the CLI + add to existing bundles

**Files:**
- Modify: `asphodel/osm_city/__main__.py`
- Data: write `citizens.json` into the 4 existing bundles (`godot/bundles/{houston,san_antonio,austin}`, `godot/sample_bundle`)

- [ ] **Step 1: Add a `--no-citizens` / citizen bake to `__main__.py`**

In `asphodel/osm_city/__main__.py`, add an import and a step. After the existing `build_bundle(...)` call in `main()`, insert:

```python
        from .citizens import write_citizens
        if not args.no_citizens:
            n = write_citizens(args.out, cities_dir=args.cities_dir,
                               n_per_profile=args.citizens_per_profile, seed=args.seed)
            print(f"Baked {n} citizens into {args.out}")
```

And add these arguments alongside the existing `p.add_argument(...)` lines:

```python
    p.add_argument("--cities-dir", default="cities", help="Dir of city-profile YAMLs")
    p.add_argument("--citizens-per-profile", type=int, default=15)
    p.add_argument("--no-citizens", action="store_true", help="Skip citizen baking")
```

- [ ] **Step 2: Write citizens.json into the four committed bundles**

Run:
```bash
py -c "from asphodel.osm_city.citizens import write_citizens; [print(d, write_citizens('godot/bundles/'+d if d!='sample_bundle' else 'godot/sample_bundle')) for d in ['houston','san_antonio','austin','sample_bundle']]"
```
Expected: prints each name + a citizen count (e.g. 60). Confirm the files exist:
`py -c "import os; print([os.path.exists(f'godot/{b}/citizens.json') for b in ['bundles/houston','bundles/san_antonio','bundles/austin','sample_bundle']])"` → all `True`.

- [ ] **Step 3: Sanity-check one citizens.json**

Run: `py -c "import json; c=json.load(open('godot/bundles/austin/citizens.json')); print(len(c), c[0]['name'], c[0]['occupation'], '|', c[0]['signature_title'])"`
Expected: a count and a sample citizen line.

- [ ] **Step 4: Commit**

```bash
git add asphodel/osm_city/__main__.py godot/bundles/*/citizens.json godot/sample_bundle/citizens.json
git commit -m "feat(osm): CLI bakes citizens.json; add to the four bundles"
```

---

## Task 4: Godot — load citizens + random-pick on Load City

**Files:**
- Modify: `godot/scripts/bundle_loader.gd`, `godot/scripts/session.gd`, `godot/scripts/city_select.gd`

- [ ] **Step 1: Add a citizens loader to `bundle_loader.gd`**

Append to `godot/scripts/bundle_loader.gd`:

```gdscript
static func load_citizens(dir_path: String) -> Array:
	## Returns the bundle's citizen list, or [] if absent/invalid.
	var path := dir_path.path_join("citizens.json")
	if not FileAccess.file_exists(path):
		push_warning("No citizens.json in %s" % dir_path)
		return []
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	return parsed if parsed is Array else []
```

- [ ] **Step 2: Add citizen state to `session.gd`**

In `godot/scripts/session.gd`, add below `var bundle_dir`:

```gdscript
var citizen: Dictionary = {}   # the citizen the player was spawned as
```

- [ ] **Step 3: In `city_select.gd`, pick a random citizen and go to the character screen**

Replace the `_on_load` function in `godot/scripts/city_select.gd` with:

```gdscript
func _on_load() -> void:
	var dir: String = CITIES[_option.selected]["dir"]
	Session.bundle_dir = dir
	var pool := BundleLoader.load_citizens(dir)
	if pool.is_empty():
		push_error("No citizens in bundle %s — cannot start." % dir)
		return
	var rng := RandomNumberGenerator.new()
	rng.randomize()
	Session.citizen = pool[rng.randi_range(0, pool.size() - 1)]
	get_tree().change_scene_to_file("res://CharacterScreen.tscn")
```

- [ ] **Step 4: Editor verification** — covered in Task 6 (after the screen exists).

- [ ] **Step 5: Commit**

```bash
git add godot/scripts/bundle_loader.gd godot/scripts/session.gd godot/scripts/city_select.gd
git commit -m "feat(godot): load citizens.json and random-pick one on Load City"
```

---

## Task 5: Godot — the ARK-style character screen

**Files:**
- Create: `godot/CharacterScreen.tscn`, `godot/scripts/character_screen.gd`

- [ ] **Step 1: Create `godot/scripts/character_screen.gd`**

```gdscript
extends Control

## Shows the randomly-picked citizen (from Session.citizen) ARK-style, then
## Continue -> the city (Sub-project 3 will repoint this to the street scene).

func _ready() -> void:
	var c: Dictionary = Session.citizen
	var bg := ColorRect.new()
	bg.color = Color(0.07, 0.09, 0.13)
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	bg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(bg)

	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(center)

	var vb := VBoxContainer.new()
	vb.add_theme_constant_override("separation", 12)
	vb.custom_minimum_size = Vector2(640, 0)
	center.add_child(vb)

	if c.is_empty():
		var err := Label.new()
		err.text = "No citizen selected. Go back and Load a city."
		vb.add_child(err)
		vb.add_child(_button("Back", func(): get_tree().change_scene_to_file("res://CitySelect.tscn")))
		return

	vb.add_child(_heading("You are %s" % c.get("name", "?")))
	vb.add_child(_line("%d-year-old %s  ·  lives in %s" % [
		int(c.get("age", 0)), str(c.get("occupation", "?")), str(c.get("home_district", "?"))]))

	var sig_title: String = c.get("signature_title", "")
	if sig_title != "":
		vb.add_child(_gap(10))
		vb.add_child(_subheading(sig_title))
		var situ: String = c.get("signature_situation", "")
		var dilemma: String = c.get("signature_dilemma", "")
		var loc: String = c.get("signature_location", "")
		var para := situ
		if loc != "":
			para = "%s  %s" % [loc, situ]
		if dilemma != "":
			para += "\n\n%s" % dilemma
		vb.add_child(_paragraph(para))

	var inv: Dictionary = c.get("inventory", {})
	if not inv.is_empty():
		vb.add_child(_gap(10))
		vb.add_child(_subheading("On hand"))
		var items: Array = []
		for k in inv.keys():
			items.append("%s ×%d" % [str(k), int(inv[k])])
		vb.add_child(_paragraph(", ".join(items)))

	vb.add_child(_gap(20))
	vb.add_child(_button("Continue", func(): get_tree().change_scene_to_file("res://CityScene.tscn")))
	vb.add_child(_button("Back", func(): get_tree().change_scene_to_file("res://CitySelect.tscn")))


func _heading(text: String) -> Label:
	var l := Label.new()
	l.text = text
	l.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	l.add_theme_font_size_override("font_size", 40)
	return l


func _subheading(text: String) -> Label:
	var l := Label.new()
	l.text = text
	l.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	l.add_theme_font_size_override("font_size", 24)
	l.modulate = Color(0.95, 0.85, 0.55)
	return l


func _line(text: String) -> Label:
	var l := Label.new()
	l.text = text
	l.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	l.add_theme_font_size_override("font_size", 18)
	return l


func _paragraph(text: String) -> Label:
	var l := Label.new()
	l.text = text
	l.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	l.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	l.custom_minimum_size = Vector2(600, 0)
	l.add_theme_font_size_override("font_size", 16)
	l.modulate = Color(0.8, 0.85, 0.9)
	return l


func _gap(h: int) -> Control:
	var c := Control.new()
	c.custom_minimum_size = Vector2(0, h)
	return c


func _button(text: String, handler: Callable) -> Button:
	var b := Button.new()
	b.text = text
	b.custom_minimum_size = Vector2(300, 46)
	b.add_theme_font_size_override("font_size", 22)
	b.pressed.connect(handler)
	return b
```

- [ ] **Step 2: Create `godot/CharacterScreen.tscn`**

```
[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://scripts/character_screen.gd" id="1_char"]

[node name="CharacterScreen" type="Control"]
layout_mode = 3
anchors_preset = 15
anchor_right = 1.0
anchor_bottom = 1.0
grow_horizontal = 2
grow_vertical = 2
script = ExtResource("1_char")
```

- [ ] **Step 3: Commit**

```bash
git add godot/CharacterScreen.tscn godot/scripts/character_screen.gd
git commit -m "feat(godot): ARK-style character screen (name/occupation/signature/inventory)"
```

---

## Task 6: Editor verification + docs

- [ ] **Step 1 (user, editor):** Reopen the Godot project so it imports the new script/scene. Main Menu → Start Game → pick **Austin** → **Load City**. Expected: a character screen — "You are {name}", a {age}-year-old {occupation} in {district}, a signature predicament paragraph, an "On hand" item list, and **Continue** / **Back**. Continue → the Austin block-city; Back → the dropdown (re-rolls on next Load). If the screen says "No citizen selected", the bundle's `citizens.json` didn't load — paste the Output panel.

- [ ] **Step 2: Update README** — under the OSM City section, add a short note:

```markdown
On **Load City** the game picks a random pre-baked citizen (from the bundle's
`citizens.json`, spawned across the generic/capital/harbor/university profile
archetypes) and shows an ARK-style character screen before entering the city.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: note the random-citizen character screen"
```

---

## Done criteria (Sub-projects 1 & 2)

- The citizen branch is merged; `py -m pytest -q` is fully green (trunk + branch tests).
- Every bundle has a `citizens.json`; the bake is deterministic and signature-attached.
- Load City → a random citizen → character screen → Continue enters the city.

**Next:** Sub-project 3 — repoint Continue to a procedural first-person `StreetScene` with a `CharacterBody3D` controller (WASD / Shift-sprint / mouse-look).
