#!/usr/bin/env python3
"""ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1 — deterministic scenario pre-step.

Approach (b) from the milestone brief: build a Houston world through the *real*
bridge ``START_WORLD`` path, drive the SAME causal chain the certification day
uses (repeated mutual aid + fleeing danger together -> a survivor group emerges;
a shelter chosen from member knowledge; members regroup; a coordinator, a guard
and a scavenger take real roles; an outsider becomes assessable; a threat
warning is shared with preserved provenance), then ``SAVE`` the world to disk.

The live GroupGate then ``LOAD``s that save over the bridge and observes/queries
the formed group through ``GET_GROUPS`` / ``GROUP_QUERY`` — exercising the real
save/load + bridge + snapshot path end to end. This script forms the group by
calling the frozen GroupRuntime/CognitionRuntime APIs directly (it never edits
them); it is the deterministic driver the emergent scan needs, exactly as the
certification's ``day()`` fixture drives it.

Nothing here is city-name logic: the trio, the shelter, the roles and the
outsider are all *discovered* from authoritative state (co-presence, member
knowledge, relationship history), never hard-coded.

    PYTHONPATH=. python3 tools/groups_build_scenario.py \
        --bundle houston --start-hour 8.0 --save /tmp/asph_group_save.json \
        --sidecar /tmp/asph_group_scenario.json
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from asphodel.bridge import WorldSession, PROTOCOL_VERSION            # noqa: E402
from asphodel.bridge.protocol import Command                          # noqa: E402
from asphodel.cognition import memory as M                            # noqa: E402
from asphodel.groups import model as GM                               # noqa: E402

FAR = (9000.0, 9000.0)


def _co_present_trio(w):
    """The first room (by building id, room id) with >=3 citizens who can
    perceive — discovered from authoritative co-presence, never named."""
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


def _cooperate(c, trio, rounds=3):
    """Drive the REAL social history that justifies a group: repeated mutual aid
    and fleeing danger together, through cognition's own relationship rules."""
    a, b, cc = trio
    for _ in range(rounds):
        for x, y in [(a, b), (b, a), (a, cc), (cc, a), (b, cc), (cc, b)]:
            c.relate(x, y, "fled_with")
            c.relate(y, x, "helped_by")


def _run(w, minutes):
    for _ in range(int(minutes)):
        w.advance_seconds(60.0, focus_xy=FAR)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default="houston")
    ap.add_argument("--start-hour", type=float, default=8.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--player", type=int, default=None)
    ap.add_argument("--save", required=True)
    ap.add_argument("--sidecar", required=True)
    args = ap.parse_args()

    s = WorldSession()
    s.handle({"cmd": Command.HELLO, "protocol_version": PROTOCOL_VERSION})
    msg = {"cmd": Command.START_WORLD, "bundle": args.bundle, "seed": args.seed,
           "start_hour": float(args.start_hour), "work": True, "cognition": True,
           "dialogue": True, "groups": True}
    if args.player is not None:
        msg["player_citizen"] = int(args.player)
    r = s.handle(msg)
    if not r.get("ok"):
        raise SystemExit(f"START_WORLD failed: {r}")
    if not r.get("groups_enabled"):
        raise SystemExit(f"groups not enabled: {r}")
    w = s.world
    c, gr, dl = w.cognition, w.groups, w.dialogue

    # ---- Phase A: ordinary individuals; discover a co-present trio ----------
    _run(w, 120)                                    # 08:00 -> 10:00
    trio, workbid = _co_present_trio(w)
    if trio is None:
        raise SystemExit("no co-present trio of >=3 found by 10:00")
    a, b, cc = trio

    # ---- Phase B: cooperation -> a group EMERGES (never pre-seeded) ---------
    _cooperate(c, trio, rounds=3)
    gr._last_form_scan = -1e9
    gr._scan_formation()
    g = gr.group_of(a)
    if g is None:
        raise SystemExit(f"no group formed from trio {trio}")

    # ---- Phase C: shelter chosen from member knowledge, then regroup --------
    gr.select_shelter(g)
    regrouped = []
    for _ in range(6):
        _run(w, 60)
        regrouped = sorted(m for m in g.active_members() if gr.at_shelter(g, m))
        if len(regrouped) >= 3:
            break

    # ---- Phase D: real roles (coordinator emerges at formation; guard;
    #               scavenger via a supply shortage the group notices) --------
    guard = gr.assign_role(g, GM.GUARD)
    g.supplies["food"] = 0.0
    scavenger = gr.check_supplies(g)
    _run(w, 240)                                    # let guard hold + scavenger run/return

    # ---- Phase E: an outsider becomes assessable (helpful history) ----------
    at = regrouped or g.active_members()
    outsider = next((x for x in sorted(w.mobility.execs)
                     if x not in g.members and c._can_perceive(x) and dl.co_present(at[0], x)[0]), None)
    if outsider is None:
        outsider = next((x for x in sorted(w.mobility.execs)
                         if x not in g.members and c._can_perceive(x)), None)
    if outsider is not None:
        for mem in at[:2]:
            c.relate(mem, outsider, "helped_by")    # members remember the outsider helped them
            c.relate(mem, outsider, "helped_by")

    # a citizen that is definitely NOT in the group (for the membership-null check)
    non_member = next((x for x in sorted(w.mobility.execs)
                       if x not in g.members and x != outsider), None)

    # ---- Phase F: a threat warning shared with preserved provenance ---------
    reporter = at[0]
    st = c.store(reporter)
    threat_fact, _ = st.remember(M.ATTACK_SEEN, c.now_s, actor=888,
                                 building_id=g.shelter_building, room_id=g.entrance_room,
                                 source=M.DIRECT, confidence=1.0)
    c._beliefs.pop(reporter, None)
    warn = gr.warn_group(g, reporter, threat_fact)

    # ---- SAVE through the real bridge command -------------------------------
    sr = s.handle({"cmd": Command.SAVE, "path": args.save})
    if not sr.get("ok"):
        raise SystemExit(f"SAVE failed: {sr}")

    warned_fact = None
    for fid, gf in sorted(g.shared_record.items()):
        if gf.origin_witness is not None:
            warned_fact = {"fact_id": fid, "kind": gf.kind, "origin_witness": gf.origin_witness,
                           "source_citizen": gf.source_citizen, "building_id": gf.building_id,
                           "subject": gf.subject}
            break

    sidecar = {
        "bundle": args.bundle, "start_hour": args.start_hour, "seed": args.seed,
        "save_path": os.path.abspath(args.save),
        "group_id": g.group_id, "founders": list(g.founders),
        "members": g.active_members(), "coordinator": g.coordinator,
        "roles": {r: cid for r, cid in g.roles.items()},
        "shelter_building": g.shelter_building, "shelter_room": g.shelter_room,
        "entrance_room": g.entrance_room, "shelter_node": g.shelter_node,
        "regrouped": regrouped, "reporter": reporter,
        "outsider": outsider, "non_member": non_member,
        "guard_result": guard, "scavenger_result": scavenger,
        "supplies": dict(g.supplies), "threat_state": g.threat_state,
        "warn": warn, "warned_fact": warned_fact,
        "member_states": {str(cid): st for cid, st in sorted(g.members.items())},
        "formed_reason": g.formed_reason,
        "hour_saved": round(w.current_hour(), 3),
        "counts": dict(gr.counts),
        "n_groups": len(gr.groups),
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.sidecar)), exist_ok=True)
    with open(args.sidecar, "w") as f:
        json.dump(sidecar, f, indent=1, sort_keys=True)

    print(f"SCENARIO OK group={g.group_id} members={g.active_members()} "
          f"coordinator={g.coordinator} roles={g.roles} shelter={g.shelter_building} "
          f"outsider={outsider} non_member={non_member} warned_fact={warned_fact is not None}")
    print(f"SAVE={args.save} SIDECAR={args.sidecar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
