| gate | requirement | status | evidence |
|---|---|---|---|
| G1 | Stable group identity | PASS | group group:1, founders [42, 87, 117], created 7800.0 |
| G2 | Certified group forms during simulation | PASS | 1 GROUP_FORMED during the run at t=7800.0 |
| G3 | Formation caused by actual social history | PASS | formation cause: workplace:42-87; helped:42-87; trust:42-87; workplace:42-117; helped:42-117; trust:42-117 |
| G4 | No arbitrary pre-seeded group | PASS | no group existed before cooperation; formation event is timestamped mid-run |
| G5 | Individual cognition remains authoritative | PASS | each member has its own memory store and goal stack |
| G6 | Membership states persist | PASS | 4 membership transitions, states ['member', 'provisional'] |
| G7 | Membership changes through valid social actions | PASS | every membership change carries a cause, e.g. {'t': 7800.0, 'cid': 42, 'old': None, 'new': 'member', 'cause': 'founder'} |
| G8 | No omniscient group knowledge | PASS | a group warning reached only co-present members [], not the whole group |
| G9 | Group information preserves provenance | PASS | 1 shared-record facts, each with origin witness + source + confidence |
| G10 | Real shelter selected | PASS | shelter 6353 room 0 selected from 14 proposals |
| G11 | Shelter candidates come from member knowledge | PASS | every shelter candidate came from a member's own knowledge |
| G12 | Members physically regroup at shelter | PASS | 3 members physically regrouped at the shelter by 11.5: [42, 87, 117] |
| G13 | Shared goal grammar exists | NOT_RUN |  |
| G14 | Group objective becomes individual goal | NOT_RUN |  |
| G15 | At least three meaningful roles | PASS | roles filled: ['coordinator', 'guard', 'scavenger'] |
| G16 | Role assignment considers member state | PASS | role proposals carry member-state components, e.g. {'influence': 0.788, 'loyalty': 0.596, 'risk_tolerance': 0.667, 'role_history': 0.3, 'free': True} |
| G17 | Role request uses dialogue/cognition | PASS | 2 role requests spoken through Dialogue V1 |
| G18 | Accepted role creates real action | PASS | guard 87 accepted -> objective WATCH_ENTRANCE cancelled |
| G19 | Refused role does not create action | PASS | 0 refused roles created no active objective |
| G20 | Guard/watch behavior occurs physically | PASS | guard 87 physically holding the shelter post: True |
| G21 | Supply need detected | PASS | 1 supply-need detections |
| G22 | Supply run uses known source | FAIL | supply run to a known source building None |
| G23 | Supply runner physically travels and interacts | FAIL | scavenger physically reached and used Smart Object None |
| G24 | Supply result changes group state | FAIL | supplies returned: group food now 0.0 |
| G25 | Stranger can request admission | PASS | outsider 0 requested admission |
| G26 | Admission uses knowledge/relationships/capacity | PASS | admission graded on each member's own knowledge: {42: [0.427, 'known_helpful'], 87: [0.0, 'stranger'], 117: [0.0, 'stranger']} |
| G27 | Acceptance changes membership | PASS | acceptance changed membership: outsider in members = True |
| G28 | Refusal preserves non-membership | PASS | a refused outsider stays out: {'accept': False, 'reason': 'insufficient_trust', 'aggregate': 0.0} |
| G29 | Members can disagree | PASS | 3 group decisions, 2 with recorded dissent |
| G30 | Bounded decision protocol resolves a disagreement | NOT_RUN |  |
| G31 | Threat warning propagates through legitimate channels | FAIL | group warning told [] through the legitimate dialogue channel |
| G32 | Unwarned member remains uninformed | PASS | uncontacted members stayed uninformed: [0, 87, 117] |
| G33 | Threat causes collective multi-member response | PASS | evacuation moved 4 members collectively |
| G34 | Individual emergency can override group role | PASS | a frightened member refuses a group role (survival overrides): {'accept': False, 'reason': 'too_dangerous', 'citizen': 87} |
| G35 | Member can voluntarily leave | FAIL | a member voluntarily left: [] |
| G36 | Relationships change through group experience | PASS | 2770 relationship changes over the group's life |
| G37 | Formation counterfactual passes | PASS | without cooperation the trio does not form a group: {'trio': [42, 87, 117], 'groups_formed': 0, 'trio_grouped': False} |
| G38 | Shelter-knowledge counterfactual passes | PASS | removing shelter knowledge changes selection: {'with_knowledge': 6353, 'without_knowledge': 7928, 'changed': True} |
| G39 | Admission counterfactual passes | PASS | removing the outsider's history flips admission: {'with_history': {'accept': True, 'reason': 'group_agrees', 'aggregate': 0.606}, 'without_history': {'accept': False, 'reason': 'in |
| G40 | Warning counterfactual passes | PASS | removing the warning leaves uncontacted members uninformed |
| G41 | Role counterfactual passes | PASS | changed risk flips the role decision: {'willing': {'accept': True, 'reason': '', 'citizen': 87}, 'frightened': {'accept': False, 'reason': 'too_dangerous', 'citizen': 87}, 'changed |
| G42 | Save/load formation/shelter passes | PASS | formation/shelter save-load identical; moments ['admission_decision', 'after_departure', 'after_formation', 'before_formation', 'during_shelter', 'mid_supply_run', 'role_assignment |
| G43 | Save/load group task passes | PASS | group task (role/supply) save-load identical |
| G44 | Save/load admission passes | PASS | admission decision save-load identical |
| G45 | LOD preserves group/member state | PASS | LOD promotion/demotion preserves group state: {'ok': True, 'citizen': 0, 'band_near': 'PHYSICAL', 'band_control': 'ROUTE_SIMULATED', 'group_same_while_physical': True, 'group_same_ |
| G46 | Godot demonstrates group behavior | NOT_RUN | artifacts/survivor_groups_v1/regression.json missing |
| G47 | DialogueGate remains PASS | NOT_RUN | artifacts/survivor_groups_v1/regression.json missing |
| G48 | CognitionGate remains PASS | NOT_RUN | artifacts/survivor_groups_v1/regression.json missing |
| G49 | WorkGate remains PASS | NOT_RUN | artifacts/survivor_groups_v1/regression.json missing |
| G50 | OutbreakGate remains PASS | NOT_RUN | artifacts/survivor_groups_v1/regression.json missing |
| G51 | MobilityGate remains PASS | NOT_RUN | artifacts/survivor_groups_v1/regression.json missing |
| G52 | Existing Godot gates remain PASS | NOT_RUN | artifacts/survivor_groups_v1/regression.json missing |
| G53 | Multi-city smoke | NOT_RUN | artifacts/survivor_groups_v1/city_smoke.json missing |
| G54 | No city-name special cases | PASS | no city-name special cases in the groups package: [] |
