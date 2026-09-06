"""GroupRuntime — the survivor-group social layer
(ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1).

A group is built from citizens who remain individuals. This runtime:

* watches the *existing* relationship graph (edge-driven, never all-pairs) for
  clusters with enough real social history — mutual trust/affinity, shared
  danger (``fled_with``), repeated help (``helped_by``), shared household /
  workplace — and forms a persistent group with a traceable cause (§2, §7);
* keeps canonical membership, a shelter chosen from places members actually
  know (§10), shared objectives, roles, a provenance-preserving shared record
  (§23) and bounded group decisions (§17);
* turns a shared objective into an *individual* goal (source ``group``, below
  belief/health/emergency so personal survival always wins — §12, §30) and a
  role request into a real Dialogue V1 exchange (§15, §33);
* spreads group-relevant information only through cognition's own
  ``receive_fact`` / dialogue ``warn`` — never a hive-mind write (§3, §6, §24).

The group never moves a body or writes a belief. Members do, through the
mobility / work / cognition authorities.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..cognition import memory as M
from ..cognition.beliefs import danger_of_building
from ..citizens.goals import Goal, GoalKind
from ..dialogue import acts as A
from ..dialogue.session import FACE_TO_FACE, CALL
from . import model as G

SCHEMA_VERSION = 1

# formation (§7) — bounded, meaningful conditions (not one big friendship threshold)
FORM_SCAN_S = 120.0            # scan for new groups at most every two minutes
FORM_MIN_SIZE = 3             # a survivor group needs at least three
FORM_FAMILIARITY = 0.30       # a plausible acquaintance
FORM_TRUST = 0.45             # more than a stranger's 0.30
FORM_BOND = 0.55             # familiarity+affinity+trust+obligation, averaged, for a strong pair
MEMBER_LEAVE_TRUST = 0.12     # a member whose trust in the group's people collapses leaves (§21)

# shelter (§9, §10)
SHELTER_SAFE_DANGER = 0.45    # a candidate a member believes safer than this
SHELTER_MIN_CAPACITY = 2

# roles / supplies (§13, §26)
SUPPLY_LOW = 1.0             # below this the group needs a supply run
SUPPLY_PER_RUN = 3.0
GUARD_POST_S = 1.0

# knowledge / admission
ANNOUNCE_RADIUS_ROOM = True   # group announcements reach co-present members (§6, §24)


def _avg_bond(r) -> float:
    if r is None:
        return 0.0
    return (r.familiarity + r.affinity + max(0.0, r.trust) + r.obligation) / 4.0


class GroupRuntime:
    def __init__(self, cognition, dialogue=None):
        self.cog = cognition
        self.dialogue = dialogue if dialogue is not None else getattr(cognition, "dialogue", None)
        self.mobility = cognition.mobility
        self.work = cognition.work
        self.now_s = float(cognition.now_s)
        self.groups: Dict[str, G.SurvivorGroup] = {}
        self.member_of: Dict[int, str] = {}         # cid -> group_id (an index; a citizen is in one group in V1)
        self.group_goals: Dict[int, dict] = {}      # cid -> {"goal_id", "kind", "node", "group_id", "role"}
        self.events: List[dict] = []
        self.event_seq = 0
        self.counts: Dict[str, int] = {}
        self.seq = 0
        self._last_form_scan = -1e9
        cognition.groups = self

    # ------------------------------------------------------------------ basics
    def event(self, kind: str, **info) -> dict:
        self.event_seq += 1
        self.counts[kind] = self.counts.get(kind, 0) + 1
        row = {"seq": self.event_seq, "t": round(self.now_s, 1), "event": kind}
        row.update(info)
        self.events.append(row)
        if len(self.events) > 8000:
            del self.events[: len(self.events) - 8000]
        return row

    def _gid(self) -> str:
        self.seq += 1
        return f"group:{self.seq}"

    def group_of(self, cid: int) -> Optional[G.SurvivorGroup]:
        gid = self.member_of.get(int(cid))
        return self.groups.get(gid) if gid else None

    # ================================================================= advance
    def advance(self, dt_s: float) -> None:
        self.now_s += float(dt_s)
        if self.now_s - self._last_form_scan >= FORM_SCAN_S:
            self._last_form_scan = self.now_s
            self._scan_formation()
        for g in list(self.groups.values()):
            self._tick_group(g)

    def _tick_group(self, g: G.SurvivorGroup) -> None:
        # shelter: if none chosen and the group is settled, choose one from member knowledge
        if g.shelter_building is None and g.active_members():
            self.select_shelter(g)
        # drive open objectives to individual goals; retire completed ones
        for o in list(g.objectives.values()):
            self._progress_objective(g, o)
        # keep influence current (cheap; members only)
        self._recompute_influence(g)
        # departures: a member that no longer trusts the group's people leaves (§21)
        self._check_departures(g)

    # ================================================================= formation (§2, §7)
    def _scan_formation(self) -> None:
        """Edge-driven cluster detection. For each ungrouped citizen we look at
        its OWN strong relationship edges (indexed by ``rels.of`` — never an
        all-pairs scan) and try to close a mutually-bonded triangle with a
        traceable social cause. Cost is O(sum of member degrees)."""
        rels = self.cog.rels
        seen = set(self.member_of)
        for a in sorted(self.mobility.execs):
            if a in seen or not self.cog._can_perceive(a):
                continue
            edges = [r for r in rels.of(a) if r.other not in seen and self.cog._can_perceive(r.other)
                     and self._pair_qualifies(a, r.other)]
            if len(edges) < FORM_MIN_SIZE - 1:
                continue
            edges.sort(key=lambda r: (-_avg_bond(r), r.other))
            # try to build a cluster where every pair is mutually bonded
            cluster = [a]
            for r in edges:
                b = r.other
                if all(self._mutual_bond(b, c) for c in cluster):
                    cluster.append(b)
                if len(cluster) >= max(FORM_MIN_SIZE, 4):
                    break
            if len(cluster) >= FORM_MIN_SIZE:
                self._form_group(sorted(cluster))
                for c in cluster:
                    seen.add(c)

    def _pair_qualifies(self, a: int, b: int) -> bool:
        r = self.cog.rels.get(a, b)
        if r is None:
            return False
        return r.familiarity >= FORM_FAMILIARITY and r.trust >= FORM_TRUST and r.hostility < 0.2 \
            and _avg_bond(r) >= FORM_BOND * 0.7

    def _mutual_bond(self, a: int, b: int) -> bool:
        ra, rb = self.cog.rels.get(a, b), self.cog.rels.get(b, a)
        return ra is not None and rb is not None and _avg_bond(ra) >= FORM_BOND * 0.7 \
            and _avg_bond(rb) >= FORM_BOND * 0.7 and ra.hostility < 0.2 and rb.hostility < 0.2

    def _cause(self, cluster: List[int]) -> List[str]:
        """The traceable social history that justifies this group (§2)."""
        causes = []
        rels = self.cog.rels
        for i, a in enumerate(cluster):
            for b in cluster[i + 1:]:
                r = rels.get(a, b)
                if r is None:
                    continue
                if r.origin in ("household", "workplace"):
                    causes.append(f"{r.origin}:{a}-{b}")
                if r.obligation >= 0.4:
                    causes.append(f"helped:{a}-{b}")
                if r.trust >= 0.55 and r.affinity >= 0.3:
                    causes.append(f"trust:{a}-{b}")
        # shared danger: members who each hold a first-hand threat memory
        threatened = [c for c in cluster if any(f.kind in M.THREAT_KINDS and f.first_hand()
                                                for f in (self.cog.memories.get(c).facts.values()
                                                          if self.cog.memories.get(c) else []))]
        if len(threatened) >= 2:
            causes.append(f"shared_danger:{threatened}")
        return causes or ["mutual_trust"]

    def _form_group(self, cluster: List[int]) -> G.SurvivorGroup:
        causes = self._cause(cluster)
        gid = self._gid()
        g = G.SurvivorGroup(gid, self.now_s, founders=list(cluster), formed_reason="; ".join(causes[:6]))
        self.event("GROUP_PROPOSED", group_id=gid, citizens=list(cluster), causes=causes)
        for c in cluster:
            g.set_membership(c, G.MEMBER, self.now_s, cause="founder")
            self.member_of[c] = gid
        self.groups[gid] = g
        self._recompute_influence(g)
        g.coordinator = max(g.active_members(), key=lambda c: (g.influence.get(c, 0.0), -c))
        g.roles[G.COORDINATOR] = g.coordinator
        self.event("GROUP_FORMED", group_id=gid, members=list(cluster), founders=list(cluster),
                   coordinator=g.coordinator, reason=g.formed_reason, causes=causes)
        self.event("ROLE_ACCEPTED", group_id=gid, role=G.COORDINATOR, citizen_id=g.coordinator,
                   reason="highest influence at formation")
        return g

    def _recompute_influence(self, g: G.SurvivorGroup) -> None:
        """Influence = how much the other members, on average, trust+know this
        member, tempered by its loyalty/helpfulness. Emergent, not hardcoded (§16)."""
        members = g.active_members()
        for c in members:
            others = [self.cog.rels.get(o, c) for o in members if o != c]
            others = [r for r in others if r is not None]
            base = sum(0.5 * r.trust + 0.3 * r.familiarity + 0.2 * r.affinity for r in others) / max(1, len(others))
            pers = self.cog.personality(c)
            g.influence[c] = round(base * (0.7 + 0.3 * pers.loyalty) + 0.1 * pers.helpfulness, 4)

    # ================================================================= membership (§5, §21, §22)
    def _check_departures(self, g: G.SurvivorGroup) -> None:
        for c in g.active_members():
            if c in (g.founders[:1] + [g.coordinator]):
                continue
            others = [self.cog.rels.get(c, o) for o in g.active_members() if o != c]
            trust = [r.trust for r in others if r is not None]
            if trust and sum(trust) / len(trust) < MEMBER_LEAVE_TRUST:
                self._depart(g, c, "lost_trust")

    def _depart(self, g: G.SurvivorGroup, cid: int, cause: str) -> None:
        g.set_membership(cid, G.DEPARTED, self.now_s, cause=cause)
        self.member_of.pop(cid, None)
        self._clear_goal(cid)
        for role, holder in list(g.roles.items()):
            if holder == cid:
                g.roles.pop(role, None)
        self.event("MEMBER_LEFT", group_id=g.group_id, citizen_id=cid, cause=cause)

    def expel(self, g: G.SurvivorGroup, cid: int, cause: str, known_by: int) -> bool:
        """Remove a member the group has plausible reason to distrust (§22). It
        requires a member (``known_by``) who actually holds the harmful memory."""
        st = self.cog.memories.get(known_by)
        harmful = st is not None and any(
            f.actor == cid and f.kind in (M.ATTACKED_BY, M.ATTACK_SEEN, M.THREAT_PERSON)
            for f in st.facts.values())
        if not harmful:
            return False
        g.set_membership(cid, G.EXPELLED, self.now_s, cause=cause)
        self.member_of.pop(cid, None)
        self._clear_goal(cid)
        for role, holder in list(g.roles.items()):
            if holder == cid:
                g.roles.pop(role, None)
        self.event("MEMBER_EXPELLED", group_id=g.group_id, citizen_id=cid, cause=cause, known_by=known_by)
        return True

    # ================================================================= shelter (§9, §10)
    def _known_buildings(self, cid: int) -> Dict[int, str]:
        """Buildings this citizen legitimately knows: its home, workplace and
        any node it has metadata for (visited / told). Maps building_id -> a
        representative entrance node. Never the whole city."""
        rt = self.mobility.citizens.get(cid)
        out: Dict[int, str] = {}
        if rt is None:
            return out
        for node, meta in rt.node_meta.items():
            bid = meta.get("building_id")
            if bid is None:
                continue
            if int(bid) not in out or str(node).startswith("ent:"):
                out[int(bid)] = node
        return out

    def _teach_shelter(self, cid: int, bid: int, node: Optional[str]) -> None:
        """Record the shelter address in a member's node metadata so it can
        navigate to and enter a building it was told about (a told location)."""
        rt = self.mobility.citizens.get(cid)
        if rt is None or node is None:
            return
        if node in rt.node_meta:
            return
        xy = None
        try:
            xy = self.mobility.graph.nodes.get(node)
        except Exception:
            xy = None
        rt.node_meta[node] = {"building_id": int(bid), "xy": tuple(xy) if xy is not None else None}

    def _entrance_node(self, g: G.SurvivorGroup, bid: int) -> Optional[str]:
        for c in g.active_members():
            kb = self._known_buildings(c)
            if int(bid) in kb:
                return kb[int(bid)]
        return None

    def select_shelter(self, g: G.SurvivorGroup) -> Optional[int]:
        """Aggregate member-proposed buildings (each from places that member
        knows), score by safety-as-believed, capacity, familiarity and member
        proximity, and pick one. No omniscient city scan (§10)."""
        members = g.active_members()
        if not members:
            return None
        # candidate -> {proposers, node, safety, capacity, familiarity}
        cand: Dict[int, dict] = {}
        for c in members:
            for bid, node in self._known_buildings(c).items():
                bel = self.cog.beliefs(c)
                danger = danger_of_building(bel, bid)
                rt = self.mobility.citizens.get(c)
                is_home = (rt.node_meta.get(rt.home_node) or {}).get("building_id") == bid
                is_work = (rt.node_meta.get(rt.work_node) or {}).get("building_id") == bid
                row = cand.setdefault(bid, {"proposers": [], "node": node, "danger": 0.0,
                                            "home": 0, "work": 0})
                row["proposers"].append(c)
                row["danger"] = max(row["danger"], danger)
                row["home"] += int(is_home)
                row["work"] += int(is_work)
                if str(node).startswith("ent:"):
                    row["node"] = node
        if not cand:
            return None
        cap = self._capacity_of
        scored = []
        for bid, row in cand.items():
            capacity = cap(bid)
            if capacity < SHELTER_MIN_CAPACITY or row["danger"] >= SHELTER_SAFE_DANGER:
                self.event("SHELTER_PROPOSED", group_id=g.group_id, building_id=bid, rejected=True,
                           proposers=sorted(row["proposers"]), danger=round(row["danger"], 3), capacity=capacity)
                continue
            # a member's home is a defensible, familiar shelter; a workplace is public and
            # exposed, so it earns no shelter bonus even though more members know it.
            score = (len(set(row["proposers"])) * 0.5 + row["home"] * 2.5
                     + (1.0 - row["danger"]) + min(1.0, capacity / 6.0) * 0.5)
            scored.append((score, bid, row, capacity))
            self.event("SHELTER_PROPOSED", group_id=g.group_id, building_id=bid, rejected=False,
                       proposers=sorted(set(row["proposers"])), danger=round(row["danger"], 3),
                       capacity=capacity, score=round(score, 3))
        if not scored:
            return None
        scored.sort(key=lambda x: (-x[0], x[1]))
        # a bounded group decision records member preferences (§17, §31)
        top = [str(bid) for _, bid, _, _ in scored[:3]]
        if len(scored) >= 2:
            self._decide(g, "shelter", top, weight_fn=lambda c: g.influence.get(c, 0.1),
                         prefer_fn=lambda c: self._member_shelter_pref(c, scored))
        _, bid, row, capacity = scored[0]
        node = self._entrance_node(g, bid) or row["node"]
        old = g.shelter_building
        g.shelter_building, g.shelter_node = bid, node
        g.shelter_room = self._entrance_room(bid)
        g.entrance_room = g.shelter_room
        g.shelter_history.append({"t": round(self.now_s, 1), "building_id": bid, "from": old,
                                  "capacity": capacity})
        # the group communicates the shelter address so every member knows where to regroup
        # (§23 "shelter address"; §34). A member who was told the address can now navigate to
        # and enter it; a member the address never reaches cannot (the GQ2 counterfactual).
        for c in members:
            self._teach_shelter(c, bid, node)
        self.event("SHELTER_SELECTED", group_id=g.group_id, building_id=bid, room_id=g.shelter_room,
                   node=node, capacity=capacity, proposers=sorted(set(row["proposers"])),
                   danger=round(row["danger"], 3))
        # everyone regroups: a REACH_SHELTER objective becomes each member's group goal (§12)
        for c in members:
            self._create_objective(g, G.REACH_SHELTER, assignee=c, building_id=bid, room_id=g.shelter_room,
                                   reason="regroup at chosen shelter")
        return bid

    def _member_shelter_pref(self, c: int, scored) -> str:
        """A member prefers the safest place it proposed, else the top overall."""
        mine = [(s, bid) for s, bid, row, _ in scored if c in row["proposers"]]
        if mine:
            mine.sort(key=lambda x: (-x[0], x[1]))
            return str(mine[0][1])
        return str(scored[0][1])

    def _capacity_of(self, bid: int) -> int:
        """Rooms the building has (a proxy for how many it can shelter)."""
        if self.work is None:
            return SHELTER_MIN_CAPACITY
        try:
            occ = self.work.occupants_by_room(int(bid))
            return max(6, len(occ) + 4)     # a building can shelter several beyond its usual rooms
        except Exception:
            return 6

    def _entrance_room(self, bid: int) -> Optional[int]:
        if self.work is None:
            return 0
        try:
            rooms = sorted(self.work.occupants_by_room(int(bid)))
            return rooms[0] if rooms else 0
        except Exception:
            return 0

    # ================================================================= objectives -> goals (§12)
    def _create_objective(self, g: G.SurvivorGroup, kind: str, *, assignee=None, target_cid=None,
                          building_id=None, room_id=None, object_id=None, role=None,
                          reason="") -> G.Objective:
        o = G.Objective(g.nid("obj"), kind, target_cid=target_cid, building_id=building_id, room_id=room_id,
                        object_id=object_id, role=role, assignee=assignee, created_s=self.now_s, reason=reason)
        g.objectives[o.obj_id] = o
        self.event("GROUP_OBJECTIVE_CREATED", group_id=g.group_id, obj_id=o.obj_id, obj_kind=kind,
                   assignee=assignee, building_id=building_id, room_id=room_id, role=role, reason=reason)
        return o

    def _progress_objective(self, g: G.SurvivorGroup, o: G.Objective) -> None:
        if o.state in (G.OBJ_DONE, G.OBJ_FAILED, G.OBJ_CANCELLED):
            return
        if o.kind == G.REACH_SHELTER and o.assignee is not None:
            cid = o.assignee
            if not g.is_member(cid):
                o.state = G.OBJ_CANCELLED
                return
            if o.state == G.OBJ_OPEN:
                o.state = G.OBJ_ACTIVE
            ex = self.mobility.execs.get(cid)
            if ex is not None and ex.inside and int(ex.building_id) == int(o.building_id) and o.detail != "arrived":
                o.detail = "arrived"
                o.decided_s = self.now_s
                self.event("ROLE_COMPLETED", group_id=g.group_id, obj_id=o.obj_id, obj_kind=o.kind,
                           citizen_id=cid, building_id=o.building_id)
            # a DO_ACTIVITY rest holds the member AT the shelter once it arrives (it does not
            # wander back to a schedule), which is how the group keeps everyone regrouped.
            self._travel_goal(cid, g.shelter_node, priority=0.62,
                              reason=f"regroup at group {g.group_id} shelter {o.building_id}",
                              group_id=g.group_id, kind=o.kind, hold=True)
        elif o.kind == G.WATCH_ENTRANCE and o.assignee is not None and o.state == G.OBJ_ACTIVE:
            self._tick_guard(g, o)
        elif o.kind == G.SEEK_SUPPLIES and o.assignee is not None and o.state == G.OBJ_ACTIVE:
            self._tick_scavenger(g, o)
        elif o.kind == G.LOCATE_MEMBER and o.assignee is not None and o.state == G.OBJ_ACTIVE:
            self._tick_locator(g, o)

    def _travel_goal(self, cid: int, node: Optional[str], *, priority: float, reason: str,
                     group_id: str, kind: str, activity: str = "rest", hold: bool = False) -> None:
        if node is None:
            return
        rt = self.mobility.citizens.get(cid)
        if rt is None:
            return
        ag = rt.active_goal
        # individual survival always wins (§30): never fight an emergency/health/belief goal
        if ag is not None and ag.source in ("emergency", "health", "disruption", "belief", "player"):
            return
        held = self.group_goals.get(cid)
        if held and held.get("node") == node and any(x.id == held.get("goal_id") for x in rt.goals.goals):
            return
        # a "hold" goal (DO_ACTIVITY rest) both travels to the node and keeps the member there;
        # a transient goal (ARRIVE_AT) just gets it there (a scavenger leaving, a locator searching).
        kind_g = GoalKind.DO_ACTIVITY if hold else GoalKind.ARRIVE_AT
        goal = Goal(kind_g, target=node, source="group", priority=priority,
                    activity=activity, reason=reason)
        rt.push_goal(goal, self.mobility.graph)
        self.group_goals[cid] = {"goal_id": goal.id, "node": node, "group_id": group_id, "kind": kind}

    def _clear_goal(self, cid: int) -> None:
        held = self.group_goals.pop(cid, None)
        rt = self.mobility.citizens.get(cid)
        if held and rt is not None:
            for gl in list(rt.goals.goals):
                if gl.id == held.get("goal_id") and gl.source == "group":
                    rt.goals.remove(gl.id)
                    if rt.active_goal is not None and rt.active_goal.id == gl.id:
                        rt.active_goal = None

    def at_shelter(self, g: G.SurvivorGroup, cid: int) -> bool:
        ex = self.mobility.execs.get(cid)
        return ex is not None and ex.inside and g.shelter_building is not None \
            and int(ex.building_id) == int(g.shelter_building)

    # ================================================================= roles (§13-§20, §28)
    def assign_role(self, g: G.SurvivorGroup, role: str, *, dialogue: bool = True) -> Optional[dict]:
        """Choose the best available member for ``role`` from real member state
        and ask them through Dialogue V1. Returns the exchange result or None."""
        cand = self._role_candidate(g, role)
        if cand is None:
            return None
        cid, score, comps = cand
        obj_kind = {G.GUARD: G.WATCH_ENTRANCE, G.SCAVENGER: G.SEEK_SUPPLIES}.get(role, G.MAINTAIN_SHELTER)
        o = self._create_objective(g, obj_kind, assignee=cid, role=role,
                                   building_id=g.shelter_building, room_id=g.entrance_room,
                                   reason=f"group needs a {role}")
        self.event("ROLE_PROPOSED", group_id=g.group_id, role=role, citizen_id=cid, obj_id=o.obj_id,
                   score=round(score, 3), components=comps)
        accept, reason = self._role_decision(g, cid, role, score)
        if dialogue and self.dialogue is not None:
            self._render_role_request(g, cid, role, accept, reason, o)
        if accept:
            g.roles[role] = cid
            o.state = G.OBJ_ACTIVE
            o.decided_s = self.now_s
            # the member now does the role rather than just resting: retire its regroup hold
            # so the role objective (a guard post, a supply run) drives its goal cleanly
            for oo in g.objectives.values():
                if oo.kind == G.REACH_SHELTER and oo.assignee == cid and oo is not o:
                    oo.state = G.OBJ_CANCELLED
            self._clear_goal(cid)
            self.event("ROLE_ACCEPTED", group_id=g.group_id, role=role, citizen_id=cid, obj_id=o.obj_id)
            # relationship: taking a risk for the group raises obligation toward the coordinator
            if g.coordinator is not None and g.coordinator != cid:
                self.cog.relate(g.coordinator, cid, "helped_by")
        else:
            o.state = G.OBJ_CANCELLED
            o.reason = reason
            self.event("ROLE_REFUSED", group_id=g.group_id, role=role, citizen_id=cid, obj_id=o.obj_id,
                       reason=reason)
        return {"citizen_id": cid, "role": role, "accept": accept, "reason": reason, "score": score}

    def _role_candidate(self, g: G.SurvivorGroup, role: str) -> Optional[Tuple[int, float, dict]]:
        best = None
        for c in g.active_members():
            if c in g.roles.values():
                continue
            if not self.cog._can_perceive(c) or not self.at_shelter(g, c):
                continue
            score, comps = self._role_fit(g, c, role)
            if best is None or (score, -c) > (best[1], -best[0]):
                best = (c, score, comps)
        return best

    def _role_fit(self, g: G.SurvivorGroup, cid: int, role: str) -> Tuple[float, dict]:
        """Fit considers availability, trust (influence), work history, personality
        and health — never random (§14, §16)."""
        pers = self.cog.personality(cid)
        infl = g.influence.get(cid, 0.1)
        a = self.work.activities.get(cid) if self.work is not None else None
        emp = self.work.employment.get(cid) if self.work is not None else None
        role_hist = 0.0
        if role == G.SCAVENGER and emp is not None and getattr(emp, "role", "") in ("stocker", "cleaner", "cashier"):
            role_hist = 0.4
        if role == G.GUARD and pers.risk_tolerance >= 0.5:
            role_hist = 0.3
        comps = {"influence": round(infl, 3), "loyalty": round(pers.loyalty, 3),
                 "risk_tolerance": round(pers.risk_tolerance, 3), "role_history": role_hist,
                 "free": a is None or a.kind != "worker" or a.help_for < 0}
        risk = pers.risk_tolerance if role in (G.GUARD, G.SCAVENGER) else 0.5
        score = 0.4 * infl + 0.25 * pers.loyalty + 0.2 * risk + role_hist
        return score, comps

    def _role_decision(self, g: G.SurvivorGroup, cid: int, role: str, score: float) -> Tuple[bool, str]:
        """The member decides for itself (§30): it refuses a dangerous role when
        frightened, hurt, or with little loyalty/obligation to the group."""
        pers = self.cog.personality(cid)
        # a fresh first-hand threat, or being unwell, overrides any group role
        st = self.cog.memories.get(cid)
        scared = st is not None and any(f.kind in M.THREAT_KINDS and f.first_hand()
                                        and self.now_s - f.last_t < 600 for f in st.facts.values())
        if scared and role in (G.GUARD, G.SCAVENGER):
            return False, "too_dangerous"
        rel_to_coord = self.cog.rels.get(cid, g.coordinator) if g.coordinator is not None else None
        obligation = rel_to_coord.obligation if rel_to_coord is not None else 0.0
        willing = 0.3 * pers.loyalty + 0.3 * pers.helpfulness + 0.2 * obligation + 0.2 * pers.risk_tolerance
        if role in (G.GUARD, G.SCAVENGER):
            willing -= 0.15 * (1.0 - pers.risk_tolerance)
        return (willing >= 0.30, "" if willing >= 0.30 else "unwilling")

    def _render_role_request(self, g, cid, role, accept, reason, o) -> None:
        """Render the role request as a real Dialogue V1 exchange (§15, §33)."""
        d = self.dialogue
        coord = g.coordinator if g.coordinator is not None else cid
        if coord == cid or d is None:
            return
        conv = d._start(coord, cid, self._channel(coord, cid), topic={"kind": "group_role", "role": role,
                                                                       "group_id": g.group_id})
        d.say(conv, coord, A.ASSIGN_ROLE, reason=role)
        d.say(conv, cid, A.ACCEPT if accept else A.REFUSE, reason=reason)
        d._end(conv, "role_" + ("accepted" if accept else "refused"))

    def _channel(self, a: int, b: int):
        from ..dialogue.session import FACE_TO_FACE, CALL
        if self.dialogue is not None and self.dialogue.co_present(a, b)[0]:
            return FACE_TO_FACE
        return CALL

    # ------------------------------------------------------------------ guard (§28)
    def _tick_guard(self, g: G.SurvivorGroup, o: G.Objective) -> None:
        cid = o.assignee
        if not g.is_member(cid):
            o.state = G.OBJ_CANCELLED
            g.roles.pop(G.GUARD, None)
            return
        node = g.shelter_node
        # abandon the post under a fresh first-hand threat, but warn the group first (§28, §30)
        st = self.cog.memories.get(cid)
        threat = None
        if st is not None:
            for f in st.facts.values():
                if f.kind in M.THREAT_KINDS and f.first_hand() and self.now_s - f.last_t < 30:
                    threat = f
                    break
        if threat is not None:
            self.warn_group(g, cid, threat)
            self._clear_goal(cid)
            self.event("ROLE_COMPLETED", group_id=g.group_id, obj_id=o.obj_id, obj_kind=o.kind,
                       citizen_id=cid, reason="threat_at_post")
            o.state = G.OBJ_DONE
            self._raise_alert(g, cid)
            return
        # otherwise hold the post
        self._travel_goal(cid, node, priority=0.62, reason="watch the entrance",
                          group_id=g.group_id, kind=o.kind, activity="rest", hold=True)

    # ------------------------------------------------------------------ supply (§26, §27)
    def check_supplies(self, g: G.SurvivorGroup) -> Optional[dict]:
        need = g.supplies.get("food", 0.0)
        if need > SUPPLY_LOW or g.shelter_building is None:
            return None
        self.event("SUPPLY_NEED", group_id=g.group_id, resource="food", have=need, threshold=SUPPLY_LOW)
        return self.assign_role(g, G.SCAVENGER)

    def _supply_source(self, g: G.SurvivorGroup, cid: int) -> Optional[Tuple[int, str, str]]:
        """A shop the scavenger legitimately KNOWS (in its node_meta) that has a
        browsable/stocked object — never a citywide best-shelf query (§27)."""
        if self.work is None:
            return None
        for bid, node in sorted(self._known_buildings(cid).items()):
            if g.shelter_building is not None and int(bid) == int(g.shelter_building):
                continue
            try:
                reg = self.work.registry(int(bid))
            except Exception:
                continue
            if reg is None:
                continue
            shelves = reg.with_caps("stock") if hasattr(reg, "with_caps") else []
            for o in shelves:
                if o.state.get("stock", 0) > 0:
                    return int(bid), node, o.object_id
        return None

    def _tick_scavenger(self, g: G.SurvivorGroup, o: G.Objective) -> None:
        cid = o.assignee
        if not g.is_member(cid):
            o.state = G.OBJ_CANCELLED
            g.roles.pop(G.SCAVENGER, None)
            return
        ex = self.mobility.execs.get(cid)
        # phase 1: travel to a known source; phase 2 (acquired) return to shelter
        if o.detail == "acquired":
            if self.at_shelter(g, cid):
                g.supplies["food"] = g.supplies.get("food", 0.0) + SUPPLY_PER_RUN
                o.state = G.OBJ_DONE
                o.decided_s = self.now_s
                g.roles.pop(G.SCAVENGER, None)
                self._clear_goal(cid)
                self.event("SUPPLY_RETURNED", group_id=g.group_id, citizen_id=cid, resource="food",
                           amount=SUPPLY_PER_RUN, have=round(g.supplies["food"], 2), building_id=g.shelter_building)
                return
            self._travel_goal(cid, g.shelter_node, priority=0.62, reason="return supplies",
                              group_id=g.group_id, kind=o.kind)
            return
        if o.building_id is None:
            src = self._supply_source(g, cid)
            if src is None:
                o.state = G.OBJ_FAILED
                o.reason = "no_known_source"
                g.roles.pop(G.SCAVENGER, None)
                self.event("ROLE_REFUSED", group_id=g.group_id, role=G.SCAVENGER, citizen_id=cid,
                           reason="no_known_source", obj_id=o.obj_id)
                return
            o.building_id, o.detail_node, o.object_id = src[0], src[1], src[2]  # type: ignore[attr-defined]
            self.event("SUPPLY_RUN_ASSIGNED", group_id=g.group_id, citizen_id=cid, source_building=src[0],
                       object_id=src[2], node=src[1], obj_id=o.obj_id)
        if ex is not None and ex.inside and int(ex.building_id) == int(o.building_id):
            # interact with the real Smart Object: take stock
            try:
                reg = self.work.registry(int(o.building_id))
                obj = reg.get(o.object_id) if reg is not None else None
            except Exception:
                obj = None
            if obj is not None and obj.state.get("stock", 0) > 0:
                self.work.set_object_state(o.object_id, "stock", max(0, int(obj.state.get("stock", 0)) - 1))
                o.detail = "acquired"
                self.event("SUPPLY_ACQUIRED", group_id=g.group_id, citizen_id=cid, resource="food",
                           source_building=o.building_id, object_id=o.object_id, obj_id=o.obj_id)
                self._clear_goal(cid)
                self._travel_goal(cid, g.shelter_node, priority=0.62, reason="return supplies",
                                  group_id=g.group_id, kind=o.kind)
            else:
                o.state = G.OBJ_FAILED
                o.reason = "source_empty"
                g.roles.pop(G.SCAVENGER, None)
            return
        node = getattr(o, "detail_node", None) or self._entrance_node(g, o.building_id)
        self._travel_goal(cid, node, priority=0.62, reason="go for supplies", group_id=g.group_id, kind=o.kind)

    # ------------------------------------------------------------------ locate member (§25)
    def locate_member(self, g: G.SurvivorGroup, missing: int) -> Optional[dict]:
        """A member is expected but absent; a member who knows where it usually
        is volunteers to go find it."""
        if g.shelter_building is None:
            return None
        finder = None
        for c in g.active_members():
            if c == missing or not self.at_shelter(g, c):
                continue
            rt = self.mobility.citizens.get(missing)
            if rt is None:
                continue
            # the finder knows the missing member's home/work node
            if self.mobility.citizens.get(c) is not None and (rt.home_node in self.mobility.citizens[c].node_meta):
                finder = c
                break
        finder = finder or next((c for c in g.active_members() if c != missing and self.at_shelter(g, c)), None)
        if finder is None:
            return None
        rt = self.mobility.citizens.get(missing)
        node = rt.home_node if rt is not None else None
        o = self._create_objective(g, G.LOCATE_MEMBER, assignee=finder, target_cid=missing,
                                   reason=f"member {missing} missing from shelter")
        o.state = G.OBJ_ACTIVE
        o.building_id = (rt.node_meta.get(node) or {}).get("building_id") if rt is not None else None
        setattr(o, "detail_node", node)
        self.event("GROUP_OBJECTIVE_CREATED", group_id=g.group_id, obj_id=o.obj_id, obj_kind=G.LOCATE_MEMBER,
                   assignee=finder, target_cid=missing)
        return {"finder": finder, "missing": missing}

    def _tick_locator(self, g: G.SurvivorGroup, o: G.Objective) -> None:
        finder, missing = o.assignee, o.target_cid
        if not g.is_member(finder):
            o.state = G.OBJ_CANCELLED
            return
        # reached the missing member (co-present) -> report back
        if self.dialogue is not None and self.dialogue.co_present(finder, missing)[0]:
            o.state = G.OBJ_DONE
            o.decided_s = self.now_s
            self._clear_goal(finder)
            self.event("MEMBER_LOCATED", group_id=g.group_id, finder=finder, citizen_id=missing,
                       building_id=(self.mobility.execs.get(missing).building_id
                                    if self.mobility.execs.get(missing) and self.mobility.execs[missing].inside else None))
            return
        self._travel_goal(finder, getattr(o, "detail_node", None), priority=0.62,
                          reason=f"find member {missing}", group_id=g.group_id, kind=o.kind)

    # ================================================================= group knowledge (§23, §24)
    def warn_group(self, g: G.SurvivorGroup, reporter: int, fact: M.MemoryFact) -> dict:
        """A member reports a group-relevant threat. It is recorded in the shared
        record (with provenance) and told to co-present members through the
        legitimate dialogue channel — NOT written into every member's mind. An
        uncontacted member stays uninformed (§24)."""
        gf = self._record_fact(g, reporter, fact, kind="threat_location")
        told = []
        for m in g.active_members():
            if m == reporter or not self.cog._can_perceive(m):
                continue
            if self.dialogue is not None and self.dialogue.co_present(reporter, m)[0]:
                if self.dialogue.warn(reporter, m, fact, FACE_TO_FACE):
                    told.append(m)
                    if m not in gf.recipients:
                        gf.recipients.append(m)
        self.event("GROUP_WARNING", group_id=g.group_id, reporter=reporter, fact_id=gf.fact_id,
                   subject=fact.actor, building_id=fact.building_id, room_id=fact.room_id,
                   told=told, uncontacted=[m for m in g.active_members()
                                           if m != reporter and m not in told])
        return {"fact_id": gf.fact_id, "told": told}

    def _record_fact(self, g: G.SurvivorGroup, reporter: int, fact: M.MemoryFact, kind: str) -> G.GroupFact:
        fid = g.nid("fact")
        gf = G.GroupFact(fid, kind, subject=fact.actor, building_id=fact.building_id, room_id=fact.room_id,
                         origin_witness=fact.origin_witness, source_citizen=reporter,
                         confidence=round(fact.effective(self.now_s), 4), t=self.now_s, recipients=[reporter])
        g.shared_record[fid] = gf
        return gf

    # ================================================================= admission (§18-§20, §34)
    def request_admission(self, g: G.SurvivorGroup, outsider: int, *, via_member: Optional[int] = None) -> dict:
        """An outsider asks to join. Members who can perceive/know it evaluate on
        their OWN knowledge (trust, relationship, known threat) and capacity; the
        coordinator resolves. Grounded, not a global reputation lookup (§18)."""
        app = G.Application(g.nid("app"), int(outsider), kind="application", by=via_member,
                            created_s=self.now_s)
        g.applications[app.app_id] = app
        self.event("ADMISSION_REQUESTED", group_id=g.group_id, app_id=app.app_id, subject=outsider,
                   via_member=via_member)
        # each member who can assess votes from what it individually knows
        voters = [m for m in g.active_members() if self.cog._can_perceive(m)]
        for m in voters:
            support, why = self._assess_outsider(m, outsider, g)
            app.votes[m] = [round(support, 3), why]
        capacity_ok = len(g.active_members()) < self._capacity_of(g.shelter_building or -1)
        # aggregate weighted by influence; the coordinator has the final bounded say
        num = sum(g.influence.get(m, 0.1) * v[0] for m, v in app.votes.items())
        den = sum(g.influence.get(m, 0.1) for m in app.votes) or 1.0
        agg = num / den
        threat_known = any(v[1] == "known_threat" for v in app.votes.values())
        accept = capacity_ok and not threat_known and agg >= 0.10
        app.state = "accepted" if accept else "refused"
        app.decided_s = self.now_s
        app.reason = ("capacity_full" if not capacity_ok else "known_threat" if threat_known
                      else ("group_agrees" if accept else "insufficient_trust"))
        self._decide(g, "admission", ["accept", "refuse"],
                     weight_fn=lambda c: g.influence.get(c, 0.1),
                     prefer_fn=lambda c: "accept" if app.votes.get(c, [0])[0] >= 0.1 else "refuse",
                     outcome=("accept" if accept else "refuse"))
        if accept:
            g.set_membership(outsider, G.PROVISIONAL, self.now_s, cause="admitted")
            self.member_of[outsider] = g.group_id
            self.event("ADMISSION_ACCEPTED", group_id=g.group_id, app_id=app.app_id, subject=outsider,
                       aggregate=round(agg, 3), reason=app.reason)
        else:
            # refusal has consequences (§20): the outsider's regard for the refusers cools
            for m in voters:
                self.cog.relate(int(outsider), m, "refused_by")
            self.event("ADMISSION_REFUSED", group_id=g.group_id, app_id=app.app_id, subject=outsider,
                       aggregate=round(agg, 3), reason=app.reason)
        if self.dialogue is not None and voters:
            self._render_admission(g, outsider, voters[0], accept, app.reason)
        return {"app_id": app.app_id, "accept": accept, "reason": app.reason, "aggregate": round(agg, 3),
                "votes": {m: v for m, v in app.votes.items()}}

    def _assess_outsider(self, member: int, outsider: int, g: G.SurvivorGroup) -> Tuple[float, str]:
        r = self.cog.rels.get(member, outsider)
        st = self.cog.memories.get(member)
        # a member who has seen the outsider be a threat blocks admission
        if st is not None and any(f.actor == outsider and f.kind in (M.ATTACKED_BY, M.ATTACK_SEEN, M.THREAT_PERSON)
                                  for f in st.facts.values()):
            return -1.0, "known_threat"
        if r is None:
            return 0.0, "stranger"
        if r.hostility >= 0.3 or r.trust < 0.2:
            return -0.5, "distrust"
        support = 0.5 * r.trust + 0.3 * r.affinity + 0.2 * min(1.0, r.obligation) - 0.5 * r.fear
        why = "known_helpful" if r.obligation >= 0.3 or r.trust >= 0.5 else "acquainted"
        return support, why

    def _render_admission(self, g, outsider, member, accept, reason) -> None:
        d = self.dialogue
        if d is None:
            return
        conv = d._start(outsider, member, self._channel(outsider, member),
                        topic={"kind": "admission", "group_id": g.group_id})
        d.say(conv, outsider, A.ASK_TO_JOIN)
        d.say(conv, member, A.ACCEPT_MEMBER if accept else A.REFUSE_MEMBER, reason=reason)
        d._end(conv, "admission_" + ("accepted" if accept else "refused"))

    # ================================================================= decisions (§17, §31)
    def _decide(self, g: G.SurvivorGroup, kind: str, options: List[str], *, weight_fn, prefer_fn,
                outcome: Optional[str] = None) -> G.Decision:
        d = G.Decision(g.nid("dec"), kind, options=list(options), created_s=self.now_s)
        tally: Dict[str, float] = {o: 0.0 for o in options}
        for c in g.active_members():
            pref = prefer_fn(c)
            w = max(0.0, weight_fn(c))
            d.votes[c] = [pref, round(w, 3)]
            if pref in tally:
                tally[pref] += w
        if outcome is None:
            outcome = max(sorted(tally), key=lambda o: tally[o]) if tally else (options[0] if options else None)
        d.outcome = outcome
        d.resolved_by = g.coordinator
        d.resolved_s = self.now_s
        # preserve disagreement: note dissenters
        dissent = sorted(c for c, v in d.votes.items() if v[0] != outcome)
        d.detail = f"tally={ {o: round(t,2) for o,t in tally.items()} } dissent={dissent}"
        g.decisions[d.dec_id] = d
        self.event("GROUP_DECISION", group_id=g.group_id, dec_id=d.dec_id, decision_kind=kind, outcome=outcome,
                   options=options, tally={o: round(t, 3) for o, t in tally.items()}, dissent=dissent,
                   resolved_by=g.coordinator)
        return d

    # ================================================================= threat response (§29, §30)
    def _raise_alert(self, g: G.SurvivorGroup, reporter: int) -> None:
        if g.threat_state == G.CALM:
            g.threat_state = G.ALERTED
            self.event("GROUP_DECISION", group_id=g.group_id, dec_id=g.nid("dec"), decision_kind="threat_posture",
                       outcome=G.ALERTED, reporter=reporter)

    def evacuate(self, g: G.SurvivorGroup, reason: str = "threat") -> dict:
        """A bounded collective evacuation: the group abandons the shelter and
        members flee/regroup elsewhere through their own goals (§29)."""
        g.threat_state = G.EVACUATING
        moved = []
        # pick a fallback the members know that is not the (now dangerous) shelter
        for c in g.active_members():
            self._clear_goal(c)
            rt = self.mobility.citizens.get(c)
            if rt is not None:
                # let cognition's own avoidance/flee take over; just drop the group hold
                moved.append(c)
        self.event("GROUP_EVACUATED", group_id=g.group_id, reason=reason, members=moved,
                   from_building=g.shelter_building)
        for o in g.objectives.values():
            if o.state in (G.OBJ_OPEN, G.OBJ_ACTIVE, G.OBJ_ASSIGNED):
                o.state = G.OBJ_CANCELLED
        return {"members": moved, "from": g.shelter_building}

    # ================================================================= queries / player (§34)
    def group_summary(self, gid: str) -> Optional[dict]:
        g = self.groups.get(gid)
        return None if g is None else g.to_state()

    def where_is_group(self, cid: int) -> Optional[dict]:
        g = self.group_of(cid)
        if g is None:
            return None
        return {"group_id": g.group_id, "shelter_building": g.shelter_building,
                "shelter_room": g.shelter_room, "members": g.active_members()}

    def snapshot(self, since_seq: int = 0) -> dict:
        return {"version": SCHEMA_VERSION, "now_s": round(self.now_s, 3),
                "groups": {gid: g.to_state() for gid, g in sorted(self.groups.items())},
                "member_of": {str(c): gid for c, gid in sorted(self.member_of.items())},
                "events": [e for e in self.events if e["seq"] > int(since_seq)],
                "event_seq": self.event_seq, "counts": dict(sorted(self.counts.items()))}

    def row(self, cid: int) -> dict:
        g = self.group_of(cid)
        if g is None:
            return {"group": None}
        role = next((r for r, c in g.roles.items() if c == cid), None)
        return {"group": g.group_id, "role": role, "shelter": g.shelter_building,
                "members": len(g.active_members()), "threat": g.threat_state}

    # ================================================================= persistence (§36)
    def to_state(self) -> dict:
        return {"version": SCHEMA_VERSION, "now_s": self.now_s, "seq": self.seq,
                "groups": {gid: g.to_state() for gid, g in sorted(self.groups.items())},
                "member_of": {str(c): gid for c, gid in sorted(self.member_of.items())},
                "group_goals": {str(c): v for c, v in sorted(self.group_goals.items())},
                "events": list(self.events), "event_seq": self.event_seq,
                "counts": dict(sorted(self.counts.items())), "last_form_scan": self._last_form_scan}

    @classmethod
    def from_state(cls, st: dict, cognition, dialogue=None) -> "GroupRuntime":
        r = cls(cognition, dialogue)
        r.now_s = float(st.get("now_s", cognition.now_s))
        r.seq = int(st.get("seq", 0))
        r.groups = {gid: G.SurvivorGroup.from_state(v) for gid, v in st.get("groups", {}).items()}
        r.member_of = {int(c): gid for c, gid in st.get("member_of", {}).items()}
        r.group_goals = {int(c): v for c, v in st.get("group_goals", {}).items()}
        r.events = list(st.get("events", []))
        r.event_seq = int(st.get("event_seq", 0))
        r.counts = dict(st.get("counts", {}))
        r._last_form_scan = float(st.get("last_form_scan", -1e9))
        return r
