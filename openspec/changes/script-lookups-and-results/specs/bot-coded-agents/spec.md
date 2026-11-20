# bot-coded-agents — lookups and results

## ADDED Requirements

### Requirement: A Script Can Look Up What The Tick Already Saw

A script MUST be able to ask questions of the data the agent already sent for
that tick, through a `look` object installed beside `api`, and a lookup MUST
NOT spend a host call, reach the network, or reach the mod.

#### Scenario: A lookup answers from the snapshot
- **GIVEN** a tick whose snapshot carries `nearby.mobs` including a sheep
- **WHEN** the script calls `look.nearest({ kind: 'mob', type: 'sheep' })`
- **THEN** it returns the nearest sheep with its distance
- **AND** `hostCalls` for the tick is unchanged by the call

#### Scenario: A lookup beyond the snapshot says so
- **GIVEN** a snapshot whose `nearby.blocks` covers radius 5
- **WHEN** the script asks for a block within 40 blocks
- **THEN** the lookup MUST NOT return an empty list that reads as "nothing there"
- **AND** it MUST report that the search did not extend that far

#### Scenario: A lookup reports the age of what it searched
- **GIVEN** a tick whose snapshot was refreshed up to 2000 ms before the tick
- **WHEN** the script asks the snapshot's age
- **THEN** the lookup MUST report that age in milliseconds
- **AND** the age MUST be derived from the envelope's `server_ms` with no extra
  host call

#### Scenario: A block's display name is not its kind
- **GIVEN** a snapshot whose `nearby.blocks` entry carries a display name such
  as "Oak Planks" and no registry id
- **WHEN** the script tries to match a block by its registry id or its state
  (for example a flower's colour)
- **THEN** the lookup MUST NOT claim to have answered it
- **AND** the documented answer MUST be that neither the display name nor a
  registry id carries block state, so the lookup is not attempted

#### Scenario: The nearest K are the nearest, not the first met
- **GIVEN** a bot at the origin, a chest at (2,0,2) and another at (-5,-5,-5),
  and K=1 for that block id
- **WHEN** the cache is refreshed
- **THEN** the kept entry MUST be (2,0,2), squared distance 8, and not
  (-5,-5,-5), squared distance 75
- **AND** an implementation that keeps whichever candidate the x,y,z scan met
  first MUST fail this scenario
- **AND** equal squared distances MUST be broken by scan order, stated in the
  requirement, so the same world always gives the same payload

#### Scenario: A lookup cannot act
- **GIVEN** the `look` object built for a tick
- **WHEN** its construction is inspected
- **THEN** it MUST hold no reference to `api`
- **AND** no lookup path MUST reach `accept()`, the function that spends the
  host-call budget

#### Scenario: A lookup result is a copy
- **GIVEN** a lookup that returned a list
- **WHEN** the script mutates that list
- **THEN** a second lookup in the same tick MUST be unaffected

#### Scenario: A dry tick sees the same lookups
- **GIVEN** one snapshot and one script
- **WHEN** the script is dry-ticked and then live-ticked
- **THEN** every lookup MUST return the same value in both

### Requirement: A Script's Result Reaches The Planner On Stated Triggers Only

A script's result MUST be the value passed to `api.result(v)` — NOT its
top-level return value, which ends the tick and reaches no result field
(lead rule, 2026-11-10; `worker.js:147`, `32b592a`). The stored result MUST be
delivered to the planner when the script reports completion, when it errors,
or when it states an escalation — and on no other tick. Delivery MUST NOT
depend on a player message arriving: a finished script's result MUST start a
planner call of its own, under the per-bot hourly cap and cooldown that bound
how often that can happen.

`api.result(v)` MUST cost one of the tick's 8 host calls. Its value MUST be
JSON-serialised and capped by the same 2 KiB marked cut as any other result.
When a script calls `api.result` more than once in a tick, the LAST value MUST
be the one kept. A call to `api.result` MUST NOT itself raise a delivery
trigger: it stores a value, and the trigger remains done/error/escalate.

#### Scenario: A completed goal delivers one result
- **GIVEN** a script that calls `api.result({ done: true, ... })`
- **WHEN** it is ticked repeatedly
- **THEN** exactly one result MUST be delivered
- **AND** the binding MUST be released

#### Scenario: The return value is not the result
- **GIVEN** a script whose top-level `return` carries a value and which never
  calls `api.result`
- **WHEN** its tick completes
- **THEN** no result MUST be delivered from the return value
- **AND** the tick MUST still end as the return-value rule says it does

#### Scenario: The last result call in a tick wins
- **GIVEN** a script that calls `api.result` twice in one tick with different
  values
- **WHEN** the result is delivered
- **THEN** the delivered value MUST be the second call's
- **AND** the first value MUST NOT appear

#### Scenario: Reporting costs a host call
- **GIVEN** a script that uses all 8 host calls, one of them `api.result`
- **WHEN** the tick runs
- **THEN** `api.result` MUST be counted among the 8 and MUST NOT be free

#### Scenario: Reporting does not trigger delivery by itself
- **GIVEN** a script that calls `api.result` and then keeps ticking, never
  reaching done, error or escalation
- **WHEN** several ticks pass
- **THEN** no planner call MUST be triggered by the `api.result` call

#### Scenario: An error delivers a result rather than only a log line
- **GIVEN** a script whose tick fails
- **WHEN** the agent processes the failure
- **THEN** a result MUST be delivered to the planner

#### Scenario: A loop cannot re-trigger the planner every tick
- **GIVEN** ten distinct scripts, each calling `api.result({ done: true })` on
  its first tick
- **WHEN** they are bound and run back to back within one hour, each released
  by its own completion and the next bound in its place
- **THEN** at most 4 results MUST reach the planner
- **AND** the results over the cap MUST be queued and the suppressed call
  logged with the cap named
- **AND** the fifth script MUST NOT start a planner call even though its
  binding and release are the same shape as the first

The shape is deliberate: a reported `done: true` releases the binding, so "ten ticks of
one script" can never reach the cap — only ten separate scripts can. That makes
this scenario the bind/release bypass test, and it is also what proves the
cooldown is **per bot** rather than per script: ten different scripts must
still be held off, so any implementation keyed on the script fails it.

#### Scenario: A result has a size cap
- **GIVEN** a script calling `api.result` with more than 2 KiB of JSON
- **WHEN** the result is delivered
- **THEN** it MUST be truncated with a marker
- **AND** it MUST NOT be dropped

#### Scenario: The planner reads a result without an extra call
- **GIVEN** a delivered result
- **WHEN** the planner next runs
- **THEN** the result MUST appear in that call's prompt
- **AND** no additional planner call MUST be made to carry it

#### Scenario: A result is only read by the goal that produced it (DEFERRED)
**Deferred (task 3.9):** the rule below is implemented and tested on the slot,
but it cannot fire in production yet, because a tick carries no goal id out of
the sandbox -- a held script returns SCRIPT_HELD before it ticks, so every
stored result is keyed to goal `""`. Nothing this change ships depends on the
discard; it starts working unchanged once a tick reports the goal it ran for.
- **GIVEN** a result keyed to bot and goal id
- **WHEN** the planner next runs for a different goal id
- **THEN** the result MUST NOT be rendered into that call's prompt
- **AND** it MUST be discarded with both goal ids logged

#### Scenario: A finished script's result reaches the planner with no player
- **GIVEN** a script that reaches `done` and releases its binding
- **WHEN** no player message arrives afterwards
- **THEN** the result MUST reach `call_plan` for its own goal without waiting
  for a player
- **AND** that call MUST be started by the result-triggered entry point, not by
  `_maybe_plan`

#### Scenario: A result arriving mid-call is queued, not injected
- **GIVEN** a planner call in flight for a goal
- **WHEN** a result for that goal arrives
- **THEN** the in-flight call MUST NOT be interrupted or given the result
- **AND** the result MUST be delivered on a later pass under the caps

#### Scenario: A stale result is discarded, not delivered (DEFERRED)
**Deferred (task 3.9):** not shipped by this change. No age rule is
implemented, and the requirement below is the target for the step that gives a
tick its goal id, not a promise about this ship.
- **GIVEN** a pending result older than 30 minutes
- **WHEN** a planning call for its goal next runs
- **THEN** the result MUST NOT be rendered
- **AND** the discard MUST be logged

#### Scenario: A result never enters a field the trainer reads
- **GIVEN** a delivered result rendered into a `call_plan` prompt
- **WHEN** the reply is recorded for the DPO trainer
- **THEN** the result MUST NOT appear in `response_raw`, `parsed`, or any other
  field the trainer reads
- **AND** the prompt path that renders it MUST be the only surface it touches

#### Scenario: Logs and actions are not results
- **GIVEN** a script that calls `api.log` and `api.do` and returns nothing
- **WHEN** the tick completes
- **THEN** no result MUST be delivered
