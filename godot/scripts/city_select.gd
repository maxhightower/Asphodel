extends Control

## City-select screen: pick one of the bundled real cities from a dropdown and
## load it. The chosen bundle dir is stashed in the Session autoload so CityScene
## knows which city to render. (Phase 3 will add free-text entry that runs the
## Python pipeline to fetch any city on demand.)

const CITIES := [
	{"name": "Houston", "dir": "res://bundles/houston"},
	{"name": "San Antonio", "dir": "res://bundles/san_antonio"},
	{"name": "Austin", "dir": "res://bundles/austin"},
]

var _option: OptionButton


func _ready() -> void:
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
	for city in CITIES:
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
	Session.bundle_dir = CITIES[_option.selected]["dir"]
	get_tree().change_scene_to_file("res://CityScene.tscn")


func _on_back() -> void:
	get_tree().change_scene_to_file("res://MainMenu.tscn")
