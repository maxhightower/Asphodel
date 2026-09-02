"""Internal record types passed between exterior-compiler stages.

These are compile-time only (never serialized as-is); the on-disk contract
is the chunk JSON in schema.py.  Geometry fields hold shapely objects in
the bundle metre frame (x=east, z=north).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RoadSegment:
    key: str                 # stable source key (GERS)
    pts: list                # [(x, z), ...] centerline
    cls: str                 # normalized class (motorway..service, footway..)
    carriage_w: float        # full carriageway width, metres
    lanes: int
    sidewalk_w: float        # per-side; 0 when none
    verge_w: float           # per-side grass verge; 0 when none
    curb: bool
    markings: str            # "dashed_center" | "solid_lanes" | "none"
    elevated: bool = False   # render as elevated deck (motorway/trunk)
    path_only: bool = False  # footway/cycleway/path: no carriageway
    observed_width: bool = False  # carriage_w came from source data


@dataclass
class Parcel:
    pid: str                 # deterministic parcel id
    poly: object             # shapely Polygon (exterior may have holes)
    arch: str                # PARCEL_ARCHETYPES member
    obs: str                 # OBSERVED (real parcel data) | DERIVED (inferred)
    block_id: int
    frontage: list = field(default_factory=list)   # [((x0,z0),(x1,z1)), ...]
    road_key: str | None = None                    # nearest frontage road
    building_bids: list = field(default_factory=list)


@dataclass
class BuildingRecord:
    bid: int                 # bundle-local authoritative building id
    key: str                 # stable geographic key (GERS or derived)
    poly: object             # shapely Polygon footprint
    h: float                 # metres
    floors: int
    arch: str                # BUILDING_ARCHETYPES member
    roof: str                # "flat" | "pitched"
    entrance_edge: int       # index into exterior ring edges
    entrance_t: float        # 0..1 along that edge
    entrance_w: float
    entrance_xy: tuple       # point just OUTSIDE the footprint at entrance
    feat: list = field(default_factory=list)       # BUILDING_FEATURES subset
    parcel_id: str | None = None
    height_observed: bool = False
    # Package B: BuildingAppearanceV1.to_dict() — facade/roof colour+material+
    # shape with OBSERVED/DERIVED/PROCEDURAL provenance. None until assembled.
    appearance: dict | None = None
    # Package H: BusinessIdentityV1.to_dict() for non-residential buildings —
    # fictional name/category/palette/sign_family (always PROCEDURAL). None for
    # residential and until assigned.
    identity: dict | None = None


@dataclass
class Placement:
    kind: str
    x: float
    z: float
    rot: float               # degrees
    variant: int = 0
    cat: str = "prop"        # "prop" | "vehicle" | "tree"


@dataclass
class SurfacePatch:
    """A polygon painted into the semantic raster at a given priority.

    Priority bands (higher paints later / wins):
      10 base land, 20 land_cover/land_use refinement, 30 water,
      40 parcel ground, 50 parking/driveway/walkway aprons,
      60 road verge, 65 sidewalk, 70 carriageway, 90 building.
    """

    poly: object             # shapely Polygon/MultiPolygon
    surface: str             # SURFACE_TYPES member
    priority: int


@dataclass
class Anchor:
    kind: str                # ANCHOR_KINDS member
    x: float
    z: float
    bid: int = -1            # owning building id, -1 when none
