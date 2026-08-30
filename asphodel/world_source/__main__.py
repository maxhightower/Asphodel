"""CLI for the world_source acquisition layer.

    python -m asphodel.world_source bbox <city>
    python -m asphodel.world_source acquire --city <city> [--release R] [--types a,b,c] [--force] [--offline]
    python -m asphodel.world_source gate
"""
from __future__ import annotations

import argparse
import datetime
import sys

from . import bbox as bbox_mod
from . import gate as gate_mod
from . import overture
from . import provenance

DEFAULT_RELEASE = "2026-08-19.0"
ALL_TYPES = list(overture.TYPE_THEMES.keys())


def _cmd_bbox(args) -> int:
    return bbox_mod._cli([args.city])


def _cmd_gate(args) -> int:
    return gate_mod._cli([])


def _cmd_acquire(args) -> int:
    city = args.city
    release = args.release
    types = args.types.split(",") if args.types else ALL_TYPES
    w, s, e, n = bbox_mod.city_bbox(city)
    target_bbox = (w, s, e, n)
    manifest = provenance.load_manifest()

    for type_ in types:
        theme = overture.TYPE_THEMES[type_]
        license_terms = provenance.THEME_LICENSE[theme]
        out_path_rel = f"data/raw/overture/{release}/{city}/{type_}.parquet"

        if args.offline:
            existing = next(
                (a for a in manifest.get("artifacts", []) if a.get("type") == type_ and a.get("city") == city and a.get("release") == release),
                None,
            )
            if existing is None:
                print(f"[{city}/{type_}] OFFLINE: no manifest entry, cannot verify", file=sys.stderr)
                return 1
            import os
            full_path = os.path.join(overture._REPO_ROOT, existing["raw_path"])
            ok = overture.verify_cached(full_path, existing["sha256"])
            print(f"[{city}/{type_}] OFFLINE verify: {'OK' if ok else 'CHECKSUM MISMATCH'}")
            if not ok:
                return 1
            continue

        info = overture.download_type(
            city=city,
            bbox=target_bbox,
            type_=type_,
            release=release,
            force=args.force,
        )
        entry = {
            "provider": provenance.OVERTURE_PROVIDER,
            "dataset": f"Overture {theme}/{type_}",
            "theme": theme,
            "type": type_,
            "release": release,
            "city": city,
            "source_url_pattern": f"{overture.S3_BASE}/release/{release}/theme={theme}/type={type_}/part-*.parquet",
            "retrieval_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "bbox": list(target_bbox),
            "license_family": license_terms["license_family"],
            "license_name": license_terms["license_name"],
            "attribution": license_terms["attribution"],
            "commercial_permitted": license_terms["commercial_permitted"],
            "share_alike": license_terms["share_alike"],
            "license_note": license_terms["license_note"],
            "sha256": info["sha256"],
            "raw_path": info["raw_path"],
            "row_count": info["row_count"],
            "file_size_bytes": info["file_size_bytes"],
            "status": "ok",
        }
        provenance.upsert_artifact(manifest, entry)

    provenance.ensure_failed_sources(manifest)
    provenance.save_manifest(manifest)
    print(f"manifest updated: {provenance.MANIFEST_PATH}")
    return 0


def _cmd_build(args) -> int:
    """Full reproducible world build: acquire -> gate -> compile -> rebake
    citizens -> certify (mission §30)."""
    import json
    import os

    from . import compile as compile_mod

    city = args.city
    release = args.release
    bundle_dir = os.path.join("godot", "bundles", city)
    if not os.path.isdir(bundle_dir):
        print(f"no bundle dir {bundle_dir}", file=sys.stderr)
        return 1

    if args.download_missing and not args.offline:
        rc = _cmd_acquire(argparse.Namespace(
            city=city, release=release, types=None, force=False,
            offline=False))
        if rc != 0:
            return rc

    # License gate is a hard precondition of compiling a releasable bundle.
    rc = gate_mod._cli([])
    if rc != 0:
        return rc

    report = compile_mod.compile_city(city, release, seed=args.seed,
                                      out_dir=bundle_dir)
    print(json.dumps(report["counts"], indent=1, sort_keys=True))

    if args.citizens > 0:
        from ..osm_city import citizens as citizens_mod
        n = citizens_mod.write_citizens_from_bundle(
            bundle_dir, args.city_name or city.title(), n=args.citizens,
            seed=args.seed)
        print(f"rebaked {n} citizens")

    if args.certify:
        from . import certify as certify_mod
        result = certify_mod.certify_city(bundle_dir, seed=args.seed)
        print(json.dumps(result["gates"], indent=1, sort_keys=True))
        report_path = os.path.join(bundle_dir, "world",
                                   "certification.json")
        with open(report_path, "w") as f:
            json.dump(result, f, indent=1, sort_keys=True)
        if not all(result["gates"].values()):
            print("CERTIFICATION GATES FAILED", file=sys.stderr)
            return 2
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m asphodel.world_source")
    sub = parser.add_subparsers(dest="command", required=True)

    p_bbox = sub.add_parser("bbox", help="print a city's (W,S,E,N) bbox")
    p_bbox.add_argument("city")
    p_bbox.set_defaults(func=_cmd_bbox)

    p_acquire = sub.add_parser("acquire", help="download Overture data for a city")
    p_acquire.add_argument("--city", required=True)
    p_acquire.add_argument("--release", default=DEFAULT_RELEASE)
    p_acquire.add_argument("--types", default=None, help="comma-separated subset of: " + ",".join(ALL_TYPES))
    p_acquire.add_argument("--force", action="store_true")
    p_acquire.add_argument("--offline", action="store_true", help="verify cached files against manifest checksums instead of downloading")
    p_acquire.set_defaults(func=_cmd_acquire)

    p_gate = sub.add_parser("gate", help="run the commercial-cleanliness gate over the manifest")
    p_gate.set_defaults(func=_cmd_gate)

    p_build = sub.add_parser(
        "build", help="full world build: acquire+gate+compile+citizens+certify")
    p_build.add_argument("--city", required=True)
    p_build.add_argument("--city-name", default=None,
                         help="display name for citizen records")
    p_build.add_argument("--release", default=DEFAULT_RELEASE)
    p_build.add_argument("--seed", type=int, default=0)
    p_build.add_argument("--citizens", type=int, default=60,
                         help="citizen count to rebake (0 skips)")
    p_build.add_argument("--download-missing", action="store_true")
    p_build.add_argument("--offline", action="store_true",
                         help="build purely from cached source packets")
    p_build.add_argument("--certify", action="store_true")
    p_build.set_defaults(func=_cmd_build)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
