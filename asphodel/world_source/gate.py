"""Commercial-cleanliness gate over the provenance manifest.

This is the single mechanical check that stands between "data we downloaded"
and "data a shipped bundle is allowed to use": no artifact recorded with
status "ok" may carry an UNKNOWN or RESTRICTED license family. FAILED
(unreachable) sources are exempt -- they never produced usable output in the
first place, so they cannot leak into a bundle.
"""
from __future__ import annotations

import sys

from . import provenance

UNSAFE_FAMILIES = {"RESTRICTED", "UNKNOWN"}


class GateFailure(Exception):
    """Raised when the manifest contains a commercially unsafe "ok" artifact."""


def assert_commercial_clean(manifest: dict) -> None:
    """Raise GateFailure if any "ok" artifact has an unsafe license family."""
    offenders = []
    for artifact in manifest.get("artifacts", []):
        if artifact.get("status") != "ok":
            continue
        family = artifact.get("license_family")
        if family in UNSAFE_FAMILIES or not artifact.get("commercial_permitted", False):
            offenders.append(artifact)
    if offenders:
        lines = [
            f"  - provider={o.get('provider')!r} type={o.get('type')!r} "
            f"city={o.get('city')!r} license_family={o.get('license_family')!r} "
            f"commercial_permitted={o.get('commercial_permitted')!r}"
            for o in offenders
        ]
        raise GateFailure(
            "Commercial-cleanliness gate failed: "
            f"{len(offenders)} 'ok' artifact(s) are not commercially safe:\n"
            + "\n".join(lines)
        )


def _cli(argv: list[str]) -> int:
    manifest = provenance.load_manifest()
    try:
        assert_commercial_clean(manifest)
    except GateFailure as exc:
        print(str(exc), file=sys.stderr)
        return 1
    n_ok = sum(1 for a in manifest.get("artifacts", []) if a.get("status") == "ok")
    print(f"gate: OK -- {n_ok} 'ok' artifact(s), all commercially clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
