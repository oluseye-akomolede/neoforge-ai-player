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
