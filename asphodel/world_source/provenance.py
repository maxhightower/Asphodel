"""Machine-readable provenance manifest for acquired public data.

Every artifact this package downloads (or fails to download) is recorded
here so that (a) `gate.py` can mechanically block anything commercially
unsafe from ever reaching a shipped bundle, and (b) a human auditing the repo
can see exactly where every polygon/attribute came from without re-reading
code. This module owns the on-disk manifest format; it does not itself
perform any network I/O.
"""
from __future__ import annotations

import json
import os

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MANIFEST_PATH = os.path.join(_REPO_ROOT, "geo", "provenance", "data_sources.json")

# License families -- gate.py treats RESTRICTED and UNKNOWN as commercially
# unsafe for any artifact recorded with status "ok".
LICENSE_FAMILIES = (
    "PUBLIC_DOMAIN",
    "CC0",
    "PERMISSIVE",
    "ODBL",
    "RESTRICTED",
    "UNKNOWN",
)

OVERTURE_PROVIDER = "Overture Maps Foundation"

# theme -> license terms, as documented for Overture's 2026 releases.
# docs.overturemaps.org is unreachable from this environment (blocked by
# egress policy), so these assignments are transcribed from prior knowledge
# and cross-checked against the `sources.list.element.license` field observed
# in the actual downloaded parquet (e.g. "ODbL-1.0" on OSM-derived base/
# buildings/transportation rows) rather than re-fetched -- see license_note.
THEME_LICENSE = {
    "buildings": dict(
        license_family="ODBL",
        license_name="ODbL-1.0",
        attribution="© OpenStreetMap contributors, Overture Maps Foundation",
        share_alike=True,
        license_note=(
            "docs.overturemaps.org is blocked by egress policy in this "
            "environment; ODbL-1.0 confirmed instead from the "
            "sources.list.element.license field present on downloaded rows."
        ),
    ),
    "transportation": dict(
        license_family="ODBL",
        license_name="ODbL-1.0",
        attribution="© OpenStreetMap contributors, Overture Maps Foundation",
        share_alike=True,
        license_note=(
            "docs.overturemaps.org is blocked by egress policy in this "
            "environment; ODbL-1.0 confirmed instead from the "
            "sources.list.element.license field present on downloaded rows."
        ),
    ),
    "base": dict(
        license_family="ODBL",
        license_name="ODbL-1.0",
        attribution="© OpenStreetMap contributors, Overture Maps Foundation",
        share_alike=True,
        license_note=(
            "docs.overturemaps.org is blocked by egress policy in this "
            "environment; ODbL-1.0 confirmed instead from the "
            "sources.list.element.license field present on downloaded rows."
        ),
    ),
    "places": dict(
        license_family="PERMISSIVE",
        license_name="CDLA-Permissive-2.0",
        attribution="Overture Maps Foundation",
        share_alike=False,
        license_note=(
            "docs.overturemaps.org is blocked by egress policy in this "
            "environment; CDLA-Permissive-2.0 is Overture's documented "
            "license for the places theme as of the 2026 releases."
        ),
    ),
}

# commercial use is permitted for all four Overture themes we pull from.
for _v in THEME_LICENSE.values():
    _v["commercial_permitted"] = True

FAILED_SOURCES = [
    dict(
        provider="City of Houston (COHGIS)",
        dataset="Harris County / Houston parcels + land-use",
        theme=None,
        type=None,
        release=None,
        source_url_pattern="https://services.arcgis.com/... , https://cohgis.houstontx.gov/...",
        retrieval_date=None,
        bbox=None,
        license_family="UNKNOWN",
        license_name=None,
        attribution=None,
        commercial_permitted=False,
        share_alike=None,
        sha256=None,
        raw_path=None,
        row_count=None,
        file_size_bytes=None,
        status="unreachable_egress_policy",
        license_note="services.arcgis.com and cohgis.houstontx.gov are blocked by egress policy in this environment.",
        fallback="derived_parcel_inference",
    ),
    dict(
        provider="USGS",
        dataset="3DEP 1m DEM",
        theme=None,
        type=None,
        release=None,
        source_url_pattern="https://tnmaccess.nationalmap.gov/api/v1/products",
        retrieval_date=None,
        bbox=None,
        license_family="UNKNOWN",
        license_name=None,
        attribution=None,
        commercial_permitted=False,
        share_alike=None,
        sha256=None,
        raw_path=None,
        row_count=None,
        file_size_bytes=None,
        status="unreachable_egress_policy",
        license_note="tnmaccess.nationalmap.gov is blocked by egress policy in this environment.",
        fallback="flat_terrain",
    ),
    dict(
        provider="USGS / MRLC",
        dataset="NLCD annual land cover",
        theme=None,
        type=None,
        release=None,
        source_url_pattern="https://www.mrlc.gov/... (served via tnmaccess/ArcGIS endpoints)",
        retrieval_date=None,
        bbox=None,
        license_family="UNKNOWN",
        license_name=None,
        attribution=None,
        commercial_permitted=False,
        share_alike=None,
        sha256=None,
        raw_path=None,
        row_count=None,
        file_size_bytes=None,
        status="unreachable_egress_policy",
        license_note="NLCD endpoints are served through tnmaccess.nationalmap.gov / services.arcgis.com, both blocked by egress policy in this environment.",
        fallback="overture_base_landcover",
    ),
]


def load_manifest() -> dict:
    if not os.path.exists(MANIFEST_PATH):
        return {"artifacts": []}
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def save_manifest(manifest: dict) -> None:
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")


def upsert_artifact(manifest: dict, entry: dict) -> dict:
    """Insert `entry` into `manifest["artifacts"]`, replacing any prior entry
    with the same (provider, dataset/type, release, city/bbox) key."""
    key = (entry.get("provider"), entry.get("type"), entry.get("release"), entry.get("city"))
    artifacts = manifest.setdefault("artifacts", [])
    for i, existing in enumerate(artifacts):
        ekey = (existing.get("provider"), existing.get("type"), existing.get("release"), existing.get("city"))
        if ekey == key:
            artifacts[i] = entry
            return manifest
    artifacts.append(entry)
    return manifest


def ensure_failed_sources(manifest: dict) -> dict:
    """Make sure the documented-unreachable sources are recorded, without
    duplicating them on repeated acquisition runs."""
    artifacts = manifest.setdefault("artifacts", [])
    existing_datasets = {a.get("dataset") for a in artifacts if a.get("status") == "unreachable_egress_policy"}
    for failed in FAILED_SOURCES:
        if failed["dataset"] not in existing_datasets:
            artifacts.append(dict(failed))
    return manifest
