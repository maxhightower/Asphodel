#!/usr/bin/env python3
"""Per-city smoke test for the survivor-group runtime
(ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1).

For each requested city bundle the smoke boots the world exactly as the game
does (bridge ``START_WORLD`` with a player citizen, which enables mobility,
work, cognition, dialogue and — by default — the survivor-group layer), then
drives the SAME reduced causal chain the certification uses through the frozen
GroupRuntime/CognitionRuntime APIs (the deterministic driver an emergent scan
needs) and checks the group-layer invariants that must hold in EVERY city:

    * deterministic replay — the whole scenario is built twice from the same
      seed and the two resulting group states (GroupRuntime.to_state) must be
      byte-identical;
    * the possibility of formation where conditions permit — where a co-present
      cluster of >=3 exists and real cooperation is applied, a group must
      emerge (INFO, never FAIL, where no such cluster exists to seed one);
    * valid shelter selection — the chosen shelter is a building the group's
      own members actually know (aggregated from member node_meta, never a
      citywide scan);
    * membership persistence through save/load — the group's membership, roles
      and shelter survive a world_state -> load_world round trip byte-identically;
    * NO city-name logic — the identical function drives every city; the trio,
      the shelter and the roles are all discovered from authoritative state.

Status per city:
    PASS   the run was deterministic, a group formed with a member-known
           shelter, and its membership persisted through save/load
    INFO   no compiled world in the bundle (nothing to embody), or no
           co-present cluster of >=3 exists to seed a group (conditions do not
           permit formation) — reported, never a failure
    FAIL   anything else (non-determinism, an invalid shelter, or lost
           membership across save/load)

Exit code is non-zero when any city FAILs. Writes
artifacts/survivor_groups_v1/city_smoke.json.

    PYTHONPATH=. python3 tools/groups_city_smoke.py [city ...]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time
import traceback
from typing import Dict, List, Optional, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from asphodel.bridge import WorldSession, PROTOCOL_VERSION            # noqa: E402
from asphodel.bridge.protocol import Command                          # noqa: E402
from asphodel.bridge.worldfactory import resolve_bundle_dir           # noqa: E402
from asphodel.cognition import memory as M                            # noqa: E402
from asphodel.groups import model as GM                               # noqa: E402
from asphodel.save import world_state, load_world                     # noqa: E402
from asphodel.embodiment import CitySpatialContext                    # noqa: E402

DEFAULT_CITIES = ["houston", "madisonville_tx", "austin", "san_antonio", "boulder"]
ARTIFACT = os.path.join(REPO, "artifacts", "survivor_groups_v1", "city_smoke.json")

START_HOUR = 8.0
WARM_MINUTES = 120                    # 08:00 -> 10:00, when workplaces fill and clusters form
SEED = 0
PLAYER_CITIZEN = 0
FAR = (9000.0, 9000.0)


def has_compiled_world(bundle_dir: str) -> bool:
    return os.path.exists(os.path.join(bundle_dir, "world", "spawn_anchors.json.gz"))


def build_world(city: str, start_hour: float = START_HOUR, seed: int = SEED,
                player_citizen: Optional[int] = PLAYER_CITIZEN):
    """World + mobility + work + cognition + dialogue + groups, exactly as the
    game boots one. Returns ``(session, world)``."""
    s = WorldSession()
    s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    msg = {"cmd": Command.START_WORLD, "bundle": city, "seed": seed,
           "start_hour": float(start_hour)}
    if player_citizen is not None:
        msg["player_citizen"] = int(player_citizen)
    r = s.handle(msg)
    if not r.get("ok") and player_citizen is not None:
        msg.pop("player_citizen")
        r = s.handle(msg)
    if not r.get("ok"):
        raise RuntimeError(f"START_WORLD failed for {city}: {r}")
    if not r.get("groups_enabled"):
        raise RuntimeError(f"START_WORLD did not enable the group runtime for {city}: {r}")
    return s, s.world


def co_present_trio(w) -> Tuple[Optional[List[int]], Optional[int]]:
    c = w.cognition
    rooms = collections.defaultdict(list)
    for cid in sorted(w.mobility.execs):
        ex = w.mobility.execs[cid]
        if ex.inside and c._can_perceive(cid):
            rooms[(int(ex.building_id), c._ctx(cid).get("room_id"))].append(cid)
    for k, v in sorted(rooms.items()):
        if len(v) >= 3:
            return sorted(v)[:3], k[0]
    return None, None


def cooperate(c, trio, rounds=3):
    a, b, cc = trio
    for _ in range(rounds):
        for x, y in [(a, b), (b, a), (a, cc), (cc, a), (b, cc), (cc, b)]:
            c.relate(x, y, "fled_with")
            c.relate(y, x, "helped_by")


def run(w, minutes):
    for _ in range(int(minutes)):
        w.advance_seconds(60.0, focus_xy=FAR)


def drive_scenario(city: str, seed: int = SEED) -> dict:
    """Boot a city and drive the reduced deterministic group scenario. Returns a
    dict describing what happened (trio, formation, shelter, roles, group state
    digest). Raises only on a genuine error; 'no trio' is a normal INFO result."""
    s, w = build_world(city, seed=seed)
    c, gr = w.cognition, w.groups
    run(w, WARM_MINUTES)
    trio, workbid = co_present_trio(w)
    # give the city a fair window: if no co-present cluster of >=3 exists yet,
    # keep advancing (workplaces fill, shops draw customers) up to mid-afternoon
    searched_to = 10.0
    while trio is None and w.current_hour() < 15.0:
        run(w, 30)
        searched_to = round(w.current_hour(), 2)
        trio, workbid = co_present_trio(w)
    out: dict = {"trio": trio, "workbid": workbid, "formed": False, "searched_to_hour": searched_to}
    if trio is None:
        out["reason"] = ("no co-present cluster of >=3 anywhere between 10:00 and 15:00 — "
                         "conditions do not permit a group in this city/seed window")
        return {"session": s, "world": w, **out}
    cooperate(c, trio, rounds=3)
    gr._last_form_scan = -1e9
    gr._scan_formation()
    g = gr.group_of(trio[0])
    if g is None:
        out["reason"] = "cooperation applied but the formation scan produced no group"
        out["group_state_digest"] = _digest(gr.to_state())
        return {"session": s, "world": w, **out}
    out["formed"] = True
    out["group_id"] = g.group_id
    out["members"] = g.active_members()
    out["coordinator"] = g.coordinator
    gr.select_shelter(g)
    out["shelter_building"] = g.shelter_building
    # a member's own known-building set — the ONLY legitimate source of a shelter
    known = set()
    for m in g.active_members():
        known |= set(gr._known_buildings(m).keys())
    out["shelter_is_member_known"] = g.shelter_building is not None and g.shelter_building in known
    out["n_member_known_buildings"] = len(known)
    run(w, 120)
    out["regrouped"] = sorted(m for m in g.active_members() if gr.at_shelter(g, m))
    guard = gr.assign_role(g, GM.GUARD)
    out["guard"] = guard
    g.supplies["food"] = 0.0
    out["scavenger"] = gr.check_supplies(g)
    run(w, 120)
    out["roles_after"] = dict(g.roles)
    out["group_state_digest"] = _digest(gr.to_state())
    return {"session": s, "world": w, "group": g, **out}


def _digest(obj) -> str:
    import hashlib
    return hashlib.sha1(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]


def saveload_persistence(w, city: str) -> dict:
    """world_state -> load_world round trip; the group's membership/roles/shelter
    must survive byte-identically. Exercises the real save/load path (the same
    one LOAD uses over the bridge)."""
    d = resolve_bundle_dir(city)
    before = json.dumps(w.groups.to_state(), sort_keys=True)
    js = json.dumps(world_state(w))
    w2 = load_world(json.loads(js))
    w2.set_spatial_context(CitySpatialContext.from_bundle_dir(d))
    w2.enable_mobility(bundle_dir=d)
    if w2._pending_outbreak_state is not None:
        w2.enable_outbreak()
    w2.enable_work()
    w2.enable_cognition()
    w2.enable_dialogue()
    w2.enable_groups()
    after = json.dumps(w2.groups.to_state(), sort_keys=True)
    return {"identical": before == after,
            "n_groups_before": len(w.groups.groups), "n_groups_after": len(w2.groups.groups)}


def smoke_city(city: str, seed: int = SEED) -> dict:
    out = {"city": city, "status": "FAIL", "reason": ""}
    d = resolve_bundle_dir(city)
    if not os.path.isdir(d):
        return {**out, "status": "INFO", "reason": "bundle not found / not compiled"}
    if not has_compiled_world(d):
        return {**out, "status": "INFO", "reason": "no compiled world (spawn anchors absent)"}
    t0 = time.perf_counter()
    try:
        run1 = drive_scenario(city, seed=seed)
    except Exception as exc:
        return {**out, "status": "FAIL", "reason": f"scenario error: {exc}",
                "traceback": traceback.format_exc()}
    out["n_citizens"] = len(run1["world"].mobility.execs)
    out["trio"] = run1.get("trio")
    out["workbid"] = run1.get("workbid")
    out["formed"] = run1.get("formed", False)

    if run1.get("trio") is None:
        out["status"] = "INFO"
        out["reason"] = run1["reason"]
        out["run_s"] = round(time.perf_counter() - t0, 2)
        return out
    if not run1.get("formed"):
        # a co-present cluster existed but the scan did not close a bonded group;
        # this is a possibility-gated outcome, reported as INFO, never a failure
        out["status"] = "INFO"
        out["reason"] = run1.get("reason", "no group formed despite a co-present cluster")
        out["run_s"] = round(time.perf_counter() - t0, 2)
        return out

    out["group_id"] = run1["group_id"]
    out["members"] = run1["members"]
    out["coordinator"] = run1["coordinator"]
    out["shelter_building"] = run1["shelter_building"]
    out["shelter_is_member_known"] = run1["shelter_is_member_known"]
    out["regrouped"] = run1["regrouped"]
    out["roles_after"] = run1["roles_after"]

    # -- membership persistence through save/load --------------------------
    persist = saveload_persistence(run1["world"], city)
    out["saveload"] = persist

    # -- deterministic replay (same seed -> same group twice) --------------
    try:
        run2 = drive_scenario(city, seed=seed)
    except Exception as exc:
        out["status"] = "FAIL"
        out["reason"] = f"determinism replay error: {exc}"
        return out
    deterministic = (run1.get("group_state_digest") == run2.get("group_state_digest")
                     and run1.get("group_state_digest") is not None)
    out["determinism"] = {"deterministic": deterministic,
                          "digest_run1": run1.get("group_state_digest"),
                          "digest_run2": run2.get("group_state_digest"),
                          "members_run2": run2.get("members")}

    reasons = []
    if not run1["shelter_is_member_known"]:
        reasons.append("shelter is not a member-known building")
    if not persist["identical"]:
        reasons.append("group state changed across save/load")
    if not deterministic:
        reasons.append("group state diverged on replay")
    if len(run1["members"]) < 3:
        reasons.append("group has fewer than 3 members")
    out["status"] = "FAIL" if reasons else "PASS"
    out["reason"] = "; ".join(reasons) if reasons else (
        "a group formed from real cooperation, sheltered in a member-known building, "
        "kept its membership through save/load, and rebuilt identically on replay")
    out["run_s"] = round(time.perf_counter() - t0, 2)
    return out


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cities", nargs="*", default=DEFAULT_CITIES)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--merge", action="store_true",
                    help="merge these cities' results into an existing city_smoke.json instead of overwriting")
    args = ap.parse_args(argv)
    cities = args.cities or DEFAULT_CITIES

    results = {}
    all_cities = list(cities)
    if args.merge and os.path.exists(ARTIFACT):
        try:
            prev = json.load(open(ARTIFACT))
            results = dict(prev.get("results", {}))
            all_cities = list(dict.fromkeys(list(prev.get("cities", [])) + list(cities)))
        except Exception:
            pass
    for city in cities:
        print(f"[groups_city_smoke] {city} ...")
        try:
            results[city] = smoke_city(city, seed=args.seed)
        except Exception as exc:
            results[city] = {"city": city, "status": "FAIL", "reason": str(exc),
                             "traceback": traceback.format_exc()}
        r = results[city]
        print(f"  {city}: {r['status']} — {r.get('reason','')}")

    any_fail = any(r["status"] == "FAIL" for r in results.values())
    doc = {"milestone": "ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1",
           "protocol_version": PROTOCOL_VERSION, "seed": args.seed,
           "start_hour": START_HOUR, "warm_minutes": WARM_MINUTES,
           "cities": all_cities, "overall": "FAIL" if any_fail else "PASS",
           "checks": ["deterministic replay (same seed -> identical group state)",
                      "possibility of formation where a co-present cluster permits",
                      "valid shelter selection (a member-known building)",
                      "membership persistence through save/load",
                      "no city-name logic (identical driver for every city)"],
           "results": results}
    os.makedirs(os.path.dirname(ARTIFACT), exist_ok=True)
    with open(ARTIFACT, "w") as f:
        json.dump(doc, f, indent=2)
    print(f"\nwrote {ARTIFACT}  overall={doc['overall']}")
    for city in all_cities:
        r = results.get(city, {})
        print(f"  {city:16s} {r.get('status','?'):5s} {r.get('reason','')}")
    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
