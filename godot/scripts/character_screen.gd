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

	# What the citizen is actually doing right now, so the screen, the signature
	# and the first-person spawn all describe the same moment.
	var activity: String = c.get("current_activity", "")
	var where: String = c.get("current_location", "")
	if activity != "":
		var hour: float = float(c.get("spawn_hour", 0.0))
		vb.add_child(_line("%02d:%02d  ·  %s at %s" % [
			int(hour), int((hour - int(hour)) * 60.0), activity, where]))

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
	# Isometric presentation is the default gameplay scene (ISO V1). The legacy
	# first-person path stays accessible but is frozen/deprecated.
	vb.add_child(_button("Continue", func(): get_tree().change_scene_to_file("res://IsometricWorld.tscn")))
	vb.add_child(_button("First-person (legacy)", func(): get_tree().change_scene_to_file("res://StreetScene.tscn")))
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
