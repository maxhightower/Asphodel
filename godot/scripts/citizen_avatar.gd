extends Node3D
class_name CitizenAvatar

## CitizenAvatar — a near / high-fidelity NPC (LOD2, H4).
##
## Used for the small BOUNDED pool of citizens that are close to the player, the
## current interaction target, nearby named roster members, and interior
## occupants (H10). Everyone else stays in the batched MultiMesh crowd.
##
## It is built as a MultiMeshInstance3D with a SINGLE instance so it drives the
## exact same shared shader through the exact same per-instance channels
## (INSTANCE_COLOR / INSTANCE_CUSTOM) as the crowd. That guarantees a citizen
## looks identical when they cross the MultiMesh <-> avatar boundary — only the
## triangle count of the mesh changes (H4/H15). Avatars are POOLED and reused,
## never instantiated per snapshot (H12).
##
## The root is a Node3D carrying `citizen_id` metadata at its authoritative
## position, so interaction (which reads `get_meta("citizen_id")` +
## `global_position` off the Occupants children) keeps working unchanged (H10).

const V = preload("res://scripts/citizen_visual_identity.gd")
const M = preload("res://scripts/citizen_meshes.gd")

var citizen_id: int = -1
var appearance: Dictionary = {}
var _mmi: MultiMeshInstance3D
var _mm: MultiMesh
var _label: Label3D
var _geo_key: String = ""


func _init() -> void:
	_mm = MultiMesh.new()
	_mm.transform_format = MultiMesh.TRANSFORM_3D
	_mm.use_colors = true
	_mm.use_custom_data = true
	_mm.instance_count = 1
	_mm.set_instance_transform(0, Transform3D.IDENTITY)
	_mmi = MultiMeshInstance3D.new()
	_mmi.multimesh = _mm
	add_child(_mmi)


## Assign this pooled avatar to a citizen. `material` is the shared NPC material
## (built once by the renderer). `lod` lets interior occupants use the richer
## near mesh while keeping the same identity.
func configure(cid: int, appear: Dictionary, material: ShaderMaterial, gait: float = 0.0,
		lod: int = M.LOD_NEAR) -> void:
	citizen_id = cid
	appearance = appear
	set_meta("citizen_id", cid)
	name = "Avatar_%d" % cid if cid >= 0 else "Avatar_fill"
	var key := "%d_%d_%d_%d_%d" % [int(appear.get("body", 0)), int(appear.get("lower", 0)),
		int(appear.get("hair", 0)), int(appear.get("sleeve", 0)), lod]
	if key != _geo_key:
		_geo_key = key
		_mm.mesh = M.combined_mesh(appear, lod)
	if _mmi.material_override != material:
		_mmi.material_override = material
	_mm.set_instance_color(0, V.instance_color(appear, gait))
	_mm.set_instance_custom_data(0, V.instance_custom(appear))
	visible = true


## Override the mesh material (used by the silhouette gallery gate to render the
## geometry in a single neutral grey). Pass the shared material back to restore.
func set_material_override(mat: Material) -> void:
	_mmi.material_override = mat


func set_gait(gait: float) -> void:
	if _mm.instance_count > 0:
		var c := _mm.get_instance_color(0)
		c.a = clampf(gait, 0.0, 1.0)
		_mm.set_instance_color(0, c)


func set_heading(yaw: float) -> void:
	rotation.y = yaw


## Show (and set) a nameplate above the head; pass "" to hide it.
func set_nameplate(text: String) -> void:
	if text == "":
		if _label != null:
			_label.visible = false
		return
	if _label == null:
		_label = Label3D.new()
		_label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
		_label.no_depth_test = true
		_label.pixel_size = 0.004
		_label.modulate = Color(1, 1, 1)
		_label.outline_size = 8
		add_child(_label)
	_label.text = text
	_label.position = Vector3(0, M.head_height(int(appearance.get("body", 0))) + 0.28, 0)
	_label.visible = true


func release() -> void:
	## Return to the pool: hidden, id cleared, but geometry/material kept for reuse.
	visible = false
	citizen_id = -1
	if _label != null:
		_label.visible = false
	if has_meta("citizen_id"):
		remove_meta("citizen_id")
