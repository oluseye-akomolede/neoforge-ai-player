# bot-coded-agents — lookups and results

## ADDED Requirements

### Requirement: A Script Can Look Up What The Tick Already Saw

A script MUST be able to ask questions of the data the agent already sent for
that tick, through a `look` object installed beside `api`, and a lookup MUST
NOT spend a host call, reach the network, or reach the mod.

#### Scenario: A lookup answers from the snapshot
- **GIVEN** a tick whose snapshot carries `nearby.mobs` including a sheep
- **WHEN** the script calls `look.entities('sheep')`
- **THEN** it returns `{ ok: true, kind: 'entities', matches: [...] }` with each
  sheep's `distance`
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

#### Scenario: A namespaced kind matches a bare one
- **GIVEN** a snapshot whose `nearby.blocks` entry carries `id`
  `minecraft:iron_ore`, the form the game's own producer emits
- **WHEN** the script calls `look.blocks('iron_ore')` with the bare name
- **THEN** it MUST match that entry
- **AND** the answer MUST be the same one `look.blocks('minecraft:iron_ore')`
  gives for the same snapshot

#### Scenario: An unnamespaced entry matches a namespaced needle
- **GIVEN** a snapshot whose `nearby.blocks` entry carries a bare `id`
  `iron_ore`, a form the game does not emit today
- **WHEN** the script calls `look.blocks('minecraft:iron_ore')`
- **THEN** it MUST still match that entry
- **AND** the two forms MUST compare equal in both directions, so a script
  never has to know which form the game sends

#### Scenario: Only a leading namespace is stripped
- **GIVEN** a snapshot whose `nearby.blocks` carries `id` `a:minecraft:b`
- **WHEN** the script calls `look.blocks('minecraft:b')`
- **THEN** it MUST NOT match, because only one leading `minecraft:` prefix is
  removed from each side and nothing else is rewritten
- **AND** matching MUST remain exact after that one strip, so
  `look.blocks('iron')` MUST NOT match `minecraft:iron_ore`

### Requirement: A Script Can Read Its Own Inventory Through The Lookup

A script MUST be able to ask what the bot is carrying through
`look.inventory()`, a **read-only** lookup beside `look.blocks`,
`look.entities` and `look.age`. It MUST return the items in the snapshot's
`state.inventory` as a deep copy, MUST NOT spend a host call, MUST NOT let the
script mutate the snapshot by mutating what it receives, and MUST NOT offer any
way to change the inventory — a script that wants to move items calls the
existing `do` directives. The inventory the answer describes is the one the
tick's snapshot carries, so it is as old as the snapshot and is reported
alongside `look.age()`.

This exists because a script could otherwise not tell whether it held the tool
its work needs. The 2026-11-21 trial had a script written to shear sheep idle
with no shears in inventory, and `look` offered no way to check.

#### Scenario: The inventory is readable with no host call
- **GIVEN** a snapshot whose `state.inventory` carries 1 `minecraft:shears` and
  12 `minecraft:iron_ore`
- **WHEN** the script calls `look.inventory()`
- **THEN** it returns `{ ok: true, items: [...] }` naming both stacks
- **AND** `hostCalls` for the tick is unchanged by the call

The host-call half is measured, not asserted in prose: the binding reports
`host_calls` per tick, and `look-engine.test.mjs` evaluates 200 calls to every
`look` accessor — `inventory()` included — on a real sandbox and requires the
count to stay at 0. Wiring any accessor through `accept` reds it.

#### Scenario: A script cannot change the snapshot through it
- **GIVEN** a `look.inventory()` result
- **WHEN** the script mutates the returned list or any item in it
- **THEN** a second `look.inventory()` in the same tick MUST return the
  unmodified inventory
- **AND** the tick's own snapshot MUST be unchanged

#### Scenario: The inventory is read-only
- **GIVEN** the `look` object built for a tick
- **WHEN** its properties are enumerated
- **THEN** every one of them MUST be read-only, and `look.inventory` MUST be a
  function returning data rather than anything that accepts a change

#### Scenario: An empty inventory says so rather than failing
- **GIVEN** a snapshot whose `state.inventory` is empty
- **WHEN** the script calls `look.inventory()`
- **THEN** it MUST return `{ ok: true, items: [] }`
- **AND** it MUST NOT throw, so a script can test for a missing tool without a
  guard

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

#### Scenario: The cooldown is the binding rate limit
- **GIVEN** a bot with a script result delivered at some moment
- **WHEN** further script results are pending for that bot
- **THEN** no result-triggered planner call MUST start within 900 seconds of
  the last one
- **AND** at most one such call MUST start per 900 seconds per bot, so at most
  four in any rolling hour
- **AND** a result held back by the cooldown MUST stay pending, not be dropped

#### Scenario: The cooldown is per bot, not per script
- **GIVEN** two bots, each with a script result pending
- **WHEN** both results are delivered within the same 15 minutes
- **THEN** each bot MUST get its planner call, because one bot's cooldown MUST
  NOT hold back another bot's result

#### Scenario: The hourly cap is a backstop
The cap bounds the rate even if the cooldown is shortened or removed; on its
own, with the cooldown at 900 seconds, the cooldown already holds the rate to
four per hour.
- **GIVEN** the 15-minute cooldown is short enough that four result-triggered
  planner calls for one bot fall inside one rolling hour
- **WHEN** a fifth result is pending for that bot inside the same hour
- **THEN** the fifth call MUST NOT start
- **AND** the fifth result MUST stay pending, not be dropped
- **AND** the suppressed call MUST be logged with the cap named

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

### Requirement: The Planner Prompt Documents The Whole Script Surface

A feature the planner cannot see is a feature no planner-written script can
use. The planner prompt's script section (the text the LLM is given when it may
answer with a program instead of steps) MUST document every call a script can
make, in the shape the runner actually binds: the six `api.*` host calls, the
`look` global, and `api.result(v)`. It MUST state each one's signature, what it
returns, and when to reach for it. It MUST NOT describe a call that the runner
does not bind, because a prompt that offers one teaches the model to write
scripts that throw.

The section is paid for on every planner call, so it MUST stay short: a line
or two per call, not a copy of the runner's source.

There are two prompts that can produce a script: the legacy planner's script
section (`planner.PLANNER_PROMPT`) and the L3 script prompt
(`l3_planner._SCRIPT_SYSTEM_PROMPT`), which is the one the live path uses when
`USE_L3_PLAN_LAYER` is on. BOTH MUST carry the same facts. Fixing one and
leaving the other stale is the failure this requirement exists to prevent: the
L3 prompt told the model "this is the whole surface" and named only the six
original calls, so a bot on the live path could not see `look` or `api.result`
at all (seen live 2026-11-21). The two MUST share one text so they cannot drift
apart.

#### Scenario: The rendered prompt names every call, with its shape
- **GIVEN** a planner prompt rendered for a goal
- **WHEN** a script is offered as an answer
- **THEN** the prompt MUST name `look.blocks(kind, options)`,
  `look.entities(type, options)` and `look.age()` with the arguments and the
  return shape the runner binds (`{ ok, matches }`, or `{ ok: false, reason }`)
- **AND** it MUST name `api.result(v)` with what it returns (`{ ok: true }` or a
  rejection)
- **AND** a prompt that no longer names either call MUST fail this scenario

#### Scenario: The prompt states the snapshot's radius limits
- **GIVEN** the planner prompt's `look` description
- **WHEN** it states how far a script can see
- **THEN** it MUST give the real radii, blocks 5 and entities 16
- **AND** it MUST say that a query beyond them answers "not searched that far"
  rather than an empty list
- **AND** it MUST say the answers describe the tick's snapshot, not a live
  query

#### Scenario: The prompt states the result's journey
- **GIVEN** the planner prompt's `api.result` description
- **WHEN** it states what happens to a reported value
- **THEN** it MUST say the value reaches the planner when the script ends
  (`done`, an error, or `escalate`)
- **AND** it MUST say the last call in a tick wins
- **AND** it MUST say the value is cut at 2 KiB with a truncation marker
- **AND** it MUST say the script's top-level return value is discarded and is
  not the result

#### Scenario: The prompt counts only the calls that are host calls
- **GIVEN** the prompt's line about the per-tick host-call budget
- **WHEN** it says which calls spend it
- **THEN** `api.result` MUST be counted among the eight
- **AND** `look` MUST NOT be counted, because it answers from data already in
  hand

#### Scenario: The L3 script prompt carries the same surface
- **GIVEN** the L3 script prompt rendered for a goal, as `call_script` renders
  it
- **WHEN** the model is asked for a script on the live path
- **THEN** the rendered prompt MUST name `look.blocks(`, `look.entities(`,
  `look.age(` and `api.result(`
- **AND** it MUST carry the same facts as the planner prompt: blocks 5 and
  entities 16, a beyond-range query answering "not searched that far", the
  snapshot not being live, `look` free and `api.result` one of the eight host
  calls, delivery on done/error/escalate, the last call winning, the 2 KiB cut,
  and the top-level return value not being the result
- **AND** it MUST NOT tell the model to report by returning an array of
  actions, because the runner discards a script's return value
- **AND** dropping either prompt's copy of the surface, or letting the two
  diverge, MUST fail this scenario

#### Scenario: The prompt says when to use them
- **GIVEN** the planner prompt's `look` description
- **WHEN** it tells the planner when to choose a lookup
- **THEN** it MUST say to look before acting on a block the bot has to be near
- **AND** the `api.result` description MUST say to report what a goal found, or
  why it stopped

### Requirement: A Lookup Reads The World Where The Envelope Puts It

A lookup MUST read the tick's world data from the path the agent actually
sends, not from a shape assumed beside it. The tick request's `snapshot` is the
envelope built by `snapshot.build_envelope` (`agent/snapshot.py`), which is
`{"tick", "server_ms", "state", "events", "task"}`; the world a lookup answers
from is `snapshot.state.nearby`, with `blocks` and `mobs` beneath it. A lookup
that reads `snapshot.nearby` directly answers from `undefined` and MUST NOT
report that as an empty world.

An empty `matches` list MUST mean "I looked where the snapshot covers and there
was nothing" and MUST NOT be returned because the lookup read the wrong path.
The failure this requirement exists to stop was silent: every lookup returned
`{ok: true, matches: []}` on a snapshot that carried the block and the mob, so
two scripts idled while the trigger was in front of them, and nothing reported
an error.

Tests for this requirement MUST build their snapshot through the agent's own
envelope constructor, or assert against its output, so a fixture cannot drift
into a shape the game never sends. A hand-written fixture that happens to match
the lookup's assumption is not evidence about the live path.

The values **under** those keys are lists, and the agent MUST put them there as
lists. The game's HTTP handlers wrap every observation in a one-key object —
`{"blocks": [...]}` from `/bot/{name}/blocks`, `{"entities": [...]}` from
`/bot/{name}/entities`, `{"inventory": [...]}` from `/bot/{name}/inventory`
(`HttpApiServer.java:469`, `:504-505`) — and `snapshot.build_state`
(`agent/snapshot.py`) stores those responses unchanged. A lookup therefore
receives an object where it requires an array and MUST NOT answer that as an
empty world.

`build_state` MUST unwrap the game's response: when the value is a mapping it
MUST take the list under the expected key, when the value is already a list it
MUST keep it, and anything else MUST become an empty list **and** append a
reader error rather than pass silently. This is the same failure one level
down from the depth bug above, and it was silent in the same way: the legacy
planner already unwraps these responses in `prompts.py`, which is why the
planner saw the world while every script saw nothing.

#### Scenario: The world is found where the envelope puts it
- **GIVEN** a tick whose snapshot is the real envelope, carrying
  `state.nearby.blocks` with an `iron_ore` entry and `state.nearby.mobs` with a
  `sheep` entry
- **WHEN** the script calls `look.blocks('iron_ore')` and
  `look.entities('sheep')`
- **THEN** each MUST return `ok: true` with one match
- **AND** neither MUST return an empty list

#### Scenario: The fixture is the producer's own output
- **GIVEN** a test of the lookup
- **WHEN** its snapshot fixture is built
- **THEN** it MUST come from `snapshot.build_envelope`, or be asserted equal to
  what that function produces
- **AND** a fixture written by hand to the shape the lookup happens to read
  MUST NOT be accepted as covering the live path

The envelope's capture time is `server_ms`. A lookup that reports the
snapshot's age MUST read that field; reading a field the envelope does not
carry MUST NOT be reported as "the game sent no capture time", because it did.

#### Scenario: The snapshot's age comes from the envelope's own stamp
- **GIVEN** a snapshot carrying `server_ms` and no other timestamp field
- **WHEN** the script asks the snapshot's age
- **THEN** the answer MUST carry an `ageMs` number derived from `server_ms`
- **AND** it MUST NOT answer `null` with "the game sent no capture time"

#### Scenario: The wrong depth is detectable
- **GIVEN** an implementation that reads `snapshot.nearby` while the envelope
  nests the world at `snapshot.state.nearby`
- **WHEN** the lookup runs against the real envelope
- **THEN** the first scenario MUST fail
- **AND** the failure MUST name an empty match list rather than an error, so the
  test that catches it is the scenario above and not an exception

#### Scenario: The game's wrapped response becomes a list
- **GIVEN** an API whose `blocks()` returns
  `{"blocks": [{"id": "minecraft:iron_ore", "block": "Iron Ore", "position": …}]}`
  and whose `entities()` returns
  `{"entities": [{"type": "sheep", "name": "Sheep", "position": …}]}`
- **WHEN** `snapshot.build_state` builds the state
- **THEN** `state.nearby.blocks` MUST be a list holding that one block entry
- **AND** `state.nearby.mobs` MUST be a list holding that one sheep entry
- **AND** `look.blocks('minecraft:iron_ore')` MUST return one match from that
  snapshot

#### Scenario: A bare list is tolerated
- **GIVEN** an API whose `blocks()` returns a list directly rather than a
  wrapper
- **WHEN** `snapshot.build_state` builds the state
- **THEN** `state.nearby.blocks` MUST be that list, unwrapped and unchanged

#### Scenario: An unusable shape is a reader error, not silence
- **GIVEN** an API whose `blocks()` returns a string or a number
- **WHEN** `snapshot.build_state` builds the state
- **THEN** `state.nearby.blocks` MUST be an empty list
- **AND** the state's errors MUST name the `blocks` reader, so the tick reports
  a broken observation rather than a world with nothing in it

#### Scenario: Every reader sees the same unwrapped shape
- **GIVEN** a reader of `state.nearby` other than the lookup (the legacy
  planner's prompt, a diagnostic, a tool script)
- **WHEN** it reads `state.nearby.blocks` or `state.nearby.mobs`
- **THEN** the value it sees MUST be the same list the lookup reads
- **AND** no reader MUST be left handling a wrapper the agent no longer stores
