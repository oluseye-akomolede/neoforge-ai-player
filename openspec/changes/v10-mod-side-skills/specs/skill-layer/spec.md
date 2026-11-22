## MODIFIED Requirements

### Requirement: L2/L3 surface

`SKILL` MUST appear in `l2-mcp`'s known-kind vocabulary, and the L3 execution
prompt MUST carry a SKILL REFERENCE listing registered skills and their
parameter schemas so L3 can select a skill by name.

Skill selection MUST NOT depend on the model alone. A deterministic, plan-time
matcher MUST map an unmistakably skill-shaped task to a seed skill in code,
without an LLM call, so a skill-covered task becomes a single `SKILL` directive
and never reaches L3 decomposition. The matcher MUST be conservative: a rule
fires only on a recognised phrase shape with all of the skill's required
parameters extractable; an unresolvable item id or an unextractable parameter
MUST return no match so the task falls through to L3 rather than fabricating a
value.

As an exec-time backstop, if L3 did decompose a task into a raw directive
sequence that exactly matches a seed skill's signature, the agent MUST collapse
that sequence back into a single `SKILL` directive.

#### Scenario: Planner selects a skill
- GIVEN L3 is asked to "search the area, loot chests, store the haul"
- WHEN the SKILL REFERENCE is present in the prompt
- THEN L3 emits a single `{kind:"SKILL", target:"search_and_loot", ...}`
  directive rather than a hand-decomposed flat sequence

#### Scenario: A skill-covered task never reaches L3 decomposition
- GIVEN a task whose text matches a seed skill's rule with all params extractable
- WHEN the task is planned
- THEN the plan emits one `SKILL` directive for that skill
- AND the task is not decomposed by L3

#### Scenario: An ambiguous task falls through to L3
- GIVEN a task that is skill-shaped but whose item id does not resolve, or whose required parameter cannot be extracted
- WHEN the deterministic matcher evaluates it
- THEN the matcher returns no match
- AND the task is planned by L3 as usual

#### Scenario: A decomposed sequence collapses back to a skill
- GIVEN L3 hand-decomposed a task into a directive sequence identical to a seed skill's signature
- WHEN the agent processes the execution result
- THEN the sequence is collapsed into a single `SKILL` directive for that skill

## ADDED Requirements

### Requirement: Skills Register Through a Seam

The skill registry MUST be extensible so that another mod can register skills
through the same validation path as the built-in seeds. A registered skill MUST
pass the same static validation (known directive kinds, bounded loops, reachable
leaves, no self/unknown references, a parseable `verify`) as a seed skill.

#### Scenario: An external skill uses the seed path
- GIVEN a skill registered through the registry seam by another mod
- WHEN it is registered
- THEN it passes the same validator as the seed skills
- AND it appears in the catalog and is selectable like a seed skill

### Requirement: Runtime Self-Expansion Is Bounded

A `SKILL` directive MAY carry an inline skill spec. An inline spec MUST be
validated before it runs; a spec with an unknown directive kind or an unbounded
loop MUST fail fast rather than run. Inline registration MUST be opt-in and MUST
be bounded by a registry cap, evicting least-recently-used entries while leaving
the seed skills intact.

#### Scenario: A valid inline spec runs
- GIVEN a `SKILL` directive carrying an inline spec over known directives
- WHEN the directive is dispatched
- THEN the inline skill runs to completion

#### Scenario: An invalid inline spec fails fast
- GIVEN an inline spec with an unknown directive kind
- WHEN it is validated
- THEN it is rejected and fails fast
- AND no partial run is started

#### Scenario: The registry cap evicts without losing seeds
- GIVEN the registry is at its cap and a new inline skill is registered
- WHEN registration proceeds
- THEN least-recently-used generated entries are evicted
- AND every seed skill remains registered

### Requirement: A Bot Can Shear A Sheep

No mod action can currently shear. The bot's action set has 25 `BotAction`
implementations; the only item-on-something paths are `PlaceBlockAction`
(`UseOnContext`, a block) and `BuildBehavior:236` (also a block). Vanilla
shearing is `interactOn(entity, hand)`, and nothing in the mod calls it:
`UseItemAction` calls `gameMode.useItem`, which uses the held item **in air**,
not on an entity. `USE_ITEM`, `CONJURE` and `SHEAR` are all absent from
`BINDABLE_KINDS` (45 kinds), so a script cannot reach any of them either.

The smallest change that lets a script shear is therefore a new capability, not
a new argument: a mod action that right-clicks a held item on a named or
nearest entity of a given type, mirroring `CombatBehavior`'s target selection
rather than inventing a second one. Behind 5 blocks, as `CombatBehavior` uses
at `:509`.

This requirement states the capability and its refusal; it does not pick the
kind string. The implementation MUST add the kind to `BINDABLE_KINDS` so a
script can dispatch it, and MUST round-trip it through `bind_action` like any
other kind.

#### Scenario: A script shears a sheep it can see

- **GIVEN** a sheep within 5 blocks and shears in the bot's inventory
- **WHEN** a script dispatches the shear action against that sheep
- **THEN** the sheep is sheared and the wool is in the bot's inventory
- **AND** the action reports success only after the entity actually changed

#### Scenario: A shear with no sheep in range is refused, not silently idle

- **GIVEN** no sheep within 5 blocks
- **WHEN** a script dispatches the shear action
- **THEN** the action fails with a reason naming the missing target
- **AND** the script's tick does not report the action as having happened
