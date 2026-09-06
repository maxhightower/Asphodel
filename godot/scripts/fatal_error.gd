extends Control
class_name FatalError
## FatalError — the readable, actionable failure screen shown when the authority
## cannot be brought up (Convergence V2 §11/§32). The canonical build NEVER falls
## back to a silent non-authoritative city; a missing/crashed/incompatible
## authority, a missing bundle, a port failure or an incompatible save all land
## here with a cause and where to find logs.

const MESSAGES := {
	"authority_missing": "The simulation authority is missing from this build.",
	"authority_crashed": "The simulation authority failed to start.",
	"protocol_mismatch": "The simulation authority speaks a different protocol than this game build.",
	"build_mismatch": "The simulation authority is a different build than this game.",
	"bundle_missing": "The selected city's data is missing from this build.",
	"port_failure": "Could not reserve a local port for the simulation.",
	"connect_failure": "Could not connect to the simulation authority.",
	"save_incompatible": "This save was written by an incompatible build.",
}

static var code := ""
static var detail := ""

static func show_error(tree: SceneTree, err_code: String, err_detail: String) -> void:
	code = err_code
	detail = err_detail
	tree.change_scene_to_file("res://FatalError.tscn")


func _ready() -> void:
	var bg := ColorRect.new()
	bg.color = Color(0.06, 0.06, 0.08)
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(bg)

	var box := VBoxContainer.new()
	box.set_anchors_preset(Control.PRESET_CENTER)
	box.custom_minimum_size = Vector2(720, 0)
	box.add_theme_constant_override("separation", 14)
	add_child(box)

	var title := Label.new()
	title.text = "Asphodel cannot start"
	title.add_theme_font_size_override("font_size", 30)
	box.add_child(title)

	var msg := Label.new()
	msg.text = MESSAGES.get(code, "The simulation could not be started.")
	msg.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	msg.add_theme_font_size_override("font_size", 18)
	box.add_child(msg)

	if detail != "":
		var det := Label.new()
		det.text = detail
		det.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		det.modulate = Color(0.75, 0.75, 0.8)
		box.add_child(det)

	var meta := Label.new()
	meta.text = "error: %s   protocol v%d   logs: %s" % [
		code, SimBridge.PROTOCOL_VERSION, ProjectSettings.globalize_path("user://logs")]
	meta.modulate = Color(0.6, 0.6, 0.65)
	box.add_child(meta)

	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 12)
	box.add_child(row)
	var retry := Button.new()
	retry.text = "Back to menu"
	retry.pressed.connect(func(): get_tree().change_scene_to_file("res://MainMenu.tscn"))
	row.add_child(retry)
	var quit := Button.new()
	quit.text = "Quit"
	quit.pressed.connect(func(): get_tree().quit())
	row.add_child(quit)
