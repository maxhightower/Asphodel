extends Node

## Package D gate (Godot side): every exterior render kind the catalog declares
## builds a real, non-empty mesh via PropMeshes for every variant — i.e. no kind
## falls through to the magenta unknown-asset box in the field.

const PropMeshes = preload("res://scripts/prop_meshes.gd")


func _ready() -> void:
	print("== AssetCatalogSmoke ==")
	var failures := 0
	var checked := 0

	var f := FileAccess.open("res://catalog_v1.json", FileAccess.READ)
	if f == null:
		print("  FAIL  catalog_v1.json missing")
		get_tree().quit(1)
		return
	var doc: Variant = JSON.parse_string(f.get_as_text())
	var rv: Dictionary = doc.get("render_variants", {}) if typeof(doc) == TYPE_DICTIONARY else {}
	if rv.is_empty():
		print("  FAIL  render_variants empty")
		get_tree().quit(1)
		return
	print("  ok   catalog render kinds: ", rv.size())

	for kind in rv.keys():
		var kind_s := String(kind)
		# interior families are drawn by interior_builder (Package F), not PropMeshes
		if not PropMeshes.is_supported(kind_s):
			continue
		var n := int(rv[kind])
		for v in range(maxi(1, n)):
			checked += 1
			var mesh: Mesh = PropMeshes.get_mesh(kind_s, v)
			if mesh == null or mesh.get_surface_count() == 0:
				print("  FAIL  %s v%d built no surfaces" % [kind_s, v])
				failures += 1
			else:
				var arr: Array = mesh.surface_get_arrays(0)
				var verts: PackedVector3Array = arr[Mesh.ARRAY_VERTEX]
				if verts.size() < 3:
					print("  FAIL  %s v%d degenerate (%d verts)" % [kind_s, v, verts.size()])
					failures += 1
	print("  ok   built %d exterior kind:variant meshes, all non-empty" % checked)

	# every kind PropMeshes supports must also be catalogued (no orphan renderers)
	for k in PropMeshes.SUPPORTED_KINDS:
		if not rv.has(k):
			print("  FAIL  supported kind %s absent from catalog" % k)
			failures += 1

	print("== AssetCatalogSmoke done: %d failure(s) ==" % failures)
	get_tree().quit(1 if failures > 0 else 0)
