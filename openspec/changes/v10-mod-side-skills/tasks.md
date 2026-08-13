# v10 tasks — Mod-side skills

Sequenced; each lands with a headless proof before the next. Test with
aiplayermod only (per testing directive); hive skills arrive after.

## Phase 1 — the engine (curated seeds)

- [ ] `SkillSpec` + node/condition model (`brain/skill/`): `SkillSpec`,
      `SkillNode` (sequence/loop/if/fallback/skill-ref/directive),
      `SkillCondition`. Parsed from JSON with strict schema validation.
- [ ] `SkillValidator` — registration-time static checks: known directive
      kinds, known conditions, bounded loops (`max_iterations` required),
      reachable leaves, no self/unknown `skill-ref`, `verify` parses.
- [ ] `SkillRegistry` — `register(id, spec)`, `get(id)`, `catalog()` (id +
      description + param schema). Seed the five aiplayermod-only skills:
      `search_and_loot`, `mine_and_smelt`, `harvest_and_store`,
      `resupply_network`, `goto_and_scan`.
- [ ] `SkillCondition.evaluate(BotPlayer)` — implement the predicate set in
      Decision 4 against `BotPlayer` state, tick-safe.
- [ ] `DirectiveType.SKILL` (28th value) + `case SKILL` in `BotBrain`.
- [ ] Extract `BehaviorFactory.create(DirectiveType)` from
      `BotBrain.createBehavior` (lines 136–165); `BotBrain` and
      `SkillBehavior` both use it.
- [ ] `SkillBehavior implements Behavior` — interpreter stack; drives child
      `Behavior`s via the factory; applies sequence/loop/if/fallback/
      skill-ref; emits `ProgressReport` events per node/iteration; reports
      SUCCESS/FAILED against `verify`.
- [ ] **Proof — headless**: POST `/bot/{name}/directive` with
      `{type:"SKILL", target:"mine_and_smelt", extra:{target:"iron_ore",
      count:16}}`; observe the brain run MINE then SMELT as one directive,
      `COMPLETED`, with progress events narrating each node.

## Phase 2 — L2/L3 surface + self-expansion

- [ ] `l2-mcp` `KNOWN_KINDS` += `SKILL`; add `GET /skills` serving
      `SkillRegistry.catalog()`.
- [ ] `l3_planner._EXEC_SYSTEM_PROMPT`: add `SKILL` to the DIRECTIVE PARAM
      REFERENCE and a SKILL REFERENCE section (populated from `/skills`).
- [ ] Agent `_l3_orchestrator_dispatch`: confirm `kind: SKILL` pass-through
      (`target`=skill id, `extra`=params).
- [ ] **Proof — headless**: L3 given "search the area around spawn for
      chests, loot them, and store everything" emits a single
      `{kind:"SKILL", target:"search_and_loot", ...}` directive; the bot
      completes it end-to-end; `criteria_eval` marks the subtask complete
      without an L3 fallback.
- [ ] Runtime self-expansion: `SkillBehavior` accepts an inline
      `extra.spec`; `SkillValidator` gates it; `extra.register` (opt-in)
      registers under a generated id; registry cap + LRU eviction.
- [ ] **Proof — headless**: an L3-proposed inline spec that references only
      known directives validates and runs; a spec with an unknown directive
      kind or an unbounded loop is rejected with a logged reason and the
      directive fails fast.

## Phase 3 — hive contribution + squad note

- [ ] hive-mod registers hive skills through the `SkillRegistry` seam (after
      the engine is proven in aiplayermod).
- [ ] **Dependency, separate change**: squad binding (`Officer<N>` ↔
      `Drone<N>` list + squad-scoped task routing) — prerequisite before any
      `parallel`/squad skill and before army composition. Tracked under the
      v2-hive-rework roadmap, not here.
- [ ] Fix-or-avoid the `GATHER`/`PATROL` idle gap before any skill references
      them.
