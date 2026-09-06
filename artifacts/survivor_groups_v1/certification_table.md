| gate | requirement | status | evidence |
|---|---|---|---|
| G1 | Stable group identity | PASS | group group:1, founders [42, 87, 117], created 7800.0 |
| G2 | Certified group forms during simulation | PASS | 1 GROUP_FORMED during the run at t=7800.0 |
| G3 | Formation caused by actual social history | PASS | formation cause: workplace:42-87; helped:42-87; trust:42-87; workplace:42-117; helped:42-117; trust:42-117 |
| G4 | No arbitrary pre-seeded group | PASS | no group existed before cooperation; formation event is timestamped mid-run |
| G5 | Individual cognition remains authoritative | PASS | each member has its own memory store and goal stack |
| G6 | Membership states persist | PASS | 5 membership transitions, states ['departed', 'member', 'provisional'] |
| G7 | Membership changes through valid social actions | PASS | every membership change carries a cause, e.g. {'t': 7800.0, 'cid': 42, 'old': None, 'new': 'member', 'cause': 'founder'} |
| G8 | No omniscient group knowledge | PASS | a group warning reached only co-present members [117], not the whole group |
| G9 | Group information preserves provenance | PASS | 2 shared-record facts, each with origin witness + source + confidence |
| G10 | Real shelter selected | PASS | shelter 6353 room 0 selected from 7 proposals |
| G11 | Shelter candidates come from member knowledge | PASS | every shelter candidate came from a member's own knowledge |
| G12 | Members physically regroup at shelter | PASS | 3 members physically regrouped at the shelter by 11.5: [42, 87, 117] |
| G13 | Shared goal grammar exists | PASS | 10 objective kinds in the grammar; used ['REACH_SHELTER', 'SEEK_SUPPLIES', 'WATCH_ENTRANCE'] |
| G14 | Group objective becomes individual goal | PASS | 3 members carried a group-source goal to the shelter, e.g. {'member': 42, 'goals': [{'id': 1, 'kind': 'do_activity', 'target': 'ent:6353', 'reason': 'regroup at group group:1 shelt |
| G15 | At least three meaningful roles | PASS | roles filled: ['coordinator', 'guard', 'scavenger'] |
| G16 | Role assignment considers member state | PASS | role proposals carry member-state components, e.g. {'influence': 0.788, 'loyalty': 0.596, 'risk_tolerance': 0.667, 'role_history': 0.3, 'free': True} |
| G17 | Role request uses dialogue/cognition | PASS | 2 role requests spoken through Dialogue V1 |
| G18 | Accepted role creates real action | PASS | guard 87 accepted -> objective WATCH_ENTRANCE done |
| G19 | Refused role does not create action | PASS | 0 refused roles created no active objective |
| G20 | Guard/watch behavior occurs physically | PASS | guard None physically holding the shelter post: True |
| G21 | Supply need detected | PASS | 1 supply-need detections |
| G22 | Supply run uses known source | PASS | supply run to a known source building 2318 |
| G23 | Supply runner physically travels and interacts | PASS | scavenger physically reached and used Smart Object so:2318:1 |
| G24 | Supply result changes group state | PASS | supplies returned: group food now 3.0 |
| G25 | Stranger can request admission | PASS | outsider 0 requested admission |
| G26 | Admission uses knowledge/relationships/capacity | PASS | admission graded on each member's own knowledge: {42: [0.427, 'known_helpful'], 87: [0.0, 'stranger'], 117: [0.0, 'stranger']} |
| G27 | Acceptance changes membership | PASS | acceptance changed membership: outsider in members = True |
| G28 | Refusal preserves non-membership | PASS | a refused outsider stays out: {'accept': False, 'reason': 'insufficient_trust', 'aggregate': 0.0} |
| G29 | Members can disagree | PASS | 3 group decisions, 2 with recorded dissent, e.g. [42, 87] |
| G30 | Bounded decision protocol resolves a disagreement | PASS | the bounded decision protocol resolved every proposal, e.g. shelter->7928 tally {'6353': 0.824, '7928': 0.827, '19087': 0.786} |
| G31 | Threat warning propagates through legitimate channels | PASS | group warning told [117] through the legitimate dialogue channel |
| G32 | Unwarned member remains uninformed | PASS | uncontacted members stayed uninformed: [0, 42] |
| G33 | Threat causes collective multi-member response | PASS | evacuation moved 4 members collectively |
| G34 | Individual emergency can override group role | PASS | a frightened member refuses a group role (survival overrides): {'accept': False, 'reason': 'too_dangerous', 'citizen': 87} |
| G35 | Member can voluntarily leave | PASS | a member voluntarily left: [87] |
| G36 | Relationships change through group experience | PASS | 2774 relationship changes over the group's life |
| G37 | Formation counterfactual passes | PASS | without cooperation the trio does not form a group: {'trio': [42, 87, 117], 'groups_formed': 0, 'trio_grouped': False} |
| G38 | Shelter-knowledge counterfactual passes | PASS | removing shelter knowledge changes selection: {'with_knowledge': 6353, 'without_knowledge': 7928, 'changed': True} |
| G39 | Admission counterfactual passes | PASS | removing the outsider's history flips admission: {'with_history': {'accept': True, 'reason': 'group_agrees', 'aggregate': 0.606}, 'without_history': {'accept': False, 'reason': 'in |
| G40 | Warning counterfactual passes | PASS | removing the warning leaves uncontacted members uninformed |
| G41 | Role counterfactual passes | PASS | changed risk flips the role decision: {'willing': {'accept': True, 'reason': '', 'citizen': 87}, 'frightened': {'accept': False, 'reason': 'too_dangerous', 'citizen': 87}, 'changed |
| G42 | Save/load formation/shelter passes | PASS | formation/shelter save-load identical; moments ['admission_decision', 'after_departure', 'after_formation', 'before_formation', 'during_shelter', 'mid_supply_run', 'role_assignment |
| G43 | Save/load group task passes | PASS | group task (role/supply) save-load identical |
| G44 | Save/load admission passes | PASS | admission decision save-load identical |
| G45 | LOD preserves group/member state | PASS | LOD promotion/demotion preserves group state: {'ok': True, 'citizen': 0, 'band_near': 'PHYSICAL', 'band_control': 'ROUTE_SIMULATED', 'group_same_while_physical': True, 'group_same_ |
| G46 | Godot demonstrates group behavior | PASS | {"status": "PASS", "pass": 12, "fail": 0, "info": 1, "exit": 0, "gate": "G46", "log": "logs/groups_gate.log", "wall_s": 59.9} |
| G47 | DialogueGate remains PASS | PASS | {"status": "PASS", "pass": 22, "fail": 0, "info": 5, "exit": 0, "gate": "G47", "log": "logs/dialogue_gate.log", "wall_s": 406.5} |
| G48 | CognitionGate remains PASS | PASS | {"status": "PASS", "pass": 30, "fail": 0, "info": 2, "exit": 0, "gate": "G48", "log": "logs/cognition_gate.log", "wall_s": 207.0} |
| G49 | WorkGate remains PASS | PASS | {"status": "PASS", "pass": 22, "fail": 0, "info": 0, "exit": 0, "gate": "G49", "log": "logs/work_gate.log", "wall_s": 244.4} |
| G50 | OutbreakGate remains PASS | PASS | {"status": "PASS", "pass": 18, "fail": 0, "info": 1, "exit": 0, "gate": "G50", "log": "logs/outbreak_gate.log", "wall_s": 816.3} |
| G51 | MobilityGate remains PASS | PASS | {"status": "PASS", "pass": 24, "fail": 0, "info": 1, "exit": 0, "gate": "G51", "log": "logs/mobility_gate.log", "wall_s": 1362.5} |
| G52 | Existing Godot gates remain PASS | PASS | {"status": "PASS", "pass": 85, "fail": 0, "info": 1, "exited_nonzero": 0, "scenes": ["tests/PhysicsGate.tscn", "tests/RegionGate.tscn", "tests/NavGate.tscn", "tests/ConvergenceGate |
| G53 | Multi-city smoke | PASS | {"houston": "PASS", "madisonville_tx": "PASS", "austin": "PASS", "san_antonio": "PASS", "boulder": "INFO"} |
| G54 | No city-name special cases | PASS | no city-name special cases in the groups package: [] |
