# v10 design — Mod-side skills

## Context

The L1 engine is `com.sigmastrain.aiplayermod.brain`:

- `DirectiveType.java` — 27 enum values (`MINE`…`MEDITATE`). Two of them,
  `GATHER` (line 5) and `PATROL` (line 23), have **no case** in
  `BotBrain.createBehavior` and silently idle — a separate latent bug, not
  in scope here but noted.
- `Directive.java` — `id, type, target, radius(256), count(-1), x/y/z,
  hasLocation, extra(Map<String,String>), status, failureReason`; builder.
- `BotBrain.java` — owns `pendingDirective` (a **single slot**, not a
  queue), `activeDirective`, `activeBehavior`. `createBehavior(DirectiveType)`
  at lines 136–165 is the enum→behavior switch. `tick()` at 73–115 pulls the
  pending directive, gates on self-preservation, ticks the behavior, and
  handles SUCCESS/FAILED/RUNNING.
- `Behavior.java` — `start(BotPlayer, Directive)`, `tick(BotPlayer) →
  BehaviorResult`, `describeState()`, `getProgress() → ProgressReport`,
  `stop()`.
- Ingress is `POST /bot/{name}/directive` → `HttpApiServer.handleBotAction`
  `case "directive"` (lines 1072–1103) → `DirectiveType.valueOf(type)` →
  `bot.getBrain().setDirective(...)`. A new enum value is therefore accepted
  by the API with **zero HTTP changes**.

The agent drives directives from `l3_planner.py` (`call_exec` emits
`{"directives":[{"kind":...}]}`), through `_l3_orchestrator_dispatch`
(`agent.py:852`) → `api.set_directive`.

## Goals / Non-Goals

**Goals:** a declarative, mod-side skill engine that composes existing
directives with control flow; a registry; a `SKILL` directive kind wired
through L2/L3; curated seed skills; a validated runtime self-expansion path.

**Non-Goals:** arbitrary code execution; squad `parallel` (needs squad
binding); persistence of in-flight skill state across restart (directives
don't survive restart today either — the agent's directive-loss detection
re-issues); changing existing behaviors.

## Decisions

### 1. Skills are declarative JSON, not Java

A skill is a spec the mod parses and validates:

```json
{
  "id": "search_and_loot",
  "description": "Sweep an area for containers, empty them, store the haul.",
  "params": {
    "target": "string", "center_x": "double", "center_z": "double",
    "radius": "int", "bot_index": "int", "bot_count": "int"
  },
  "nodes": [ /* control-flow tree, leaves are directives */ ],
  "verify": { "op": "inventory_count", "item": "${target}", "gte": 1 }
}
```

- **Why not Java**: L3 can't write Java, and we must not let it (frozen
  modpack, determinism, safety). Declarative data is fully sandboxable.
- **Why not Python (agent-side)**: that puts the loop back in LLM/agent
  territory, the exact failure mode this fixes. Mod-side execution is
  deterministic, tick-synchronous, and verifiable against `BotPlayer` state
  without a network hop.

### 2. `SkillBehavior` is a meta-behavior; the factory is extracted

`SkillBehavior` implements `Behavior`. It holds an interpreter stack
(current node, loop counters, current child `Behavior`). Each tick it either
advances control flow or ticks the current child; on child SUCCESS/FAILED it
applies the flow and pulls the next leaf. On an empty stack it returns
SUCCESS/FAILED.

To instantiate child behaviors, `BotBrain.createBehavior` is refactored into
a static `BehaviorFactory.create(DirectiveType)` used by both `BotBrain` and
`SkillBehavior`.

- **Why meta-behavior over a `pendingDirective` queue**: BotBrain's
  single-slot contract and the whole agent polling loop (`_poll_directive`,
  `api.set_directive`, `GET /bot/{name}/brain`) assume one directive at a
  time. A `SKILL` directive is *one* directive whose behavior is composite —
  no change to the slot, the polling, or the wire format. (The store-all
  change rejected meta-behaviors for a trivial loop; a full skill engine is
  precisely the case where the meta-behavior is the point.)
- **Persistence**: skill state lives in the `SkillBehavior` instance, exactly
  as behavior state does today — in-memory for the active directive, re-issued
  on restart by the agent.

### 3. Control flow is single-bot; `parallel` is a coordinator concern

`SkillBehavior` supports `sequence`, `loop` (with a hard `max_iterations`),
`if`/`else`, `fallback` (try each child until one succeeds), and `skill-ref`
(nest another registered skill). `parallel` is intentionally **not** a
mod-side node: one bot ticks one directive at a time. Parallelism is the
coordinator's job — it partitions and fans the same skill out to N bots with
`bot_index`/`bot_count` params, exactly the pattern `WIDE_SEARCH` already
uses.

### 4. Conditions evaluate against `BotPlayer` state, mod-side

The condition vocabulary is a small set of predicates the mod evaluates
synchronously against the bot:

```
inventory.has(item, >= n)   inventory.space()
block.at(x,y,z).is(id)      position.in_area(x1,z1,x2,z2)
xp.at_least(n)              me.count(item)      container.near(item)
entity.near(type, radius)   health.below(n)
```

These are the same facts the agent's `criteria_eval` uses, but read directly
from `BotPlayer` with no API round-trip. Unknown predicates fail validation
at registration time, not mid-run.

### 5. Registry + ever-expanding library

- `SkillRegistry.register(String id, SkillSpec)` — mod-side; curated seed
  skills register at mod init. Seed set (all aiplayermod-only so they test
  without hive-mod): `search_and_loot`, `mine_and_smelt`,
  `harvest_and_store`, `resupply_network`, `goto_and_scan`.
- hive-mod contributes hive skills through the same registry (the seam
  pattern already used for `ApiExtensions` / `AuxSlots`).
- **Runtime self-expansion**: L3 may emit a `SKILL` directive whose `extra`
  carries an inline `spec` (a proposed new skill). The mod validates it
  (schema, reachability, every directive kind + condition known, every loop
  bounded, no unknown refs) and — if the directive also carries
  `extra.register: "true"` — registers it under a generated id for reuse.
  Validation rejects anything non-deterministic or unbounded, so the library
  can grow from a 14B without the 14B being trusted to write code. Sequenced
  **after** the curated engine is proven (Phase 2 of this change).

### 6. Verification is two-level, both deterministic

- **Mod-side `verify`**: the skill's own terminal condition (e.g. "inventory
  has ≥1 of target"). `SkillBehavior` reports SUCCESS/FAILED against it.
- **Agent-side `criteria_eval`**: unchanged. The subtask that invoked the
  skill is still judged by its criterion; a skill SUCCESS/FAILED feeds
  strategy 3 (L1 result check).

## L2/L3 wiring

- `l2-mcp` `KNOWN_KINDS` (`renderers.py:95-104`, 35 kinds) gains `SKILL`.
- `l3_planner._EXEC_SYSTEM_PROMPT` (lines 182–352) gains a `SKILL` entry in
  the DIRECTIVE PARAM REFERENCE plus a new SKILL REFERENCE section listing
  registered skill ids, descriptions, and param schemas. `l2-mcp` serves the
  catalog (`GET /skills`) so the prompt section stays live.
- Agent `_l3_orchestrator_dispatch` passes `kind: SKILL` through as
  `type: SKILL` (target = skill id, extra = params) — no special-case needed
  beyond confirming the pass-through.

## Risks / Trade-offs

- **Meta-behavior complexity** → the interpreter must be tick-budgeted and
  must always terminate (every loop bounded by `max_iterations`; `fallback`
  bounded by child count). Mitigation: registration-time static validation
  of termination, and a per-tick op cap mirroring `WideSearchBehavior`'s
  scan budget.
- **Registry bloat from self-expansion** → cap the runtime-registered set
  (config, default e.g. 32), evict least-recently-used, and only persist
  skills that cleared validation. Unbounded growth is the Voyager failure
  mode we must not import.
- **Declarative DSL expressiveness ceiling** → some tasks genuinely won't
  fit a skill; that's fine. L3 falls back to emitting raw directives when no
  skill matches, exactly as today. Skills are additive, not a forced funnel.
- **Inline-spec trust** → L3-proposed skills are validated and can only
  reference already-validated directives/conditions; worst case is a valid
  but useless skill, never an unsafe one.
- **`GATHER`/`PATROL` idle gap** → pre-existing; a skill must not silently
  depend on them until that gap is closed. Flagged in tasks as a fix-or-avoid.
