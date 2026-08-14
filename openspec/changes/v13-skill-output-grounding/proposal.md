# v13 — Ground skill criteria in the skill's real output

## Why

L3 writes a subtask's completion criterion in *input* vocabulary while the
skill it selects produces *output* vocabulary. `l3_emits_skill` passes only
because the harness checks `iron_ingot`, but the agent's own criteria loop
spent the whole run failing against `minecraft:iron_ore_blocks`:

```
[orchestrator] subtask 1 criteria: False (world_state) — holdings 0/8 of minecraft:iron_ore_blocks (0 carried)
```

`minecraft:iron_ore_blocks` is not a real 1.21 item (mining iron drops
`raw_iron`; smelting turns that into `iron_ingot`). `criteria_eval`'s
`_strategy_world_state` is correct to return **definitive False** for a
criterion naming a non-existent item — it short-circuits before the result-text
fallback, so the plan never self-satisfies and the orchestrator replans on a
subtask that actually succeeded. The skill *did* its job; the criterion was
written against the wrong item.

This is not an L3 prompt-tweak problem. The completion item of a skill-covered
subtask is a fact about the skill — what it ends up holding — and the mod is
the only component that knows it (its `MineBehavior` drop table and
`SmeltBehavior` smelting recipes are the ground truth). The agent should not
re-derive or re-judge it; it should ask.

## What

- **`produces` on the skill spec** — an optional override declaring the skill's
  terminal output item (its "held item" after a full run). For skills whose
  output is not inferable from the node tree (or not material at all), it is
  absent and no grounding happens.
- **Runtime inference** — when `produces` is absent, a mod-side resolver walks
  the skill's node tree, threading a "held item" through directive leaves using
  `MineBehavior.resolveDrop` (MINE) and `SmeltBehavior.resolveOutput` (SMELT).
  The inference composes the mod's own tables — it re-encodes nothing.
- **`GET /skills/resolve?skill=<id>&<param>=<v>`** — returns the resolved
  output item (or `null`), plus how it was resolved (`override` / `inference` /
  `none`).
- **Agent-side grounding** — at plan time, for a SKILL-covered subtask, the
  orchestrator queries the resolver and rewrites a hallucinated inventory
  criterion item (an id that is not a real mod item, checked against
  `api.server_items`) to the resolved output. Real items are left untouched, so
  compound criteria and genuinely-relevant extras (e.g. an `iron_pickaxe`
  requirement) survive.

## Non-goals

- No change to how `criteria_eval` evaluates (the three-strategy order, the
  definitive-False short-circuit, and the `ITEM_SYNONYMS` map are all
  unchanged).
- No ore→raw synonym entries re-added — v13 replaces that approach (which the
  `af17ebf` revert showed causes premature finalization at the raw-ore stage)
  rather than reviving it.
- No change to the two-path planner architecture or `USE_L3_PLAN_LAYER`.
- No LLM judgment anywhere in the grounding path — the resolver is
  deterministic mod-side code, and the agent's `_is_real_item` check is a
  registry lookup.

## Related

- **v10** introduced the skill layer; this completes the "the skill knows its
  output" half of skills-first, mirroring how `_derive_build_criteria` grounds
  BUILD criteria in actual build orders (finding D1).
- **af17ebf** reverted the ore→raw synonym mapping that caused premature
  finalization — the regression this change fixes at the root instead.
- [[project-l3-skill-emission-gap]] documents the `l3_emits_skill` win and the
  residual `iron_ore_blocks` criteria hallucination.

## Sequencing

Mod-side first (spec field → accessors → resolver → endpoint), then agent-side
(`api.skill_output` → `_ground_skill_criteria` hook). Verify with `gradle
compileJava` + `py_compile`, then rebuild/deploy and rerun `l3_emits_skill`.
