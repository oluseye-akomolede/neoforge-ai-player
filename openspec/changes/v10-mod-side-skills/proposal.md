# v10 — Mod-side skills (the missing rung between subtask and directive)

## Why

The directive model is "too discreet" in exactly one place: between a
subtask and the primitive that executes it. The ladder today is

```
L3 plan → subtask (1–3 flat directives) → L2 dispatch → L1 behavior
```

Every `Behavior` is already a rich, self-healing state machine for ONE
primitive (`MineBehavior`, `WideSearchBehavior`, `StoreAllBehavior`, …).
What does not exist is any composable, reusable unit that can hold a
*loop*, a *conditional*, or *state*. A command like

> search this wide area, find every chest, loot all contents, then store
> in your vault

needs `loop { scan → if(chest found) loot } → if(inv full) store` — and
the only thing that can express that today is L3 re-deriving it fresh as a
flat sequence of directives, badly, on a 14B local model. That is the gap
Voyager closed with its skill library, and it is the same gap here.

This change adds the missing rung: **a named, parameterized, declarative
skill that composes directives with control flow, executed deterministically
mod-side.** L3 stops decomposing the hard part and instead *picks and
parameterizes a skill* — a strictly smaller decision, and one we can then
fine-tune (v11).

## What

- **A declarative skill DSL** — `sequence` / `loop` / `if` / `fallback` /
  `skill-ref` nodes over existing directives, plus condition predicates over
  observable bot state. JSON, not Java: a skill is data the mod *validates*
  before it runs, never arbitrary code.
- **`DirectiveType.SKILL`** — a new directive kind. Its `target` is a skill
  id (from the registry) and `extra` carries parameters. `BotBrain` maps it
  to a new `SkillBehavior`, a meta-behavior that drives the skill's control
  flow and owns its progress. Because it is *a behavior*, BotBrain's
  "one directive → one behavior" contract is untouched.
- **`SkillRegistry`** — mod-side registry keyed by skill id, seeded with
  curated skills and extended by hive-mod through a seam.
- **An ever-expanding library** — curated seed skills ship now; a runtime
  path lets L3 *propose* a new skill spec, which the mod validates
  (schema + determinism + termination) and registers for reuse. That is the
  Voyager skill-library pattern, sandboxed to declarative data.
- **L2/L3 surface** — `SKILL` joins the known-kind vocabulary, and the
  planner prompt gains a SKILL REFERENCE (ids + param schemas) so L3 can
  select skills by name.

## Non-goals

- No Java code generation or arbitrary-code execution from L3 — skills are
  validated declarative data only (frozen modpack, determinism).
- No change to existing behaviors or their self-healing logic — skills
  *drive* them, they don't replace them.
- No squad-level parallelism in this change. `parallel` is a multi-bot
  concept that belongs in the coordinator, and it depends on squad binding
  (see Related). Per-bot skills handle `sequence`/`loop`/`if`/`fallback`.

## Related

**Squad binding (separate change, prerequisite for squad skills).** The
overnight "officer + 4 underlings teleported apart" failure is a missing
data structure, not a skill gap: no structure binds a specific
`Officer<N>` to specific `Drone<N>` underlings; officers and drones are
siblings competing on the same global task board, and "speaks for its
squad" exists only as persona text (`agent.py:3271-3279`). Squad skills
(`parallel` across a bound squad) and army composition both need that
binding first. Tracked separately; noted here because `parallel` will
land on top of it.

## Not verified at archive

Added 2026-09-29 as part of the spec backfill (row `qitem-20260929143218-f02afaec`).
This change carried no spec delta; it now does. The `skill-layer` domain already
existed and covers most of v10, so the new delta adds only what the spec did not
describe: the **deterministic, plan-time skill matcher** and the exec-time
collapse backstop, plus the registry seam and the bounded self-expansion.

What was checked against `main` (`dd88be0`):

- **Skill engine (mod side).** `SkillSpec`, `SkillNode`, `SkillValidator`,
  `SkillRegistry`, `SkillBehavior` are all present under
  `src/main/java/com/sigmastrain/aiplayermod/brain/` on main. This repo builds
  them into `aiplayermod-1.0.0.jar`. Whether the deployed server jar carries
  this exact build is a deployment fact, not proven here.
- **Deterministic plan-time matcher (agent side).** `agent/skill_matcher.py` is
  on main (first commit `5f766b6`), with `l3_planner._collapse_to_skill` and
  `l3_planner._SEED_SKILLS`. This is the agent image, live in prod
  (`agent:qwen3coder-dd88be0`). It closed the v10 task's open blocker #2.
- **Seed set has grown past v10's five.** `_SEED_SKILLS` on main now names
  `mine_and_smelt`, `goto_and_scan`, `search_and_loot`, `harvest_and_store`,
  `resupply_network`, `summon_vehicle`, `channel_gun`, and `fuse_*`. The original
  five are a subset; the delta does not pin the seed list.
- The headless `SkillEngineProof` runs (27/27, 35/35) and the 2026-08-13 live
  checks are recorded evidence, not reproducible from the tree.

Still open, and deliberately so: the `SkillEngineProof` run is not re-run here;
hive-mod registration (Phase 3) lives in the hive repo and is held; squad
binding is a separate change. Per the backfill rule those boxes stay as they are.
