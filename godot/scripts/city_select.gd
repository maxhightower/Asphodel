extends Control

## City-select stub. For now it just loads the checked-in sample city. Phase 3
## will add a text field + "fetch a real city" (runs the Python pipeline) here.

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

	var note := Label.new()
	note.text = "Phase 3 will let you type a real city here."
	note.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	note.add_theme_font_size_override("font_size", 16)
	note.modulate = Color(0.7, 0.75, 0.8)
	vb.add_child(note)

	var gap := Control.new()
	gap.custom_minimum_size = Vector2(0, 20)
	vb.add_child(gap)

	vb.add_child(_make_button("Load sample city", _on_load_sample))
	vb.add_child(_make_button("Back", _on_back))


func _make_button(text: String, handler: Callable) -> Button:
	var b := Button.new()
	b.text = text
	b.custom_minimum_size = Vector2(280, 48)
	b.add_theme_font_size_override("font_size", 22)
	b.pressed.connect(handler)
	return b


func _on_load_sample() -> void:
	get_tree().change_scene_to_file("res://CityScene.tscn")


func _on_back() -> void:
	get_tree().change_scene_to_file("res://MainMenu.tscn")
