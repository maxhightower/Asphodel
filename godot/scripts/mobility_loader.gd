class_name MobilityLoader
extends RefCounted

## Mobility graph realization seam (AS-NAV-0, §5).
##
## Loads mobility.json (baked by asphodel.region_bundle) into a routable directed
## graph and routes with Dijkstra over current dynamic costs, honouring per-mode
## access and runtime obstructions/closures — the same authority the Python
## MobilityGraph implements. The engine uses this for vehicle/pedestrian routing
## and for reacting to wrecks (a MobilityObstruction closes a segment, routes
## reroute, clearing it restores them).
##
## NOTE: authored seam — mirrors asphodel/mobility/graph.py; not run in-editor here.

var nodes := {}          # id -> Vector2 (x, z)
var segments := {}       # id -> Dictionary(u, v, class, length, modes, oneway)
var _adj := {}           # node -> Array of [to_node, seg_id]
var _closed := {}        # seg_id -> Array of closed mode strings
var _congestion := {}    # seg_id -> float


func load_mobility(dir_path: String) -> bool:
	var path := dir_path.path_join("mobility.json")
	if not FileAccess.file_exists(path):
		push_error("mobility.json missing: %s" % path)
		return false
	var m: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not (m is Dictionary):
		return false
	for nid in m["nodes"]:
		var p: Array = m["nodes"][nid]
		nodes[nid] = Vector2(p[0], p[1])
		_adj[nid] = []
	for seg in m["segments"]:
		segments[seg["id"]] = seg
		_congestion[seg["id"]] = 1.0
		var u: String = seg["u"]; var v: String = seg["v"]
		var one: bool = String(seg["directionality"]) == "forward"
		_adj[u].append([v, seg["id"]])
		if not one:
			_adj[v].append([u, seg["id"]])
	return true


func close_segment(seg_id: String, modes: Array) -> void:
	_closed[seg_id] = modes            # a MobilityObstruction closing the segment

func open_segment(seg_id: String) -> void:
	_closed.erase(seg_id)

func set_congestion(seg_id: String, factor: float) -> void:
	_congestion[seg_id] = max(1.0, factor)


func _cost(seg_id: String, mode: String) -> float:
	var seg: Dictionary = segments[seg_id]
	if not (mode in seg["modes"]):
		return INF
	if _closed.has(seg_id) and (mode in _closed[seg_id]):
		return INF
	return float(seg["length"]) * _congestion.get(seg_id, 1.0)


func route(origin: String, dest: String, mode: String) -> Array:
	# Returns an Array of node ids (empty if unreachable). Dijkstra.
	if origin == dest:
		return [origin]
	var dist := {origin: 0.0}
	var prev := {}
	var visited := {}
	# Simple priority list (fine for city-scale graphs; swap for a heap if needed).
	var frontier := [[0.0, origin]]
	while frontier.size() > 0:
		frontier.sort_custom(func(a, b): return a[0] < b[0])
		var top: Array = frontier.pop_front()
		var u: String = top[1]
		if visited.has(u):
			continue
		visited[u] = true
		if u == dest:
			break
		for edge in _adj.get(u, []):
			var w: String = edge[0]
			var c := _cost(edge[1], mode)
			if c == INF:
				continue
			var nd: float = dist[u] + c
			if nd < float(dist.get(w, INF)):
				dist[w] = nd
				prev[w] = u
				frontier.append([nd, w])
	if not dist.has(dest):
		return []
	var path := [dest]
	var cur := dest
	while cur != origin:
		cur = prev[cur]
		path.push_front(cur)
	return path
