class_name Lootable
extends StaticBody3D

## A searchable container. Interact once to receive its loot; afterwards it
## reports itself as "Searched" and yields nothing. The player finds these via
## its interact raycast (see first_person.gd).

var loot: Dictionary = {}        # resource name -> int amount
var display_name: String = "Container"
var _opened := false


func prompt() -> String:
	if _opened:
		return "%s (searched)" % display_name
	return "E — Search %s" % display_name


func interact(player: Node) -> void:
	if _opened:
		return
	_opened = true
	if player.has_method("add_items"):
		player.add_items(loot)
	_dim_meshes(self)


func _dim_meshes(node: Node) -> void:
	# darken the container so searched ones read as empty at a glance
	for child in node.get_children():
		if child is MeshInstance3D:
			var mi := child as MeshInstance3D
			var mat := mi.get_active_material(0)
			if mat is StandardMaterial3D:
				var dup: StandardMaterial3D = mat.duplicate()
				dup.albedo_color = dup.albedo_color.darkened(0.45)
				mi.material_override = dup
		_dim_meshes(child)
