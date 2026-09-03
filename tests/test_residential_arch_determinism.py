"""Determinism gates: same input+seed => same architecture, across iteration
order and across fresh Python processes; never keyed on Python's salted hash()."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap

from asphodel.world_source import residential_grammar as rg
from tests._res_fixtures import rect, feature, compile_block


def _sig(recs):
    # compare architecture CONTENT keyed on the stable feature key; `bid` is a
    # compile-order index (not a determinism property of the house itself) so it
    # is excluded — a feature's architecture must be identical regardless of the
    # order features were fed in.
    out = {}
    for r in recs:
        if not r.architecture:
            continue
        a = dict(r.architecture)
        a.pop("bid", None)
        out[r.key] = a
    return out


def test_same_input_same_seed_is_identical():
    feats = [feature(f"h{i}", rect(40 + i * 15, 40, 12, 10)) for i in range(15)]
    a, _ = compile_block(feats, seed=123)
    b, _ = compile_block(feats, seed=123)
    assert _sig(a) == _sig(b)


def test_different_seed_changes_result():
    feats = [feature(f"h{i}", rect(40 + i * 15, 40, 12, 10)) for i in range(15)]
    a, _ = compile_block(feats, seed=1)
    b, _ = compile_block(feats, seed=2)
    assert _sig(a) != _sig(b)


def test_feature_iteration_order_does_not_change_results():
    feats = [feature(f"h{i}", rect(40 + i * 15, 40, 12, 10)) for i in range(15)]
    a, _ = compile_block(feats, seed=77)
    # reversing the input order must not change any individual house's architecture
    b, _ = compile_block(list(reversed(feats)), seed=77)
    assert _sig(a) == _sig(b)


def test_result_is_stable_across_fresh_processes():
    # A fresh interpreter with a RANDOMISED PYTHONHASHSEED must produce byte-for-
    # byte identical architecture — proving no reliance on the salted built-in
    # hash(). We run the same compile twice in two subprocesses and diff the JSON.
    prog = textwrap.dedent(
        """
        from shapely.geometry import Polygon
        from asphodel.world_source import buildings_grammar, residential_grammar
        from asphodel.world_source.records import Parcel
        from asphodel.world_source.schema import Feature
        import json
        def rect(cx, cz, w, d):
            return [[(cx-w/2,cz-d/2),(cx+w/2,cz-d/2),(cx+w/2,cz+d/2),(cx-w/2,cz+d/2)]]
        feats=[]
        for i in range(15):
            g=rect(40+i*15,40,12,10)
            feats.append(Feature(stable_key=f"h{i}",geometry=g,geom_type="polygon",
                properties={"subtype":"residential","_area":Polygon(g[0]).area},
                source="t",source_id=f"h{i}"))
        par=Parcel(pid="p",poly=Polygon([(-20,-20),(400,-20),(400,400),(-20,400)]),
            arch="RESIDENTIAL",obs="DERIVED",block_id=0,building_bids=list(range(15)))
        recs=buildings_grammar.compile_buildings(feats,[par],[],seed=555)
        residential_grammar.assign_architecture(recs,[par],[par.poly],555,
            lat=29.76,lon=-95.36,props_by_bid={i:f.properties for i,f in enumerate(feats)})
        print(json.dumps({r.key:r.architecture for r in recs},sort_keys=True))
        """
    )
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pp = root + os.pathsep + os.environ.get("PYTHONPATH", "")
    env1 = dict(os.environ, PYTHONHASHSEED="0", PYTHONPATH=pp)
    env2 = dict(os.environ, PYTHONHASHSEED="12345", PYTHONPATH=pp)
    r1 = subprocess.run([sys.executable, "-c", prog], capture_output=True,
                        text=True, env=env1, cwd=root)
    r2 = subprocess.run([sys.executable, "-c", prog], capture_output=True,
                        text=True, env=env2, cwd=root)
    assert r1.returncode == 0, r1.stderr
    assert r2.returncode == 0, r2.stderr
    assert r1.stdout == r2.stdout
    assert json.loads(r1.stdout)      # non-empty


def test_morphology_is_pure():
    from shapely.geometry import Polygon
    g = rect(0, 0, 18, 9)
    m1 = rg.compute_morphology(Polygon(g[0]))
    m2 = rg.compute_morphology(Polygon(g[0]))
    assert m1 == m2
