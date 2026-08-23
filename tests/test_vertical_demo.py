"""M6 vertical certification: the full end-to-end gameplay sequence, driven
through the authoritative runtime (the simulation half of the living city).

This is the initiative's closing demonstration expressed as an executable test.
Godot renders this world from `snapshot()`; here we certify that the authoritative
runtime actually *supports* the whole sequence:

  spawn as a citizen -> nearby zone promotes -> citizens are real identified agents
  with routines -> time advances -> belief changes -> NPC reactions depart from
  routine -> player interacts -> citizen enters the persistent roster -> travel
  away -> zone demotes -> an intervention changes the outbreak trajectory -> time
  advances -> return -> the previous citizen is restored as the same person ->
  save -> fully terminate -> load -> continue deterministically.
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asphodel import World, ScenarioConfig, MicroParams
from asphodel.citizen import CitizenProfile, ScheduleEntry
from asphodel import npc
from asphodel.save import save_world, load_world_file


DAY = [ScheduleEntry(0.0, 7.0, "sleep", "h"), ScheduleEntry(7.0, 9.0, "commute", "r"),
       ScheduleEntry(9.0, 17.0, "work", "o"), ScheduleEntry(17.0, 24.0, "leisure", "h")]


def _city(seed=1, start_hour=8.0):
    cfg = ScenarioConfig()
    cfg.model.graph.grid_rows = 4
    cfg.model.graph.grid_cols = 4
    cfg.model.graph.population_per_zone = 1000.0
    cfg.n_days = 80.0
    w = World(cfg, micro_params=MicroParams(area_size=100.0, infection_radius=2.0,
                                            mixing_step_frac=0.12),
              start_hour=start_hour, seed=seed)
    citizens = []
    cid = 0
    for z in range(16):
        for _ in range(40):
            citizens.append(CitizenProfile(
                citizen_id=cid, city="Houston", age=30 + (cid % 40), age_band="a",
                occupation="worker", shift="d", home_district="d", work_district="d",
                home_zone=z, work_zone=z, schedule=DAY, inventory={}, spawn_hour=8.0,
                current_location="o", current_activity="work", current_task=""))
            cid += 1
    w.set_citizens(citizens)
    return w


def _reaction_share(w, z):
    occ = w.reaction_occupancy().get(z, {})
    total = sum(occ.values()) or 1
    return (occ.get("shelter", 0) + occ.get("flee", 0)) / total


def test_full_vertical_demo(tmp_path):
    PLAYER_ZONE = 5
    NEIGHBOUR = PLAYER_ZONE * 40 + 3   # a resident of the player's zone (cid 203)

    # 1-2. Enter the city: the player's zone becomes promoted (camera focus).
    w = _city(seed=1)
    w.set_focus([PLAYER_ZONE])
    w.step()
    assert PLAYER_ZONE in w.promoted, "nearby zone did not promote under focus"

    # 3. Citizens are real identified agents with routines.
    zone = w.promoted[PLAYER_ZONE]
    assert (zone.citizen_id >= 0).sum() > 0, "no citizens embodied"
    occ = w.activity_occupancy().get(PLAYER_ZONE, {})
    assert sum(occ.values()) > 0, "no legible activity"
    assert occ.get(npc.activity_name(npc.activity_at_hour(DAY, w.current_hour())), 0) > 0

    # 4-5. Time advances, belief rises (player broadcast), reactions depart routine.
    calm_share = _reaction_share(w, PLAYER_ZONE)
    w.intervene("broadcast", level=1.0)
    for _ in range(8):
        w.step()
    spike_share = _reaction_share(w, PLAYER_ZONE)
    assert spike_share > calm_share, "citizens did not react to the belief spike"
    assert float(w.sim.belief[PLAYER_ZONE]) > 0.0

    # 6. Player interacts -> citizen is in the persistent roster (whether it was
    #    just named by sustained proximity or by this explicit interaction).
    w.interact_with(NEIGHBOUR)
    assert w.roster.contains(NEIGHBOUR)

    # 7. Travel away -> the zone demotes.
    w.set_focus([])
    demoted = False
    for _ in range(80):
        w.step()
        if PLAYER_ZONE not in w.promoted:
            demoted = True
            break
    assert demoted, "zone never demoted after the player left"

    # 8. An intervention changes the future authoritative trajectory (A/B proof
    #    on a forked continuation from the CURRENT state).
    import copy
    # (fork via save/load to guarantee identical starting state)
    fork_path = str(tmp_path / "fork.json")
    save_world(w, fork_path)
    a = load_world_file(fork_path)
    b = load_world_file(fork_path)
    b.intervene("cordon", zones=[a.sim.seed_zone])
    for _ in range(30):
        a.step()
        b.step()

    def infected(world):
        s = world.sim
        return float((s.E + s.Ia + s.Is + s.R + s.D).sum())

    assert infected(a) != infected(b), "cordon did not change the trajectory"

    # 9-10. Continue the real timeline; return; the same person is restored.
    for _ in range(10):
        w.step()
    w.set_focus([PLAYER_ZONE])
    w.step()
    assert PLAYER_ZONE in w.promoted
    zone = w.promoted[PLAYER_ZONE]
    assert (zone.citizen_id == NEIGHBOUR).any(), "befriended citizen not restored"
    assert w.roster.contains(NEIGHBOUR)

    # 11. Save -> fully terminate -> load -> continue deterministically.
    save_path = str(tmp_path / "demo.json")
    save_world(w, save_path, bundle="Houston", player_citizen=NEIGHBOUR)

    # continue the live world one way...
    cont = []
    for _ in range(20):
        w.step()
        cont.append(round(float((w.sim.E + w.sim.Ia + w.sim.Is
                                 + w.sim.R + w.sim.D).sum()), 9))

    # ...and the reloaded (post-termination) world the same way.
    reloaded = load_world_file(save_path)
    assert reloaded.roster.contains(NEIGHBOUR)         # player identity survived
    rel = []
    for _ in range(20):
        reloaded.step()
        rel.append(round(float((reloaded.sim.E + reloaded.sim.Ia + reloaded.sim.Is
                                + reloaded.sim.R + reloaded.sim.D).sum()), 9))

    assert cont == rel, "reloaded world did not continue deterministically"


def test_snapshot_carries_everything_the_renderer_needs():
    """M6 rendering contract: one snapshot exposes anonymous vs identified, disease
    state, activity, chosen_action, named-roster status, position and zone."""
    w = _city(seed=2)
    w.set_focus([5])
    w.intervene("broadcast", level=1.0)
    w.interact_with(5 * 40 + 3)          # befriend a resident of the focused zone
    for _ in range(4):
        w.step()
    snap = w.snapshot()
    ag = snap["agents"][5]
    n = len(ag["positions"])
    for key in ("positions", "state", "citizen_id", "activity",
                "chosen_action", "named"):
        assert len(ag[key]) == n, key
    assert "activity_names" in snap and "action_names" in snap
    assert "roster" in snap and any(r["citizen_id"] == 5 * 40 + 3 for r in snap["roster"])
    cid = np.array(ag["citizen_id"])
    assert (cid >= 0).any() and (cid < 0).any()        # named + anonymous both present
    assert any(ag["named"])                             # at least one roster member drawn


if __name__ == "__main__":
    import pathlib
    import tempfile
    import types
    import inspect
    for name, fn in dict(globals()).items():
        if name.startswith("test_") and isinstance(fn, types.FunctionType):
            if "tmp_path" in inspect.signature(fn).parameters:
                fn(pathlib.Path(tempfile.mkdtemp()))
            else:
                fn()
            print("ok", name)
    print("vertical demo certified")
