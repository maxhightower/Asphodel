extends RefCounted
## Procedural interior furniture meshes (Package F). Recognizable multi-part
## shapes so a room reads as a living room / bedroom / kitchen / bathroom / etc.
## without any label. One shared vertex-coloured material; meshes are cached and
## drawn via MultiMesh-friendly MeshInstances by interior_builder.gd.
##
## Convention: 1 unit = 1 m, +Y up, pivot on the FLOOR (base at y=0), forward
## (rotation.y = facing) along +Z. Serves both authoritative fixtures (cabinet,
## fridge, shelf, desk, counter, crate) and decorative furniture.

static var _cache: Dictionary = {}
static var _mat: StandardMaterial3D = null


static func _material() -> StandardMaterial3D:
	if _mat == null:
		_mat = StandardMaterial3D.new()
		_mat.vertex_color_use_as_albedo = true
		_mat.roughness = 0.9
		_mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	return _mat


## Footprint/height used by the placement layer (metres). Kept in sync with the
## builders below; interior_builder reads this for clearance.
const FOOTPRINT := {
	"sofa": Vector3(2.0, 0.85, 0.9), "armchair": Vector3(0.95, 0.9, 0.95),
	"coffee_table": Vector3(1.1, 0.42, 0.6), "side_table": Vector3(0.5, 0.55, 0.5),
	"tv": Vector3(1.2, 0.75, 0.35), "bookshelf": Vector3(1.2, 1.9, 0.4),
	"bed": Vector3(1.5, 0.9, 2.0), "nightstand": Vector3(0.5, 0.55, 0.45),
	"dresser": Vector3(1.2, 0.9, 0.55), "wardrobe": Vector3(1.2, 2.0, 0.6),
	"desk": Vector3(1.4, 0.78, 0.7), "chair": Vector3(0.5, 0.9, 0.5),
	"table": Vector3(1.5, 0.76, 1.0), "counter": Vector3(1.8, 0.9, 0.65),
	"stove": Vector3(0.76, 0.92, 0.68), "fridge": Vector3(0.8, 1.8, 0.75),
	"sink": Vector3(0.7, 0.9, 0.6), "microwave": Vector3(0.55, 0.34, 0.4),
	"toilet": Vector3(0.6, 0.8, 0.72), "bathtub": Vector3(1.7, 0.6, 0.8),
	"shower": Vector3(1.0, 2.1, 1.0), "vanity": Vector3(1.0, 1.6, 0.55),
	"washer": Vector3(0.65, 0.9, 0.65), "dryer": Vector3(0.65, 0.9, 0.65),
	"water_heater": Vector3(0.6, 1.5, 0.6), "workbench": Vector3(1.8, 0.95, 0.7),
	"tool_cabinet": Vector3(0.9, 1.4, 0.5), "shelf": Vector3(1.0, 1.8, 0.4),
	"crate": Vector3(0.8, 0.8, 0.8), "cabinet": Vector3(0.9, 0.9, 0.5),
	"rack": Vector3(1.2, 1.8, 0.5), "display": Vector3(1.0, 1.0, 1.0),
	"bench": Vector3(1.6, 0.5, 0.45), "sideboard": Vector3(1.4, 0.9, 0.5),
	"stool": Vector3(0.42, 0.75, 0.42), "lamp": Vector3(0.4, 1.6, 0.4),
	"tv_stand": Vector3(1.4, 0.5, 0.4),
	# --- workplace (Package G) ---
	"gondola": Vector3(1.8, 1.6, 0.9), "checkout": Vector3(1.6, 1.0, 0.9),
	"fridge_case": Vector3(1.8, 2.0, 0.8), "freezer_case": Vector3(1.8, 0.9, 0.9),
	"cubicle": Vector3(1.6, 1.3, 1.6), "filing_cabinet": Vector3(0.5, 1.3, 0.6),
	"printer": Vector3(0.6, 0.9, 0.6), "water_cooler": Vector3(0.4, 1.3, 0.4),
	"hospital_bed": Vector3(1.0, 1.0, 2.1), "exam_table": Vector3(0.8, 0.8, 1.9),
	"iv_pole": Vector3(0.4, 1.9, 0.4), "med_cart": Vector3(0.6, 1.0, 0.5),
	"monitor": Vector3(0.5, 1.5, 0.5), "locker": Vector3(1.2, 1.9, 0.5),
	"drum": Vector3(0.6, 0.9, 0.6), "forklift": Vector3(1.2, 2.1, 2.4),
	"machine": Vector3(1.6, 1.6, 1.2), "pallet_rack": Vector3(2.0, 2.4, 0.9),
	"student_desk": Vector3(0.7, 0.75, 0.9), "teacher_desk": Vector3(1.5, 0.78, 0.75),
	"chalkboard": Vector3(2.4, 1.5, 0.15), "library_shelf": Vector3(1.6, 2.0, 0.5),
	"cafeteria_table": Vector3(2.4, 0.78, 1.4), "lectern": Vector3(0.6, 1.2, 0.5),
	"pew": Vector3(2.2, 0.9, 0.5),
}

const SUPPORTED := [
	"sofa", "armchair", "coffee_table", "side_table", "tv", "tv_stand",
	"bookshelf", "bed", "nightstand", "dresser", "wardrobe", "desk", "chair",
	"table", "counter", "stove", "fridge", "sink", "microwave", "toilet",
	"bathtub", "shower", "vanity", "washer", "dryer", "water_heater",
	"workbench", "tool_cabinet", "shelf", "crate", "cabinet", "rack",
	"display", "bench", "sideboard", "stool", "lamp",
	"gondola", "checkout", "fridge_case", "freezer_case", "cubicle",
	"filing_cabinet", "printer", "water_cooler", "hospital_bed", "exam_table",
	"iv_pole", "med_cart", "monitor", "locker", "drum", "forklift", "machine",
	"pallet_rack", "student_desk", "teacher_desk", "chalkboard",
	"library_shelf", "cafeteria_table", "lectern", "pew",
]


static func footprint(kind: String) -> Vector3:
	return FOOTPRINT.get(kind, Vector3(0.8, 0.8, 0.6))


static func is_supported(kind: String) -> bool:
	return kind in SUPPORTED


static func get_mesh(kind: String, variant: int = 0) -> Mesh:
	var key := "%s:%d" % [kind, variant]
	if _cache.has(key):
		return _cache[key]
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	_build(st, kind, variant)
	st.generate_normals()
	var mesh := st.commit()
	mesh.surface_set_material(0, _material())
	_cache[key] = mesh
	return mesh


# ------------------------------------------------------------------ geometry
static func _b(st: SurfaceTool, cx: float, cy: float, cz: float,
		sx: float, sy: float, sz: float, col: Color) -> void:
	st.set_color(col)
	var hx := sx * 0.5; var hy := sy * 0.5; var hz := sz * 0.5
	var c := Vector3(cx, cy, cz)
	var v := [
		c + Vector3(-hx, -hy, -hz), c + Vector3(hx, -hy, -hz),
		c + Vector3(hx, -hy, hz), c + Vector3(-hx, -hy, hz),
		c + Vector3(-hx, hy, -hz), c + Vector3(hx, hy, -hz),
		c + Vector3(hx, hy, hz), c + Vector3(-hx, hy, hz)]
	var faces := [[0, 1, 2, 3], [7, 6, 5, 4], [4, 5, 1, 0],
		[6, 7, 3, 2], [5, 6, 2, 1], [7, 4, 0, 3]]
	for f in faces:
		for idx in [f[0], f[1], f[2], f[0], f[2], f[3]]:
			st.add_vertex(v[idx])


static func _legs(st: SurfaceTool, sx: float, sz: float, top_y: float,
		inset: float, col: Color) -> void:
	var lx := sx * 0.5 - inset
	var lz := sz * 0.5 - inset
	for ex in [-lx, lx]:
		for ez in [-lz, lz]:
			_b(st, ex, top_y * 0.5, ez, 0.07, top_y, 0.07, col)


# palettes
const WOOD := Color(0.52, 0.38, 0.24)
const WOOD_D := Color(0.40, 0.29, 0.18)
const FABRIC := Color(0.40, 0.46, 0.55)
const METAL := Color(0.60, 0.62, 0.66)
const WHITE := Color(0.90, 0.91, 0.93)
const DARK := Color(0.14, 0.14, 0.16)


static func _build(st: SurfaceTool, kind: String, variant: int) -> void:
	match kind:
		"sofa":
			var f: Color = [FABRIC, Color(0.5, 0.42, 0.38), Color(0.36, 0.5, 0.44)][variant % 3]
			_b(st, 0, 0.2, 0, 2.0, 0.4, 0.9, f)             # base
			_b(st, 0, 0.45, 0, 1.7, 0.22, 0.7, f.lightened(0.06))  # seat cushions
			_b(st, 0, 0.55, -0.36, 2.0, 0.55, 0.18, f)      # backrest
			_b(st, -0.94, 0.42, 0, 0.12, 0.5, 0.9, f.darkened(0.05))  # arms
			_b(st, 0.94, 0.42, 0, 0.12, 0.5, 0.9, f.darkened(0.05))
		"armchair":
			var f2: Color = [FABRIC, Color(0.5, 0.42, 0.38)][variant % 2]
			_b(st, 0, 0.2, 0, 0.9, 0.4, 0.9, f2)
			_b(st, 0, 0.45, 0, 0.7, 0.2, 0.7, f2.lightened(0.06))
			_b(st, 0, 0.6, -0.36, 0.9, 0.6, 0.16, f2)
			_b(st, -0.42, 0.42, 0, 0.1, 0.5, 0.9, f2.darkened(0.05))
			_b(st, 0.42, 0.42, 0, 0.1, 0.5, 0.9, f2.darkened(0.05))
		"coffee_table":
			_b(st, 0, 0.4, 0, 1.1, 0.06, 0.6, WOOD)
			_legs(st, 1.1, 0.6, 0.38, 0.1, WOOD_D)
		"side_table":
			_b(st, 0, 0.53, 0, 0.5, 0.05, 0.5, WOOD)
			_legs(st, 0.5, 0.5, 0.5, 0.08, WOOD_D)
		"tv":
			_b(st, 0, 0.5, 0.02, 1.2, 0.68, 0.06, DARK)     # screen
			_b(st, 0, 0.1, 0, 0.4, 0.2, 0.2, DARK.lightened(0.1))  # stand
		"tv_stand":
			_b(st, 0, 0.25, 0, 1.4, 0.5, 0.4, WOOD)
			_b(st, 0, 0.5, 0.05, 1.0, 0.5, 0.05, DARK)      # small tv on top
		"bookshelf", "shelf", "rack":
			var body: Color = WOOD if kind != "rack" else METAL
			_b(st, -0.55, 0.9, 0, 0.08, 1.8, 0.4, body.darkened(0.05))
			_b(st, 0.55, 0.9, 0, 0.08, 1.8, 0.4, body.darkened(0.05))
			_b(st, 0, 0.9, -0.18, 1.18, 1.8, 0.05, body.darkened(0.12))
			for i in range(4):
				var sy := 0.25 + float(i) * 0.5
				_b(st, 0, sy, 0, 1.1, 0.05, 0.38, body)
		"bed":
			var q: Color = [Color(0.7, 0.72, 0.8), Color(0.55, 0.4, 0.45), Color(0.4, 0.5, 0.6)][variant % 3]
			_b(st, 0, 0.2, 0, 1.5, 0.35, 2.0, WOOD_D)       # frame
			_b(st, 0, 0.45, 0.1, 1.42, 0.2, 1.8, q)          # mattress/duvet
			_b(st, 0, 0.55, -0.82, 1.4, 0.35, 0.3, WHITE)    # pillows
			_b(st, 0, 0.7, -1.0, 1.5, 0.7, 0.08, WOOD)       # headboard
		"nightstand":
			_b(st, 0, 0.27, 0, 0.5, 0.54, 0.45, WOOD)
			_b(st, 0, 0.35, 0.23, 0.4, 0.12, 0.03, WOOD_D)   # drawer face
		"dresser":
			_b(st, 0, 0.44, 0, 1.2, 0.88, 0.55, WOOD)
			for i in range(3):
				_b(st, 0, 0.2 + float(i) * 0.26, 0.28, 1.05, 0.2, 0.03, WOOD_D)
		"wardrobe":
			_b(st, 0, 1.0, 0, 1.2, 2.0, 0.6, WOOD)
			_b(st, -0.01, 1.0, 0.31, 0.04, 1.9, 0.02, WOOD_D)  # door split
		"desk":
			_b(st, 0, 0.74, 0, 1.4, 0.06, 0.7, WOOD)
			_b(st, 0.55, 0.36, 0, 0.5, 0.72, 0.62, WOOD.darkened(0.05))  # drawer pedestal
			_b(st, -0.62, 0.36, 0, 0.06, 0.72, 0.62, WOOD_D)             # left panel
		"chair":
			_b(st, 0, 0.45, 0, 0.44, 0.06, 0.44, WOOD)
			_b(st, 0, 0.68, -0.19, 0.44, 0.46, 0.05, WOOD)
			_legs(st, 0.44, 0.44, 0.45, 0.05, WOOD_D)
		"stool":
			_b(st, 0, 0.72, 0, 0.4, 0.05, 0.4, WOOD)
			_legs(st, 0.4, 0.4, 0.72, 0.05, WOOD_D)
		"table":
			_b(st, 0, 0.74, 0, 1.5, 0.06, 1.0, WOOD)
			_legs(st, 1.5, 1.0, 0.72, 0.12, WOOD_D)
		"counter":
			_b(st, 0, 0.42, 0, 1.8, 0.84, 0.65, Color(0.72, 0.66, 0.56))  # cabinet
			_b(st, 0, 0.88, 0, 1.86, 0.06, 0.68, Color(0.32, 0.33, 0.36)) # countertop
		"sideboard":
			_b(st, 0, 0.45, 0, 1.4, 0.86, 0.5, WOOD)
			_b(st, 0, 0.92, 0, 1.44, 0.04, 0.52, WOOD_D)
		"stove":
			_b(st, 0, 0.44, 0, 0.76, 0.88, 0.68, Color(0.85, 0.86, 0.88))
			_b(st, 0, 0.9, 0, 0.74, 0.04, 0.66, DARK)         # cooktop
			for ex in [-0.18, 0.18]:
				for ez in [-0.16, 0.16]:
					_b(st, ex, 0.93, ez, 0.18, 0.02, 0.18, DARK.lightened(0.08))  # burners
			_b(st, 0, 0.35, 0.35, 0.6, 0.5, 0.03, Color(0.3, 0.3, 0.34))  # oven door
		"fridge":
			_b(st, 0, 0.9, 0, 0.8, 1.8, 0.75, WHITE)
			_b(st, 0, 1.2, 0.38, 0.76, 0.02, 0.02, METAL)     # split line
			_b(st, 0.3, 1.35, 0.39, 0.05, 0.4, 0.04, METAL)   # handle
		"sink":
			_b(st, 0, 0.42, 0, 0.7, 0.84, 0.6, Color(0.7, 0.66, 0.58))
			_b(st, 0, 0.86, 0, 0.72, 0.08, 0.62, WHITE)
			_b(st, 0, 0.9, -0.18, 0.06, 0.2, 0.06, METAL)     # faucet
		"microwave":
			_b(st, 0, 0.17, 0, 0.55, 0.34, 0.4, Color(0.2, 0.2, 0.22))
			_b(st, -0.05, 0.17, 0.21, 0.36, 0.24, 0.02, Color(0.1, 0.12, 0.16))
		"toilet":
			_b(st, 0, 0.2, 0.05, 0.42, 0.4, 0.55, WHITE)      # bowl base
			_b(st, 0, 0.42, 0.08, 0.46, 0.12, 0.5, WHITE.lightened(0.02))  # seat
			_b(st, 0, 0.55, -0.28, 0.5, 0.5, 0.2, WHITE)      # tank
		"bathtub":
			_b(st, 0, 0.3, 0, 1.7, 0.6, 0.8, WHITE)
			_b(st, 0, 0.5, 0, 1.5, 0.25, 0.6, Color(0.8, 0.85, 0.9))  # inner
		"shower":
			_b(st, 0, 0.05, 0, 1.0, 0.1, 1.0, Color(0.8, 0.82, 0.85))  # base
			_b(st, -0.48, 1.05, 0, 0.04, 2.0, 1.0, Color(0.75, 0.82, 0.86))  # panels
			_b(st, 0, 1.05, -0.48, 1.0, 2.0, 0.04, Color(0.75, 0.82, 0.86))
		"vanity":
			_b(st, 0, 0.42, 0, 1.0, 0.84, 0.5, WOOD)
			_b(st, 0, 0.86, 0, 1.04, 0.06, 0.52, WHITE)
			_b(st, 0, 1.3, -0.22, 0.8, 0.6, 0.04, Color(0.7, 0.8, 0.85))  # mirror
		"washer", "dryer":
			var wc := WHITE if kind == "washer" else Color(0.86, 0.87, 0.9)
			_b(st, 0, 0.45, 0, 0.65, 0.9, 0.65, wc)
			_b(st, 0, 0.5, 0.33, 0.4, 0.4, 0.03, Color(0.3, 0.35, 0.4))  # round-ish door
			_b(st, 0, 0.85, -0.2, 0.6, 0.08, 0.2, wc.darkened(0.1))      # control panel
		"water_heater":
			_cyl(st, 0.3, 1.5, 12, METAL.lightened(0.05))
			_b(st, 0, 1.5, 0, 0.5, 0.06, 0.5, METAL.darkened(0.1))
		"workbench":
			_b(st, 0, 0.9, 0, 1.8, 0.08, 0.7, WOOD_D)
			_legs(st, 1.8, 0.7, 0.86, 0.12, DARK)
			_b(st, 0, 1.4, -0.32, 1.8, 0.9, 0.04, Color(0.5, 0.52, 0.55))  # pegboard
		"tool_cabinet":
			_b(st, 0, 0.7, 0, 0.9, 1.4, 0.5, Color(0.55, 0.15, 0.12))
			for i in range(5):
				_b(st, 0, 0.25 + float(i) * 0.25, 0.26, 0.8, 0.16, 0.02, DARK)
		"cabinet":
			_b(st, 0, 0.45, 0, 0.9, 0.9, 0.5, WOOD)
			_b(st, -0.01, 0.45, 0.26, 0.03, 0.84, 0.02, WOOD_D)
		"crate":
			_b(st, 0, 0.4, 0, 0.8, 0.8, 0.8, WOOD)
			for e in [-0.4, 0.4]:
				_b(st, 0, 0.4, e, 0.82, 0.1, 0.04, WOOD_D)
		"display":
			_b(st, 0, 0.45, 0, 1.0, 0.9, 1.0, Color(0.7, 0.75, 0.8))
			_b(st, 0, 0.95, 0, 0.96, 0.1, 0.96, Color(0.5, 0.6, 0.68))
		"bench":
			_b(st, 0, 0.45, 0, 1.6, 0.06, 0.42, WOOD)
			_legs(st, 1.6, 0.42, 0.44, 0.1, DARK)
		"lamp":
			_b(st, 0, 0.75, 0, 0.05, 1.5, 0.05, DARK)
			_b(st, 0, 1.5, 0, 0.4, 0.3, 0.4, Color(0.9, 0.85, 0.6))  # shade
		# ---- retail ----
		"gondola":
			_b(st, 0, 0.8, 0, 1.8, 1.6, 0.9, METAL)
			_b(st, 0, 0.8, 0, 0.06, 1.6, 0.9, METAL.darkened(0.15))  # centre spine
			var goods: Color = [Color(0.7, 0.4, 0.3), Color(0.4, 0.6, 0.7), Color(0.8, 0.7, 0.4)][variant % 3]
			for i in range(3):
				var gy := 0.5 + float(i) * 0.45
				for sgn in [-1.0, 1.0]:
					_b(st, 0, gy - 0.06, sgn * 0.23, 1.7, 0.05, 0.4, METAL.darkened(0.1))
					_b(st, 0, gy + 0.12, sgn * 0.28, 1.6, 0.28, 0.32, goods)  # merchandise
		"checkout":
			_b(st, 0, 0.45, 0, 1.6, 0.9, 0.9, Color(0.55, 0.57, 0.6))
			_b(st, 0, 0.92, 0, 1.64, 0.06, 0.94, DARK.lightened(0.1))
			_b(st, 0.5, 1.1, 0, 0.35, 0.3, 0.3, Color(0.2, 0.22, 0.26))   # register
			_b(st, 0.5, 1.28, -0.1, 0.3, 0.22, 0.03, Color(0.2, 0.5, 0.6))  # screen
		"fridge_case":
			_b(st, 0, 1.0, 0, 1.8, 2.0, 0.8, Color(0.8, 0.82, 0.85))
			_b(st, 0, 1.1, 0.36, 1.6, 1.6, 0.05, Color(0.6, 0.75, 0.82, 1.0))  # glass front
			for i in range(3):
				_b(st, 0, 0.5 + float(i) * 0.55, 0.1, 1.6, 0.05, 0.6, Color(0.75, 0.5, 0.4))
		"freezer_case":
			_b(st, 0, 0.45, 0, 1.8, 0.9, 0.9, Color(0.78, 0.82, 0.86))
			_b(st, 0, 0.92, 0, 1.6, 0.06, 0.7, Color(0.7, 0.85, 0.92, 1.0))  # glass top
		# ---- office ----
		"cubicle":
			_b(st, 0, 0.74, 0.5, 1.5, 0.05, 0.6, WOOD)                # desk
			_b(st, 0, 0.6, -0.2, 1.6, 1.2, 0.05, Color(0.5, 0.55, 0.5))  # back panel
			_b(st, -0.78, 0.6, 0.4, 0.05, 1.2, 1.4, Color(0.5, 0.55, 0.5))  # side panel
			_b(st, 0.3, 0.9, 0.4, 0.4, 0.28, 0.05, DARK)             # monitor
		"filing_cabinet":
			_b(st, 0, 0.65, 0, 0.5, 1.3, 0.6, Color(0.5, 0.52, 0.55))
			for i in range(4):
				_b(st, 0, 0.25 + float(i) * 0.3, 0.31, 0.42, 0.22, 0.02, DARK)
		"printer":
			_b(st, 0, 0.45, 0, 0.6, 0.5, 0.6, Color(0.3, 0.32, 0.35))  # base cabinet
			_b(st, 0, 0.78, 0, 0.56, 0.35, 0.56, Color(0.85, 0.86, 0.88))  # printer body
		"water_cooler":
			_b(st, 0, 0.5, 0, 0.35, 1.0, 0.35, WHITE)
			_cyl(st, 0.16, 0.4, 10, Color(0.6, 0.78, 0.85, 1.0))      # bottle
			_b(st, 0, 1.3, 0, 0.34, 0.4, 0.34, Color(0.6, 0.78, 0.85))
		# ---- clinic / medical ----
		"hospital_bed":
			_b(st, 0, 0.55, 0, 1.0, 0.2, 2.1, METAL)                  # frame
			_b(st, 0, 0.68, 0.1, 0.92, 0.14, 1.9, Color(0.7, 0.78, 0.82))  # mattress
			_b(st, 0, 0.55, -1.0, 1.0, 0.5, 0.06, METAL.lightened(0.1))    # head rail
			_b(st, 0, 0.9, -0.85, 0.9, 0.45, 0.08, Color(0.75, 0.8, 0.84)) # raised head
			for sgn in [-1.0, 1.0]:
				_b(st, sgn * 0.48, 0.85, 0.3, 0.05, 0.4, 1.0, METAL.lightened(0.1))  # side rails
		"exam_table":
			_b(st, 0, 0.55, 0, 0.8, 0.6, 1.9, Color(0.6, 0.62, 0.66))
			_b(st, 0, 0.9, 0, 0.76, 0.12, 1.85, Color(0.35, 0.5, 0.6))  # padded top
		"iv_pole":
			_cyl(st, 0.03, 1.7, 6, METAL)
			_b(st, 0.12, 1.7, 0, 0.28, 0.04, 0.04, METAL)
			_b(st, 0.24, 1.5, 0, 0.14, 0.28, 0.06, Color(0.8, 0.85, 0.8, 1.0))  # bag
		"med_cart":
			_b(st, 0, 0.5, 0, 0.6, 0.9, 0.5, Color(0.85, 0.7, 0.3))   # coloured drawers
			for i in range(4):
				_b(st, 0, 0.2 + float(i) * 0.22, 0.26, 0.54, 0.16, 0.02, DARK)
			_b(st, 0, 0.96, 0, 0.62, 0.04, 0.52, WHITE)
		"monitor":
			_cyl(st, 0.03, 1.2, 6, METAL)
			_b(st, 0, 1.35, 0, 0.4, 0.3, 0.12, DARK)
			_b(st, 0, 1.35, 0.07, 0.34, 0.24, 0.02, Color(0.15, 0.4, 0.3))
		# ---- industrial ----
		"locker":
			_b(st, 0, 0.95, 0, 1.2, 1.9, 0.5, Color(0.4, 0.5, 0.6))
			for i in range(3):
				_b(st, -0.4 + float(i) * 0.4, 0.95, 0.26, 0.03, 1.85, 0.02, DARK)  # door splits
		"drum":
			_cyl(st, 0.28, 0.9, 12, [Color(0.2, 0.35, 0.5), Color(0.5, 0.3, 0.2), Color(0.3, 0.45, 0.3)][variant % 3])
			_b(st, 0, 0.9, 0, 0.58, 0.05, 0.58, DARK)
		"forklift":
			_b(st, 0, 0.6, -0.3, 1.1, 1.0, 1.6, Color(0.85, 0.6, 0.1))  # body
			_b(st, 0, 1.5, -0.6, 1.0, 1.2, 0.1, Color(0.3, 0.3, 0.33))  # mast
			_b(st, 0, 0.15, 0.7, 0.9, 0.1, 0.9, DARK)                   # forks
			for sgn in [-1.0, 1.0]:
				_cyl_at(st, sgn * 0.5, -0.9, 0.28, 0.2, DARK)           # wheels
		"machine":
			_b(st, 0, 0.8, 0, 1.6, 1.6, 1.2, Color(0.45, 0.48, 0.52))
			_b(st, 0, 1.7, 0, 0.4, 0.4, 0.4, Color(0.55, 0.2, 0.15))    # motor housing
			_cyl_at(st, 0.6, 0, 0.08, 1.2, METAL)                       # pipe
		"pallet_rack":
			for sgn in [-1.0, 1.0]:
				_b(st, sgn * 0.95, 1.2, 0, 0.1, 2.4, 0.9, Color(0.75, 0.4, 0.2))  # uprights
			for i in range(3):
				_b(st, 0, 0.05 + float(i) * 1.1, 0, 1.9, 0.08, 0.85, Color(0.6, 0.32, 0.16))  # beams
				_b(st, 0, 0.35 + float(i) * 1.1, 0, 1.7, 0.5, 0.75, WOOD.darkened(0.05))       # pallet load
		# ---- school / civic ----
		"student_desk":
			_b(st, 0, 0.72, 0.1, 0.7, 0.05, 0.5, Color(0.8, 0.78, 0.6))
			_legs(st, 0.7, 0.5, 0.72, 0.06, METAL)
			_b(st, 0, 0.42, -0.28, 0.42, 0.04, 0.4, WOOD)              # attached seat
			_b(st, 0, 0.62, -0.46, 0.42, 0.35, 0.04, WOOD)            # seat back
		"teacher_desk":
			_b(st, 0, 0.76, 0, 1.5, 0.06, 0.75, WOOD)
			_b(st, -0.55, 0.38, 0, 0.4, 0.72, 0.7, WOOD.darkened(0.05))
			_b(st, 0, 0.4, 0.34, 1.5, 0.7, 0.05, WOOD.darkened(0.08))  # modesty panel
		"chalkboard":
			_b(st, 0, 1.4, 0, 2.4, 1.3, 0.08, Color(0.16, 0.28, 0.22))
			_b(st, 0, 0.75, 0.06, 2.4, 0.08, 0.12, WOOD)              # chalk tray
		"library_shelf":
			_b(st, -0.75, 1.0, 0, 0.1, 2.0, 0.5, WOOD.darkened(0.05))
			_b(st, 0.75, 1.0, 0, 0.1, 2.0, 0.5, WOOD.darkened(0.05))
			_b(st, 0, 1.0, -0.23, 1.6, 2.0, 0.05, WOOD.darkened(0.12))
			for i in range(5):
				_b(st, 0, 0.25 + float(i) * 0.42, 0, 1.5, 0.05, 0.46, WOOD)
				_b(st, 0, 0.42 + float(i) * 0.42, 0, 1.4, 0.28, 0.4,
					[Color(0.5, 0.3, 0.3), Color(0.3, 0.4, 0.5), Color(0.4, 0.5, 0.35)][i % 3])  # books
		"cafeteria_table":
			_b(st, 0, 0.76, 0, 2.4, 0.06, 0.7, Color(0.7, 0.72, 0.66))
			_legs(st, 2.4, 0.7, 0.72, 0.12, METAL)
			for sgn in [-1.0, 1.0]:
				_b(st, 0, 0.45, sgn * 0.55, 2.4, 0.05, 0.3, Color(0.55, 0.58, 0.5))  # benches
		"lectern":
			_b(st, 0, 0.55, 0, 0.5, 1.1, 0.4, WOOD)
			_b(st, 0, 1.15, 0.05, 0.55, 0.08, 0.4, WOOD.darkened(0.08))  # slanted top
		"pew":
			_b(st, 0, 0.45, 0, 2.2, 0.06, 0.42, WOOD)
			_b(st, 0, 0.7, -0.18, 2.2, 0.5, 0.05, WOOD)
			for ex in [-1.0, 1.0]:
				_b(st, ex, 0.22, 0, 0.08, 0.45, 0.42, WOOD.darkened(0.08))
		_:
			_b(st, 0, 0.4, 0, 0.7, 0.8, 0.6, Color(1.0, 0.0, 1.0))   # magenta unknown


static func _cyl_at(st: SurfaceTool, cx: float, cz: float, r: float, h: float,
		col: Color) -> void:
	st.set_color(col)
	for i in range(10):
		var a0 := TAU * float(i) / 10.0
		var a1 := TAU * float(i + 1) / 10.0
		var p0 := Vector3(cx + cos(a0) * r, 0, cz + sin(a0) * r)
		var p1 := Vector3(cx + cos(a1) * r, 0, cz + sin(a1) * r)
		var u0 := p0 + Vector3(0, h, 0)
		var u1 := p1 + Vector3(0, h, 0)
		for vtx in [p0, p1, u1, p0, u1, u0]:
			st.add_vertex(vtx)


static func _cyl(st: SurfaceTool, r: float, h: float, seg: int, col: Color) -> void:
	st.set_color(col)
	for i in range(seg):
		var a0 := TAU * float(i) / seg
		var a1 := TAU * float(i + 1) / seg
		var p0 := Vector3(cos(a0) * r, 0, sin(a0) * r)
		var p1 := Vector3(cos(a1) * r, 0, sin(a1) * r)
		var u0 := p0 + Vector3(0, h, 0)
		var u1 := p1 + Vector3(0, h, 0)
		for vtx in [p0, p1, u1, p0, u1, u0]:
			st.add_vertex(vtx)
		st.add_vertex(Vector3(0, h, 0)); st.add_vertex(u0); st.add_vertex(u1)
