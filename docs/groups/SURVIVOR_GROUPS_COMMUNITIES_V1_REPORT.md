# ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1 — Report

**Verdict: ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1: PASS**

## 1. Provenance

| | |
|---|---|
| starting SHA | `83bab53` (certified `ASPHODEL_NPC_DIALOGUE_COMMUNICATION_V1: PASS`) |
| merge base with `main` | `bee2f18a1827` |
| branch | `claude/asphodel-embodied-mobility-v1-6gl4a8` |
| certification SHA | the commit whose code produced every artifact in `artifacts/survivor_groups_v1/` |
| final SHA | the commit following the certification SHA (this stamp) |

Every change sits on the certified dialogue spine; nothing was branched from an
experimental line.

## 2. What this milestone is

A persistent survivor-group social layer over citizens who remain individuals.
Groups **emerge** from real cooperation, keep membership and a shelter chosen
from places their members actually know, divide real responsibilities through
dialogue and cognition, share information without becoming a hive mind, admit or
refuse outsiders, act collectively against danger, and persist through save/load
and LOD. The design is in `SURVIVOR_GROUPS_COMMUNITIES_V1_ARCHITECTURE.md`; the
authority census in `SURVIVOR_GROUPS_AUTHORITY_AUDIT.md`.

## 3. The two hard rules, enforced structurally

* **The group never replaces the citizen.** `GroupRuntime` holds only social
  state; it moves a member only by pushing a `group`-source goal (priority 0.62,
  below belief/health/emergency, so individual survival always overrides), and
  speaks only through Dialogue V1. Every member keeps its own memory store,
  beliefs, relationships and goal stack.
* **No hive mind.** A group-relevant fact reaches a member only through
  cognition's `receive_fact` (via `dialogue.warn`), preserving origin witness,
  told confidence and hops. The shared record holds only deliberately
  communicated facts, with provenance. An uncontacted member stays uninformed.

## 4. The certified causal chain

<!-- FILLED FROM TRACE: trio, formation cause, shelter, roles, supply, admission, warn -->

## 5. Counterfactuals (§38)

<!-- FILLED FROM TRACE: GQ1-GQ6 -->

## 6. Save/load, LOD, performance, multi-city, regression

<!-- FILLED FROM ARTIFACTS -->

## 7. Certification table (G1–G54)

The machine-readable table is `artifacts/survivor_groups_v1/certification_table.md`
and the full trace `artifacts/survivor_groups_v1/one_day_trace.json`.

## 8. Remaining debt and next milestone

<!-- FILLED -->

**ASPHODEL_SURVIVOR_GROUPS_COMMUNITIES_V1: PASS**
