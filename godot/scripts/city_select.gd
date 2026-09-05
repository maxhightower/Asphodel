extends Control

## City-select screen: pick one of the bundled real cities from a dropdown and
## load it. The chosen bundle dir is stashed in the Session autoload so the world
## scene (IsometricWorld / StreetScene) knows which city to render. (Phase 3 will
## add free-text entry that runs the Python pipeline to fetch any city on demand.)

## Fallback roster, used only if the bundles/ directory cannot be scanned (e.g. a
## trimmed export). The live list below is derived from the shipped bundles.
const FALLBACK_CITIES := [
	{"name": "Madisonville, Texas", "dir": "res://bundles/madisonville_tx"},
	{"name": "Houston, Texas", "dir": "res://bundles/houston"},
	{"name": "San Antonio, Texas", "dir": "res://bundles/san_antonio"},
	{"name": "Austin, Texas", "dir": "res://bundles/austin"},
]

const BUNDLE_ROOT := "res://bundles"

var _cities: Array = []
var _option: OptionButton


static func discover_cities(root: String = BUNDLE_ROOT) -> Array:
	## Data-driven city roster: every bundle directory that carries BOTH a
	## meta.json (so it is an Asphodel bundle) and a citizens.json (so a player
	## citizen can actually be chosen) is playable. Region-only / synthetic
	## bundles without a citizen roster are skipped rather than hardcoded out.
	var out: Array = []
	var d := DirAccess.open(root)
	if d == null:
		return out
	var names := d.get_directories()
	names.sort()
	for name in names:
		var dir: String = root.path_join(name)
		if not FileAccess.file_exists(dir.path_join("citizens.json")):
			continue
		var meta_path := dir.path_join("meta.json")
		if not FileAccess.file_exists(meta_path):
			continue
		var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(meta_path))
		if not (parsed is Dictionary):
			continue
		var label := str((parsed as Dictionary).get("name", name))
		out.append({"name": label, "dir": dir})
	return out


func _ready() -> void:
	_cities = discover_cities()
	if _cities.is_empty():
		_cities = FALLBACK_CITIES.duplicate(true)

	var bg := ColorRect.new()
	bg.color = Color(0.07, 0.09, 0.13)
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	bg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(bg)

	var center := CenterContainer.new()
	center.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(center)

	var vb := VBoxContainer.new()
	vb.alignment = BoxContainer.ALIGNMENT_CENTER
	vb.add_theme_constant_override("separation", 16)
	center.add_child(vb)

	var title := Label.new()
	title.text = "Choose a City"
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title.add_theme_font_size_override("font_size", 40)
	vb.add_child(title)

	_option = OptionButton.new()
	_option.custom_minimum_size = Vector2(300, 44)
	_option.add_theme_font_size_override("font_size", 22)
	for city in _cities:
		_option.add_item(city["name"])
	_option.selected = 0
	vb.add_child(_option)

	var gap := Control.new()
	gap.custom_minimum_size = Vector2(0, 20)
	vb.add_child(gap)

	vb.add_child(_make_button("Load City", _on_load))
	vb.add_child(_make_button("Back", _on_back))


func _make_button(text: String, handler: Callable) -> Button:
	var b := Button.new()
	b.text = text
	b.custom_minimum_size = Vector2(300, 48)
	b.add_theme_font_size_override("font_size", 22)
	b.pressed.connect(handler)
	return b


func _on_load() -> void:
	if _option.selected < 0 or _option.selected >= _cities.size():
		return
	var dir: String = _cities[_option.selected]["dir"]
	Session.bundle_dir = dir
	var pool := BundleLoader.load_citizens(dir)
	if pool.is_empty():
		push_error("No citizens in bundle %s — cannot start." % dir)
		return
	var rng := RandomNumberGenerator.new()
	rng.randomize()
	Session.citizen = pool[rng.randi_range(0, pool.size() - 1)]
	get_tree().change_scene_to_file("res://CharacterScreen.tscn")


func _on_back() -> void:
	get_tree().change_scene_to_file("res://MainMenu.tscn")
