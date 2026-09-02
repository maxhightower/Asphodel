"""P0-0.1 -- visual determinism certification.

The compiled visual plan (facade/roof material + colour) must be a pure function
of (stable_key, centroid, seed, archetype): byte-identical across separate Python
processes and independent of PYTHONHASHSEED. Python's built-in ``hash()`` is
salted per process, so if any procedural appearance decision were keyed on it the
visual baseline would silently drift between rebuilds. These tests are the hard
regression guard behind the charter's "same seed/source produces byte- or
content-equivalent compiled visual plans" acceptance criterion.

Two checks:
  * a cross-process digest that must match under several PYTHONHASHSEED values;
  * an AST guard that no appearance/randomness module ever *calls* built-in
    hash() (docstrings mentioning it are fine -- we look for call nodes only).
"""
from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# A small standalone corpus digest. Runs in a fresh interpreter (so the process
# hash salt actually varies) and prints one sha256 over the inferred appearance
# of a fixed spread of buildings across every archetype, position and seed.
_DIGEST_SNIPPET = r"""
import hashlib
from asphodel.world_source import appearance as appear
from asphodel.world_source import appearance_infer as inf

ARCHES = ["DETACHED_RESIDENTIAL", "MULTIFAMILY", "SMALL_COMMERCIAL",
          "BIG_BOX_COMMERCIAL", "INDUSTRIAL", "OFFICE_HIGHRISE",
          "CIVIC_SPECIAL", "GENERIC_UNKNOWN", "NOT_A_REAL_ARCH"]

def blank(bid):
    return appear.build_appearance(bid, {"height_m": None}, "flat", None, False).to_dict()

parts = []
for ai, arch in enumerate(ARCHES):
    for i in range(40):
        bid = ai * 1000 + i
        key = "bld/%d/%d" % (ai, i)
        cx = 100.0 + 37.0 * i - 11.0 * ai
        cz = -50.0 + 23.0 * i + 7.0 * ai
        seed = 1 + (i % 5)
        ap = inf.infer_building(bid, key, cx, cz, arch, blank(bid), seed)
        parts.append("|".join([
            key, arch, str(seed),
            ap["facade"]["material"]["value"], ap["facade"]["color"]["value"],
            ap["roof"]["material"]["value"], ap["roof"]["color"]["value"],
            str(ap["style_family"]["value"]),
        ]))
digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
print(digest)
"""


def _digest(hashseed: str) -> str:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = hashseed
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    out = subprocess.run(
        [sys.executable, "-c", _DIGEST_SNIPPET],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
    )
    assert out.returncode == 0, f"digest subprocess failed:\n{out.stderr}"
    return out.stdout.strip()


def test_appearance_digest_stable_across_pythonhashseed():
    """Inferred appearance is byte-identical across processes with different hash
    salts -- proving no procedural facade/roof choice depends on built-in hash()."""
    baseline = _digest("0")
    assert len(baseline) == 64
    for seed in ("1", "42", "1234567", "random"):
        assert _digest(seed) == baseline, (
            f"appearance digest changed under PYTHONHASHSEED={seed}: "
            f"{_digest(seed)} != {baseline} -- a salted hash() has leaked into "
            f"procedural appearance and the visual baseline is not reproducible."
        )


# Modules where a salted built-in hash() would corrupt determinism.
_GUARDED = [
    "asphodel/world_source/appearance_infer.py",
    "asphodel/world_source/detrand.py",
    "asphodel/city_visual/business_identity.py",
    "asphodel/osm_city/citizens.py",
]


def _builtin_hash_calls(path: Path) -> list[int]:
    """Line numbers where built-in hash(...) is *called* (docstrings ignored)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "hash":
            hits.append(node.lineno)
    return hits


def test_no_builtin_hash_call_in_determinism_modules():
    """Static guard: the modules that drive procedural visual/identity choices must
    never call built-in hash() -- only their own stable FNV/splitmix hashers."""
    for rel in _GUARDED:
        path = REPO_ROOT / rel
        assert path.exists(), f"guarded module missing: {rel}"
        hits = _builtin_hash_calls(path)
        assert not hits, f"{rel} calls built-in hash() at line(s) {hits}"
