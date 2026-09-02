"""Architecture guard: the isometric presentation must NOT introduce a
tile-authoritative world (ISO no-tiles gate).

Asphodel's world is continuous — real OSM road geometry, arbitrary building
polygons, continuous entity positions. The isometric pivot ("Zomboid readability
without tiles") is allowed to use invisible grids purely as acceleration/lookup
helpers, but must never make a Godot TileMap / TileMapLayer / TileSet the spatial
authority, nor snap authoritative positions to a grid.

This guard is deliberately NARROW so it protects the architecture without tripping
on the word "tile" appearing incidentally: it forbids the concrete Godot tile
*classes* in the renderer scripts and scenes, and asserts the isometric path is
built on the continuous surfaces (ExteriorWorld chunk stream + CharacterBody3D +
authoritative building_id/citizen_id ids).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GODOT = REPO / "godot"
SCRIPTS = GODOT / "scripts"

# Concrete Godot tile classes — their use as nodes/types means tile authority.
FORBIDDEN_TILE_CLASSES = ("TileMap", "TileMapLayer", "TileSet")

ISO_SOURCES = [
    "isometric_world.gd",
    "isometric_camera.gd",
    "isometric_player.gd",
    "isometric_interaction.gd",
    "isometric_highlight.gd",
    "isometric_cutaway.gd",
]


def _gd_scripts() -> list[Path]:
    return sorted(SCRIPTS.glob("*.gd"))


def _scenes() -> list[Path]:
    return sorted(GODOT.glob("*.tscn")) + sorted((GODOT / "tests").glob("*.tscn"))


def test_isometric_sources_exist():
    for name in ISO_SOURCES:
        assert (SCRIPTS / name).exists(), f"missing isometric source {name}"


def test_no_tilemap_classes_in_any_renderer_script():
    """No renderer script (FPS or isometric) uses a tile class as spatial truth."""
    offenders = []
    for path in _gd_scripts():
        text = path.read_text()
        for cls in FORBIDDEN_TILE_CLASSES:
            # word-boundary match on the class identifier
            if re.search(rf"\b{cls}\b", text):
                offenders.append(f"{path.name}: {cls}")
    assert not offenders, (
        "tile-authoritative class(es) found in renderer scripts: "
        + ", ".join(offenders)
    )


def test_no_tilemap_nodes_in_scenes():
    """No scene instantiates a TileMap/TileMapLayer node."""
    offenders = []
    for path in _scenes():
        text = path.read_text()
        for cls in FORBIDDEN_TILE_CLASSES:
            if re.search(rf'type="{cls}"', text) or re.search(rf"\b{cls}\b", text):
                offenders.append(f"{path.name}: {cls}")
    assert not offenders, "tile node(s) found in scenes: " + ", ".join(offenders)


def test_no_tileset_resources_committed():
    """No .tres/.res TileSet resources under the Godot project."""
    offenders = []
    for path in GODOT.rglob("*.tres"):
        text = path.read_text(errors="ignore")
        if "TileSet" in text:
            offenders.append(path.name)
    assert not offenders, "TileSet resource(s) present: " + ", ".join(offenders)


def test_isometric_world_is_built_on_continuous_surfaces():
    """Positive assertion: the isometric world reuses the continuous architecture
    (chunked OSM ExteriorWorld stream, a physical CharacterBody3D player) and
    authoritative ids — not tiles."""
    text = (SCRIPTS / "isometric_world.gd").read_text()
    assert "ExteriorWorld" in text, "isometric world must reuse the continuous chunk stream"
    assert "building_id" in text or "_building_aabb" in text, \
        "isometric world must key buildings by authoritative id, not tile coords"
    player = (SCRIPTS / "isometric_player.gd").read_text()
    assert "extends CharacterBody3D" in player, \
        "the isometric player must be a continuous physical body, not a tile occupant"


def test_no_grid_snapping_of_entity_positions():
    """The isometric scripts must not snap authoritative/world positions to a grid
    (no `snapped(` on positions). Invisible acceleration grids are fine, but they
    resolve back to continuous positions — so `snapped(` should not appear at all
    in the isometric presentation scripts."""
    offenders = []
    for name in ISO_SOURCES:
        text = (SCRIPTS / name).read_text()
        if re.search(r"\bsnapped\s*\(", text):
            offenders.append(name)
    assert not offenders, (
        "grid snapping of positions found in isometric scripts: " + ", ".join(offenders)
    )
