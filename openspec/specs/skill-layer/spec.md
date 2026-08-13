# Skill Layer Specification

## Purpose

Defines the mod-side skill engine — a named, parameterized, declarative
composition of directives with control flow — and how L2/L3 select and drive
skills.

## Requirements

### Requirement: Skills are validated declarative data
A skill MUST be a JSON spec the mod validates before execution. It MUST NOT
be Java code or any arbitrary executable. Validation MUST reject any skill
that references an unknown directive kind, an unknown condition predicate, an
unbounded loop, an unknown or self `skill-ref`, or a `verify` block that does
not parse.

#### Scenario: Valid skill passes validation
- GIVEN a skill spec whose leaves are `MINE` and `SMELT` and whose loop has
  `max_iterations`
- WHEN it is submitted to the registry
- THEN it validates and is registered under its id

#### Scenario: Unbounded loop rejected
- GIVEN a skill spec with a `loop` node lacking `max_iterations`
- WHEN it is submitted
- THEN validation rejects it with a logged reason
- AND the skill is not registered

### Requirement: SKILL directive kind
The directive vocabulary MUST include a `SKILL` type. `target` is the skill
id; `extra` carries parameters (and, for self-expansion, an inline `spec`).

#### Scenario: Skill dispatched as one directive
- GIVEN `POST /bot/{name}/directive` with `{type:"SKILL", target:"mine_and_smelt",
  extra:{target:"iron_ore", count:16}}`
- WHEN the bot's brain picks it up
- THEN a single active directive runs MINE then SMELT to completion
- AND the agent observes one `COMPLETED`, not two

### Requirement: Control flow nodes
The engine MUST support `sequence` (ordered), `loop` (bounded by
`max_iterations`), `if`/`else` (over a condition), `fallback` (try each child
until one succeeds), and `skill-ref` (nest another registered skill). It MUST
NOT provide single-bot `parallel` — one bot ticks one directive at a time.

#### Scenario: Conditional branch taken
- GIVEN `loot_and_store` with `if {condition: inventory.space()==0, then:[STORE_ALL]}`
- WHEN the bot's inventory is full at the time the branch is evaluated
- THEN `STORE_ALL` runs
- AND when the inventory is not full, it is skipped

### Requirement: Conditions evaluate mod-side against bot state
Condition predicates MUST be evaluated synchronously against `BotPlayer`
state with no API round-trip. Supported predicates MUST include
`inventory.has`, `inventory.space`, `block.at(...).is`, `position.in_area`,
`xp.at_least`, `me.count`, `entity.near`, `health.below`.

#### Scenario: Condition reads live state
- GIVEN a skill whose `while` condition is `inventory.space() > 0`
- WHEN the bot's inventory fills during the loop body
- THEN the condition evaluates false on the next tick and the loop exits

### Requirement: Meta-behavior execution
`SKILL` MUST map to a `SkillBehavior` (a `Behavior`) so the brain's
single-active-directive contract is preserved. `SkillBehavior` MUST tick
child behaviors via a shared `BehaviorFactory`, report progress per node and
iteration in `ProgressReport`, and return SUCCESS/FAILED against the skill's
`verify` block when present.

#### Scenario: Progress narrates skill steps
- GIVEN `mine_and_smelt` running
- WHEN the MINE leaf completes and the SMELT leaf starts
- THEN `ProgressReport.events` records both transitions

### Requirement: Registry and ever-expanding library
The mod MUST expose a `SkillRegistry` keyed by id, seeded with curated
skills. The runtime self-expansion path MUST gate every L3-proposed inline
`spec` through the validator, register it only when `register` is set, and
enforce a configurable cap with LRU eviction.

#### Scenario: Curated skill available to the planner
- GIVEN the mod has initialized
- WHEN `GET /skills` is queried
- THEN the catalog lists `search_and_loot`, `mine_and_smelt`,
  `harvest_and_store`, `resupply_network`, and `goto_and_scan` with id,
  description, and parameter schema

#### Scenario: Proposed skill validated before reuse
- GIVEN L3 emits a `SKILL` directive with an inline `spec` referencing only
  known directives and a bounded loop
- WHEN the mod validates it
- THEN it runs
- AND (if `register` is set) it is registered for future reference

### Requirement: L2/L3 surface
`SKILL` MUST appear in `l2-mcp`'s known-kind vocabulary, and the L3 execution
prompt MUST carry a SKILL REFERENCE listing registered skills and their
parameter schemas so L3 selects skills by name.

#### Scenario: Planner selects a skill
- GIVEN L3 is asked to "search the area, loot chests, store the haul"
- WHEN the SKILL REFERENCE is present in the prompt
- THEN L3 emits a single `{kind:"SKILL", target:"search_and_loot", ...}`
  directive rather than a hand-decomposed flat sequence

### Requirement: Verification is deterministic, two-level
A skill's SUCCESS/FAILED MUST come from its own mod-side `verify` condition
(no LLM judgment), and the subtask that invoked the skill MUST still be
evaluated by the agent's deterministic `criteria_eval` strategies.

#### Scenario: Skill success feeds criteria evaluation
- GIVEN a subtask "loot the chest" that invoked `search_and_loot`
- WHEN the skill returns SUCCESS with inventory containing the loot
- THEN `criteria_eval` marks the subtask complete via strategy 1 or 3
- AND no L3 evaluation fallback is needed
