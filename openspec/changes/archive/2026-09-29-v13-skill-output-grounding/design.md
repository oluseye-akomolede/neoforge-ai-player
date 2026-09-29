# v13 design — Skill output grounding

## Context

The mod already owns the ground truth for item transformation:

- `SmeltBehavior.SMELTING_RECIPES` — `raw_iron→iron_ingot`,
  `iron_ore→iron_ingot`, `nether_quartz_ore→quartz`, etc. (full table at
  `SmeltBehavior.java:29-103`).
- `MineBehavior.resolveDropItem` (private, `MineBehavior.java:483`) —
  `iron_ore→raw_iron`, `coal_ore→coal`, `diamond_ore→diamond`, with a generic
  `BuiltInRegistries` fallback for non-ore blocks.

A skill is a declarative tree over these leaves (`SkillNode`). Walking the tree
and composing these two tables deterministically tells us what the bot ends up
holding after a full run — the output item. The agent currently never asks;
instead it trusts L3's criterion, which hallucinates `minecraft:iron_ore_blocks`.

## Goals / Non-Goals

**Goals:** a mod-side, deterministic resolver for "what does this skill
produce"; an optional `produces` override; an HTTP surface; and an agent-side
plan-time rewrite of hallucinated inventory criteria to the resolved output.

**Non-Goals:** any LLM judgment in the path; reviving the ore→raw synonyms;
changing `criteria_eval` evaluation order; changing the planner architecture.

## Decisions

### 1. `produces` is an override, not a requirement

```json
{ "id": "mine_and_smelt", "produces": "minecraft:iron_ingot", "nodes": [ ... ] }
```

Absent by default. Two uses:

1. **Override** — a skill whose tree doesn't express its output cleanly
   (branch-heavy, or whose leaves are SEND_ITEM that put nothing in hand) can
   declare it directly.
2. **Escape hatch** — when inference can't decide (returns null), the author
   pins the answer.

The field is a plain string and may contain `${param}` templates, resolved
against the SKILL directive's `extra` map at query time (consistent with how
directive-leaf templates already resolve).

### 2. Inference threads a "held item" through the tree

`SkillOutputResolver.resolve(skillId, params)` walks the spec's root node,
carrying one `held` string:

| Node | Rule |
|---|---|
| `DIRECTIVE` MINE | `held = MineBehavior.resolveDrop(target)` |
| `DIRECTIVE` SMELT | `held = SmeltBehavior.resolveOutput(held ?? target)` — smelt *consumes the held raw*, not the ore target |
| `DIRECTIVE` FARM / CHANNEL / CONTAINER_SEARCH / WITHDRAW / CONTAINER_WITHDRAW | `held = target` (these acquire/put `target` in hand) |
| `DIRECTIVE` SEND_ITEM | `held = null` (the item leaves the bot) |
| any other directive (TELEPORT, STORE_ALL, WIDE_SEARCH, …) | `held` unchanged |
| `SEQUENCE` | fold children left-to-right |
| `LOOP` | resolve the body once (one iteration = the output) |
| `SKILL_REF` | `resolve(ref, params)` — nested skill's output |
| `IF` / `FALLBACK` | resolve each branch; agree-or-null (conservative) |

`null` output = "no grounding" — the caller treats it as such. Skills like
`goto_and_scan` (TELEPORT → WIDE_SEARCH) and `resupply_network` (CHANNEL →
SEND_ITEM) naturally resolve to null, which is correct: they leave nothing
deterministic in hand.

### 3. The resolver composes tables, never re-encodes them

`MineBehavior.resolveDrop` and `SmeltBehavior.resolveOutput` are promoted from
private to `public static` and reused verbatim. The resolver adds no new item
mapping — a future recipe change stays in one place.

### 4. Agent grounding is a plan-time rewrite, mirroring `_derive_build_criteria`

In `_step`, immediately after `_derive_build_criteria`, the orchestrator calls
`_ground_skill_criteria(subtask, directives)`:

- Find the SKILL directive (there is one only — L3 emits either a skill or a
  flat sequence, and `_collapse_to_skill` collapses whole sequences).
- `api.skill_output(skill_id, **params)` → `output`.
- For each clause of the criterion matching the inventory pattern, if the
  item is **not** a real mod item (`api.server_items(query=item)` returns the
  exact id), rewrite to `inventory has N <output>`. Real items are untouched.

This is deterministic and idempotent — it only fires on hallucinated ids, and
it keeps the anti-laundering guarantee intact (the rewrite is a registry
lookup, not an LLM call). The `_is_real_item` check fails **open** (assume
real → no rewrite) on any registry error, so a transient API blip can never
ground a criterion onto the wrong item.

## L2/L3 wiring

None. This is L1 (mod) + L2-orchestrator (agent) only. L3 keeps writing
criteria in its own vocabulary; the resolver is what makes those criteria
*correct*, not a prompt that asks L3 to be correct.

## Risks / Trade-offs

- **Inference ambiguity** → handled by agree-or-null on branches and the
  `produces` override for skills that don't thread cleanly. A wrong inference
  would rewrite a real-but-unhandled item; the `_is_real_item` guard means we
  only rewrite items that don't exist anyway, so the blast radius is nil.
- **`server_items` round-trip per clause** → only for the (rare) inventory
  clauses of a SKILL-covered subtask, and cached per item id; short queries are
  exact-id lookups, not broad scans.
- **`produces` on a self-expanded skill** → the spec validator already gates
  inline specs; `produces` is a passive string, so no new validation surface
  beyond "it parses".
