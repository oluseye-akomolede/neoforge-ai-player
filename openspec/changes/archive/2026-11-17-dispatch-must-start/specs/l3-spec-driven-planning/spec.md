## MODIFIED Requirements

### Requirement: Directive Normalization
Before dispatching a Phase 2 directive, L2 MUST normalize it (translation
only — no judgment):
- Uppercase `kind` and resolve known aliases: `EQUIP` → `EQUIP_ALL`
  (there is no per-item equip directive; the mod exposes bulk equip only)
- Canonicalize COMBAT targets through the mob-synonym table (e.g.
  `minecraft:pig_zombie` / `zombie_pigman` → `minecraft:zombified_piglin`,
  `wither_boss` → `wither`, `snowman` → `snow_golem`,
  `villager_golem` → `iron_golem`)
- A `kind` outside the known vocabulary MUST be surfaced to the retry
  prompt as `unknown_kind:<KIND>` so L3 can correct it, rather than
  failing silently
- A directive whose `kind` is still outside the known vocabulary after alias
  resolution MUST NOT be dispatched. The attempt fails with error
  `unknown_kind:<KIND>`. This holds whether the unknown kind was detected
  locally or flagged by l2-mcp; l2-mcp's fail-open rule applies only when
  l2-mcp is unreachable, never to a directive it has flagged.

#### Scenario: Invented EQUIP directive
- GIVEN L3 emits `{"kind": "EQUIP", "target": "armor_set"}`
- WHEN L2 normalizes the directive
- THEN it dispatches as `EQUIP_ALL` via the mod's bulk-equip endpoint
- AND the subtask does not burn an attempt on an unknown kind

#### Scenario: Renamed mob id
- GIVEN L3 emits `{"kind": "COMBAT", "target": "minecraft:pig_zombie"}`
- WHEN L2 normalizes the directive
- THEN the target is rewritten to `minecraft:zombified_piglin`

#### Scenario: Execution call labeling
- GIVEN a bot executing subtask N of M
- WHEN the L3 call is made
- THEN the gateway client label is `aibot-agent:{bot_name}:EXEC`
- AND the log line at INFO is `[{bot_name}] L3 EXEC call — subtask N/M`

#### Scenario: Invented kind is not dispatched (TEST 2026-11-13)
- GIVEN L3 emits `{"kind": "SEARCH_AND_STORE"}` and SEARCH_AND_STORE is not a
  known directive kind or alias
- WHEN the attempt is prepared for dispatch
- THEN no directive is sent to the mod
- AND the attempt fails with error `unknown_kind:SEARCH_AND_STORE`
- AND the next exec call for that subtask receives that error as `previous_error`

#### Scenario: l2-mcp flag is honoured
- GIVEN l2-mcp is reachable and returns the flag `unknown_kind:<KIND>` for a directive
- WHEN the attempt is prepared for dispatch
- THEN that directive is not dispatched and the attempt fails with `unknown_kind:<KIND>`

## ADDED Requirements

### Requirement: A Subtask Passes Only If Its Dispatch Started

An attempt that dispatched one or more directives, none of which started on the
mod, MUST fail with the dispatch reason. Criteria evaluation MUST NOT mark such an
attempt satisfied, whatever the criterion says about world state.

A directive has not started when dispatch returned no directive id, returned
`directive_never_started`, raised (`DISPATCH_ERROR`), or was refused before
dispatch (for example `unknown_kind:<KIND>`).

An attempt in which at least one directive started is evaluated against its
criteria as before. An attempt that dispatched zero directives is unchanged by
this requirement.

#### Scenario: Rejected dispatch cannot complete a plan (TEST 2026-11-13)
- GIVEN a subtask with criterion "holdings 0/0 of minecraft:items"
- AND the only directive of the attempt returns `directive_never_started`
- WHEN the orchestrator finishes the attempt
- THEN the subtask is not `complete`
- AND the attempt fails with error `directive_never_started`
- AND the plan cannot be finalized `complete` on that subtask

#### Scenario: One directive started
- GIVEN an attempt that dispatched two directives, the first never started and
  the second started and completed
- WHEN the orchestrator finishes the attempt
- THEN criteria are evaluated as before and may pass the subtask

#### Scenario: A raised dispatch is not a start
- GIVEN a subtask with criterion "holdings 0/0 of minecraft:items"
- AND the only directive of the attempt raises, so dispatch reports `DISPATCH_ERROR`
  (for example the bot's connection is refused)
- WHEN the orchestrator finishes the attempt
- THEN the subtask is not `complete`
- AND criteria are not evaluated
- AND the attempt fails with the dispatch reason

#### Scenario: A directive refused before dispatch is not a start
- GIVEN a subtask whose only directive is refused before dispatch because
  l2-mcp flagged its kind `unknown_kind:<KIND>`
- WHEN the orchestrator finishes the attempt
- THEN the subtask is not `complete`
- AND criteria are not evaluated
- AND the attempt fails with the refusal reason
