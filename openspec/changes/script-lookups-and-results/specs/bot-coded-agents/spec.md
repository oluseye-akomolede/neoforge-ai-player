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

#### Scenario: An ore kind also matches its deepslate variant
- **GIVEN** a snapshot whose `nearby.blocks` carries `id`
  `minecraft:deepslate_diamond_ore`, as trial 4.2 did (2026-11-22 05:02Z)
- **WHEN** the script calls `look.blocks('diamond_ore')`
- **THEN** it MUST match that entry, so a caller that asks for an ore is
  not silently told there is none
- **AND** the bare form MUST behave identically, so `look.blocks('minecraft:diamond_ore')`
  and `look.blocks('diamond ore')` give the same answer
- **AND** the reverse MUST hold: a `diamond_ore` entry MUST match a
  `deepslate_diamond_ore` needle, because the caller cannot know which
  variant the world happens to contain

#### Scenario: The deepslate variant is a fallback, not a replacement
- **GIVEN** a snapshot carrying BOTH `minecraft:diamond_ore` and
  `minecraft:deepslate_diamond_ore`
- **WHEN** the script calls `look.blocks('diamond_ore')`
- **THEN** BOTH MUST be returned, because the caller asked for the ore and
  the deeper variant is the same ore
- **AND** a kind with no deepslate counterpart MUST match exactly one
  entry, so the rule never widens a non-ore lookup

#### Scenario: Only ores get the variant rule
- **GIVEN** a snapshot whose `nearby.blocks` carries `id` `minecraft:deepslate`
  and another carrying `minecraft:cobbled_deepslate`
- **WHEN** the script calls `look.blocks('stone')`, `look.blocks('deepslate')`
- **THEN** the variant rule MUST NOT apply, because neither is an `_ore`,
  and the exact-match scenarios above MUST still hold

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

### Requirement: The Script Prompt Names The Fields Of Every Lookup Entry

`SCRIPT_SURFACE` MUST state the fields of every entry a lookup can return, not
only the fields of `look.blocks` entries. A script author reads that constant
and nothing else; a field it does not name is a field the author must guess,
and a wrong guess reads as an absent value rather than an error.

The three lookups return entries with **different identity fields**, and the
prompt MUST name each:

- a block entry carries `{id, block, position}`, where `id` is the namespaced
  registry id;
- a mob entry carries `{type, name, position, distance}`, where the identity
  field is `type`, not `id`;
- an inventory item carries `{slot, item, count, display_name, ...}`, where the
  identity field is `item`, not `id`.

`look.inventory()` returns the producer's stack objects verbatim; it does not
normalise them and MUST NOT be changed to do so, because a read-only accessor
that rewrote the shape would misreport what the bot carries. Naming the fields
in the prompt is what keeps that faithful copy usable.

#### Scenario: A script author is not left to guess an item's identity field

- **GIVEN** the rendered script prompt built from `SCRIPT_SURFACE`
- **WHEN** the prompt describes `look.inventory()`
- **THEN** it MUST name `item` as the field carrying the item id, because that
  is the field the producer actually sends and the one a script must read

#### Scenario: An author can tell the three entry shapes apart

- **GIVEN** the rendered script prompt
- **THEN** it MUST state that a block uses `id`, a mob uses `type`, and an
  inventory item uses `item`, so a script that reads `items[0].id` is a
  mistake the prompt could have prevented

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

### Requirement: A Result Carries Its Goal, And `done` Closes It

A delivered result MUST carry the id of the goal whose script produced it.
`_script_hold` is not that goal: the bind RELEASES the hold (2a.6), so by the
time a script reports, the hold is already None and cannot name its owner. The
surviving record is the active goal id, and the result MUST be stored with it
rather than with an empty string.

A result whose trigger is `done` MUST close its goal. It MUST NOT be handed to
the orchestrator as a new task, and the planner MUST NOT be asked to decompose
it: doing so produced a plan for the text "Script result (done): ..." and the
L3 planner declined with a clarify question, asking the player whether there
was a new task (observed on test 03:22Z). The player asked for one thing and
got a question back.

Reporting the outcome to the player is part of closing, not a separate plan.
Triggers other than `done` keep the existing delivery path.

#### Scenario: A done result carries the goal it was bound for
- **GIVEN** a script bound while running goal `chat:dashboard:hello#1`
- **WHEN** the script reports `done`
- **THEN** the stored result's goal id MUST be `chat:dashboard:hello#1`
- **AND** it MUST NOT be the empty string

#### Scenario: A done result closes its goal instead of planning again
- **GIVEN** a pending `done` result for the bot's current goal
- **WHEN** the result-delivery point runs
- **THEN** the goal MUST be closed and its outcome reported to the player
- **AND** no new orchestrator run MUST start from the result text
- **AND** the planner MUST NOT be asked whether there is a new task

#### Scenario: A result for a goal that is no longer current is still dropped
- **GIVEN** a pending result stored for goal A
- **WHEN** the bot's active goal is now B
- **THEN** the result MUST be discarded rather than closing or re-planning B

### Requirement: A Result Whose Script Said It Failed Must Not Close The Goal As Done

A result whose text reports failure MUST NOT close its goal as though the work
succeeded. A goal closed as `done` is terminal: the script binding is released
and nothing re-plans it, so closing on a failure strand the player's request
with a green chat line and no further attempt.

WHAT "REPORTS FAILURE" MEANS: the script's own boolean `done` field, not its
prose. A script reports success or failure by passing an object to
`api.result({done: true, ...})` / `api.result({done: false, reason: ...})`; the
tick carries that flag to the result slot as `ok`, and it alone selects the
trigger. Text-matching was the alternative and is unusable: a successful result
may legitimately contain the word "failed" ("first attempt failed, retried"),
and a failed one need not use it. A result that carries no verdict -- a plain
string, a non-object JSON value, a non-boolean `done`, or text cut mid-JSON by
the size cap -- MUST keep the `done` trigger it had before this requirement, so
every script written against the older contract keeps working.

DECISION: a failure result MUST hand the goal back to the planner, bounded by
the same per-bot caps as any other result-triggered call, rather than closing
as done-with-failure. The reasoning is that the two outcomes are not
symmetrical. A `done` result is the end of the work: re-planning it makes the
planner decompose text it already finished (the 03:22Z clarify question). A
failure is the *absence* of the outcome the player asked for, and the planner is
the only component that can choose a different approach -- retry the same target
from elsewhere, pick another ore, or tell the player it cannot be done. Closing
it as done silently converts "could not" into "did", which is the one reading
no script is entitled to make on the player's behalf.

The caps are what make this safe: an unbounded re-plan on a failure is the
trial 4.2 retry loop one layer up, so a failing script MUST NOT be able to drive
one planner call per tick. A failure result MUST consume the same per-bot
hourly cap and cooldown as a `done` result, and when both are exhausted the
goal MUST be left open for the player rather than closed as done.

#### Scenario: A failure result re-plans instead of closing
- **GIVEN** a pending result whose script reported `{done: false}`
- **WHEN** the result-delivery point runs and the caps allow a call
- **THEN** the planner MUST be asked what to do next
- **AND** the goal MUST NOT be closed as done
- **AND** the player MUST NOT be told the work succeeded

#### Scenario: A failure result is bounded like any other delivery
- **GIVEN** a pending `{done: false}` result and the per-bot cooldown already running
- **WHEN** the result-delivery point runs
- **THEN** no planner call MUST happen
- **AND** the goal MUST be left open rather than closed as done

#### Scenario: A successful result still closes
- **GIVEN** a pending result whose script reported `{done: true}`
- **WHEN** the result-delivery point runs
- **THEN** the goal MUST be closed and its outcome reported, as before

### Requirement: A Failed Tick's Result Must Not Be Silently Dropped

A tick the runner reports as `error` MUST NOT discard a result the script
stored in that same tick. The runner already carries it (`src/main.js` sets
`result` on both the ok and error responses, for a script that calls
`api.result` and then throws), but the agent treats every non-`ok` status as a
fallback and returns before holding the result -- so the one case the runner
went out of its way to preserve is the one the agent throws away.

A failed tick MUST still fall back to the planner, as it does today: the
script's actions for that tick are not trusted. Only the *result* MUST survive,
delivered with the failure classification above so it cannot close the goal as
done.

#### Scenario: A script that reports and then throws keeps its result
- **GIVEN** a script whose tick calls `api.result` and then throws
- **WHEN** the runner answers `status: error` with that result
- **THEN** the result MUST be held rather than dropped
- **AND** it MUST be treated as a failure result, not a done one
- **AND** the tick MUST still fall back to the planner

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

#### Scenario: Running build_envelope is not enough if its input is invented
- **GIVEN** a fixture generated by calling `build_envelope`
- **WHEN** the values fed into it are the ones the game sends
- **THEN** every position MUST be an `{x, y, z}` map, because
  `BotPlayer.formatPos` returns `Map<String,Double>` and
  `NearbyBlockIndex.positionOf` returns `Map<String,Integer>`
- **AND** a field the Java itself formats as a string, such as the entity
  `distance` (`String.format("%.1f", ...)`) MUST stay a string
- **AND** a fixture whose values were hand-written to a shape the game does not
  send MUST NOT pass merely because it went through `build_envelope`

Passing hand-written inputs through the producer's function launders them: the
file then records a wrong shape faithfully, and every lookup test reading it
agrees with the mistake. A regenerated fixture MUST equal the committed bytes,
so a hand-edit or a shape regression fails a test instead of passing quietly.

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

### Requirement: A Directive Missing A Required Field Is Refused, Never Dispatched

An action MUST be refused at binding when it lacks a field its kind requires,
with a reason the script log shows, on the same path as an unknown kind. It
MUST NOT reach the mod. A malformed directive MUST fail the directive or be
refused — never leave a bot wedged or spam the server thread.

The failure this requirement exists to stop: on 2026-11-22 a script dispatched
`MINE {"kind": "MINE", "x": 16, "y": 89, "z": -16}` with no `target`.
`_ALLOWED_ARGS` admits `x`, `y` and `z` for every kind (`agent/action_binding.py:53`),
so binding passed it. The mod's `BotBrain.applyDirective` installed `MineBehavior`
before calling `start()` (`BotBrain.java:169-170` before this change);
`MineBehavior.start()` reads `directive.getTarget()` (`MineBehavior.java:71`
before this change) and calls `resolveDrop(targetBlock)` on it (`:83`) before
`enterPhase()` (`:94`), which NPEs on null. Because the behavior was already
installed, every server tick hit `switch (phase)` at `:107` and NPEd again: 312 stack traces in ~16 s, the server
thread fell behind, and the bot stopped answering (`/brain` timed out at 10 s,
L1 polls at 5 s) for more than eight minutes. Other bots were unaffected.

`bind_action` MUST validate per-kind required fields. At minimum, `MINE`
requires a non-blank `target`, and its `x`/`y`/`z` are NOT coordinates — a lookup
returns positions, so a script mines a found block by passing the entry's
`block` (or `id`) as `target` with a `count`. The per-kind field table MUST
carry each kind's required fields and MUST be pinned by a test, in the pattern
of `test_bindable_set_matches_source`, so the table and the check cannot drift.

The script prompt MUST document the required fields of the common kinds,
derived from that same table rather than hand-written, so a planner is told
what to send instead of discovering it through a refusal.

Defence in depth in the mod, which MUST hold even when a caller bypasses the
agent's binding: `BotBrain.applyDirective` MUST NOT leave a half-started
behavior — if `start()` throws, the directive fails with a reason logged once
and the bot falls back to idle, rather than retrying a throwing `tick()` every
server tick. `MineBehavior.start()` MUST reject a null or blank target cleanly
before `resolveDrop`.

#### Scenario: MINE without a target is refused and the bot stays responsive
- GIVEN a script that dispatches `{"kind": "MINE", "x": 16, "y": 89, "z": -16}`
- WHEN the tick binds the action
- THEN the action is refused with a reason naming the missing `target`
- AND the script log shows that reason
- AND no directive reaches the mod
- AND the bot answers its next brain poll

#### Scenario: A throwing start() degrades the directive, not the server
- GIVEN a behavior whose `start()` throws
- WHEN `applyDirective` installs it
- THEN the directive is marked failed and its reason logged once
- AND the bot falls back to idle
- AND no further `tick()` on that behavior runs

#### Scenario: The prompt names the fields MINE requires
- GIVEN the rendered script prompt
- WHEN a planner reads the `MINE` entry
- THEN it says `target` (a non-blank block id) is required
- AND it says `target` is never a position, so `x`/`y`/`z` do not stand in for it
- AND the field names in the prompt come from the same table the binding checks

### Requirement: A Directive Needing Coordinates Is Refused Without Them

A kind whose coordinates are always meaningful MUST be refused at binding when
it omits `x`, `y` or `z`, with a reason the script log shows. It MUST NOT bind
and act on an implied origin.

The failure this requirement exists to stop: `Directive`'s `x`, `y` and `z` are
primitive doubles defaulting to `0.0`
(`src/main/java/com/sigmastrain/aiplayermod/brain/Directive.java:86`), and
`hasLocation` is set only by the builder's `location(...)` (`:98-100`).
`GOTO` and `TELEPORT` read `directive.getX()` unconditionally in `start()`
(`GotoBehavior.java:36-38`, `TeleportBehavior.java:22-24`), so a script sending
`{"kind": "GOTO"}` with no coordinates binds, and the bot walks to — or
teleports to — `0,0,0`, including into another dimension for `TELEPORT`. It does
not throw and is bounded by `MAX_TICKS`, so it is less severe than the MINE
wedge, but it is still an action the script never asked for.

The rule applies to a kind only where a missing coordinate is never valid. Every
bindable kind that reads directive coordinates was checked:

- `GOTO`, `TELEPORT` — read `getX()`/`getY()`/`getZ()` with no `hasLocation()`
  guard, in `start()`. Refused without coordinates.
- `BUILD` — `BuildBehavior.java:99-107` treats an all-zero location as "build
  here", building at the player's feet. A missing coordinate IS valid here, so
  `BUILD` is deliberately NOT in the rule; adding it would refuse a working call.
- `WIDE_SEARCH` (`WideSearchBehavior.java:92-97`), `AREA_LOOT`
  (`AreaLootBehavior.java:102-110`), `FUSE_BLOCK` (`FuseBlockBehavior.java:80`),
  `DRIVE_VEHICLE` (`DriveVehicleBehavior.java:42`), `STORE_ALL`
  (`StoreAllBehavior.java:63`), `CONTAINER_STORE`
  (`ContainerStoreBehavior.java:89`), `CONTAINER_WITHDRAW`
  (`ContainerWithdrawBehavior.java:68`) — each reads coordinates only under
  `hasLocation()` and otherwise falls back to the bot's position or `extra`.
  Left alone: their missing-coordinate behaviour is a deliberate fallback.
- Every other bindable kind does not read directive coordinates at all.

The coordinate rule MUST be a per-kind table, pinned by a test against this
enumeration, so a new kind that reads coordinates unguarded is a test failure
rather than a silent walk to origin. The script prompt MUST say which kinds need
`x`/`y`/`z`, from that same table.

A kind may require `target` and coordinates both; the two tables are separate
because they answer different questions.

#### Scenario: GOTO without coordinates is refused, not walked to origin
- GIVEN a script that dispatches `{"kind": "GOTO"}`
- WHEN the tick binds the action
- THEN it is refused with a reason naming `x`, `y` and `z`
- AND the script log shows that reason
- AND no directive reaches the mod
- AND no bot moves

#### Scenario: TELEPORT without coordinates is refused
- GIVEN a script that dispatches `{"kind": "TELEPORT", "extra": {"dimension": "minecraft:the_nether"}}`
- WHEN the tick binds the action
- THEN it is refused with a reason naming `x`, `y` and `z`
- AND the bot is not teleported

#### Scenario: BUILD with no coordinates still builds where the bot stands
- GIVEN a script that dispatches `{"kind": "BUILD", "target": "shelter"}`
- WHEN the tick binds the action
- THEN it binds
- AND the mod builds at the bot's position, as its all-zero fallback intends

#### Scenario: Coordinates that are present and real bind
- GIVEN a script that dispatches `{"kind": "GOTO", "x": 16, "y": 89, "z": -16}`
- WHEN the tick binds the action
- THEN it binds
- AND the bound action carries all three coordinates

#### Scenario: A zero coordinate is a coordinate
- GIVEN a script that dispatches `{"kind": "GOTO", "x": 0, "y": 64, "z": 0}`
- WHEN the tick binds the action
- THEN it binds
- AND the refusal is about an absent coordinate, never about one that equals zero

#### Scenario: The prompt says which kinds need coordinates
- GIVEN the rendered script prompt
- WHEN a planner reads it
- THEN it names `GOTO` and `TELEPORT` as needing `x`, `y` and `z`
- AND the kinds it names come from the same table the binding checks

### Requirement: A Script Can Read The Bot's Own Body

A script MUST be able to read the bot's own position, health and food level from
the same snapshot every other lookup answers from, without a host call.

The agent already sends these: `snapshot.build_state` (`agent/snapshot.py`)
places `health`, `food` and `position` at the top level of `state`, read from the
game's `/bot/{name}/status` (`BotPlayer.getStatus`, `BotPlayer.java:755-762`).
`position` is `{x, y, z}` as numbers, rounded to one decimal
(`formatPos`, `BotPlayer.java:1235-1240`); `health` and `food` are numbers.

The lookup MUST be `look.self()`, returning `{ok: true, position, health, food}`,
and MUST read `snapshot.state`, not any other path. A script that guesses a
shape the envelope does not carry MUST NOT be left to fail silently.

The document that lists the script surface MUST name `look.self()` with its
returned fields, in the same form as the existing `look` calls, so a planner
does not have to guess how to read the bot's own position.

Trial 4.3 (2026-11-22, bot Axiom, script `b6e61fbe`) is the failure this
requirement exists to stop: a script issued `GOTO x=-15 y=77 z=-28`, then
checked arrival with `snapshot.self.position` — a path that does not exist. The
bot reached `(-13.7, 77.4, -27.5)`, the check never passed, and the script
re-sent the identical GOTO every tick, each one COMPLETED.

#### Scenario: A script reads its own position from the real envelope
- **GIVEN** a tick whose snapshot is the real envelope, carrying
  `state.position` of `{x: -13.7, y: 77.4, z: -27.5}`, `state.health` and
  `state.food`
- **WHEN** the script calls `look.self()`
- **THEN** it MUST return `ok: true` with that `position` and those numbers
- **AND** it MUST NOT read `snapshot.self` or any path the envelope lacks

#### Scenario: Trial 4.3's arrival check passes when the bot has arrived
- **GIVEN** the envelope above, where the bot is within three blocks of
  `(-15, 77, -28)`
- **WHEN** a script checks `look.self().position` against that target within
  three blocks
- **THEN** the check MUST pass, so the script does not re-issue the GOTO

#### Scenario: The prompt names look.self and its fields
- **GIVEN** the rendered script prompt
- **WHEN** a planner reads it
- **THEN** it names `look.self()` and says it returns `position`, `health` and
  `food`

### Requirement: A Repeatedly Completed Identical Action Yields The Goal

A script that re-dispatches the SAME action that has already COMPLETED, N times
in a row, MUST yield the goal back to the planner and MUST log why, rather than
re-issuing it forever.

The signal is the identical action completing again, not a diff of world state.
Position, ages and mob health all move between ticks for reasons unrelated to
whether the action worked, so a state-equality test would either fire on a
slow action making progress or stay silent on a spin. An identical completed
action is the thing that is actually wrong: the script asked for the same work
it has already been told is done, which means its own completion check is not
firing (trial 4.3), and no amount of re-issuing resolves that.

N is `SCRIPT_REPEAT_MAX = 5`. The bound is a recovery from a script whose own
check is broken, not a retry policy: a legitimate action that needs more than
five identical completed re-issues to show progress is one whose completion
test is measuring something other than what it acts on, and the planner is
better placed to see that than the tick loop. The count is per identical
action: a different action resets it, so a script alternating between two
useful steps is not counted as a spin.

Yielding on a spin MUST reuse the all-refused yield path: unbind the script,
drop the step list, and re-submit the goal to the planner under
`SCRIPT_REPLAN_MAX`, so a spinning script cannot re-plan forever either. The
yield MUST log the action and the count.

Trial 4.3 is the case: the identical GOTO was re-sent ten or more times, each
COMPLETED, and nothing yielded until a human restarted the agent.

#### Scenario: Trial 4.3's repeated GOTO yields the goal, by count
- **GIVEN** a script that dispatches `GOTO x=-15 y=77 z=-28`
- **AND** that identical action COMPLETES on each tick with no different action
  between
- **WHEN** it has COMPLETED `SCRIPT_REPEAT_MAX` times in a row
- **THEN** the goal MUST be yielded to the planner
- **AND** the yield MUST log the action and the count
- **AND** the script MUST NOT dispatch it an `(N+1)`th time

#### Scenario: A different action resets the count
- **GIVEN** a script that dispatches the same GOTO four times, then a MINE
- **WHEN** it dispatches the GOTO again
- **THEN** that GOTO MUST be the first of its run, not the fifth
- **AND** it MUST NOT yield

#### Scenario: The bound does not fire before N
- **GIVEN** the same action COMPLETED `N-1` times in a row
- **WHEN** the next tick dispatches it again
- **THEN** it MUST NOT yield yet

#### Scenario: A yielding spin is still bounded by the re-plan count
- **GIVEN** a goal whose script spins, yields, and whose planner answers with
  the same spinning script
- **WHEN** it has been re-submitted `SCRIPT_REPLAN_MAX` times
- **THEN** it MUST stop re-planning, exactly as an all-refused yield does

### Requirement: A Script Can Read The Directive's Result

A script MUST be able to read what the directive it dispatched has reported,
including on the tick after it completes. `api.do` answers `{ok, seq}`
(`agent-script-runner/src/binding.js:324`), which says the action was ACCEPTED
and carries no progress, so a script that checks a completed action had no
route to its outcome at all. That is review F-1 on `465b61e`: the GOTO emitted
`arrived_at` correctly, and no script could see it.

The lookup is `look.task()`, read from `state.task`. `state.task` IS the mod's
whole `GET /bot/{name}/directive` body (`HttpApiServer.java:1338` answers it with
`BotBrain.toMap()`, `BotBrain.java:213-230`), so it carries the directive
(`Directive.toMap()`) AND `progress` (`ProgressReport.toMap()`), and
`progress.result` is where a behaviour's `putResult` fields land. Passing only
the inner `directive` map here is what made `result` unreadable, and the
envelope's `events` field is NOT the carrier: nothing populates it
(`snapshot.py:150` defaults it to `[]` and no caller passes it).

`look.task()` MUST return `{ok: true, id, type, status, result, phase,
failure_reason}`:
- `id`, `type`, `status` come from the directive, so a script can tell WHICH
  directive finished and whether it `COMPLETED` or `FAILED`. `status` is the
  field to trust for "is it done" -- `ok` from `do` never means that.
- `result` is the directive's `progress.result` map. It MUST be an empty object,
  not `undefined`, when the directive has reported nothing, so reading
  `result.arrived_at` is `undefined` rather than a throw.
- With no snapshot the answer is `{ok: false, reason: "no-snapshot"}`; with no
  directive it is `{ok: true, id: null, type: null, status: null, result: {},
  phase: null, failure_reason: null}` -- the SAME key set as the populated
  branch, with every value null or empty. These are different facts and MUST
  NOT be reported as each other (no-snapshot is `ok: false`).
- `look.task()` MUST NOT nest a `directive` key on either branch. The idle
  branch used to emit `{directive: null, ...}` while the populated branch
  emitted the directive's fields at the top level, so a script written against
  `task.directive` saw a running directive as `undefined` and an idle bot as
  an object -- the reading was inverted, and trial 4.2's retry hung on it
  (Forge waited for `task.directive === "GOTO"` forever while its GOTO ran).
  The kind is `task.type`; the completion is `task.status`.

`SCRIPT_SURFACE` MUST document `look.task()`, naming `result` and the fields a
completed action puts there. It MUST NOT tell a script to write an arrival check
against a field no lookup returns.

#### Scenario: A script sees where its GOTO arrived
- **GIVEN** a script that dispatched `GOTO` and on a later tick reads
  `look.task()`
- **WHEN** the directive has completed at a destination that was lifted
- **THEN** `status` MUST be `COMPLETED`
- **AND** `result.arrived_at` MUST be the `{x, y, z}` the bot actually reached
- **AND** `result.adjusted_from` MUST name the coordinates requested and
  `result.adjusted_to` the lifted ones

#### Scenario: A failed directive's reason reaches the script
- **GIVEN** a `GOTO` that failed with `target_enclosed`
- **WHEN** the script reads `look.task()`
- **THEN** `status` MUST be `FAILED`
- **AND** `failure_reason` MUST start with `target_enclosed`

#### Scenario: An idle bot reports no directive, not a missing snapshot
- **GIVEN** a snapshot whose `state.task` is `null`
- **WHEN** a script calls `look.task()`
- **THEN** it MUST return `ok: true` with `id`, `type`, `status`, `phase` and
  `failure_reason` all `null` and `result` an empty object -- the same key set
  a populated answer has, so one wait condition works against both

### Requirement: An Idle Script Yields Only A Goal It Actually Has, And Only When Nothing Is Running

A script that dispatches nothing, tick after tick, MUST NOT be able to hold a
goal forever -- trial 4.2's retry waited on a completion it could not read and
never dispatched again. The bound on that is `SCRIPT_IDLE_MAX` consecutive
ticks, after which the goal is yielded to the planner like a repeated action.

The bound MUST apply only where yielding means something, in two ways.

First, a bot with NO active goal has nothing to yield. A script bound from
`bindings.json` survives `_unbind_planner_script` by design and `_script_hold`
only clears when the goal ends, so a hand-written script on a goal-less bot is
reachable. Yielding there unbinds nothing, clears a live `_plan_steps`, and
resubmits an empty goal -- every `SCRIPT_IDLE_MAX` ticks, forever. With no
goal, the idle line is the correct output and nothing else MUST happen. Such a
tick MUST NOT even be COUNTED (`agent.py:3462`): climbing to the bound,
resetting and climbing again is the same unbounded repeat in a quieter form.
The log MUST NOT say a goal was unfinished unless one exists: the same
predicate decides both, so they cannot disagree.

The refusal MUST live in the yield itself, not only at the idle caller. The
idle path returns before the counter, so it never reaches the yield; the SPIN
caller does, and arrives goal-less for the same reasons. Guarding the callee
covers all three callers with one predicate, so they cannot disagree about
whether a goal exists.

Second, a tick where the bot's own directive is still running is NOT idle. A
script polling a 30-block `GOTO` dispatches nothing on every tick of the walk;
counting those would yield the goal mid-walk, replacing the wait the script
wants with a re-plan it does not. A directive counts as in progress when
`look.task()` reports it with status `ACTIVE` (`DirectiveStatus`,
`Directive.java:22`); a `COMPLETED` directive is a result to read, not work in
flight. Such a tick MUST NOT advance the idle run. The status is read from the
envelope that same tick already built, recorded as `ScriptTick.last_task`
(`script_tick.py:471`), not from a second request: a fresh `GET` would answer
for a different moment than the script was given.

Third, and overriding the second where they disagree, an `ACTIVE` directive
MUST NOT be able to hold a goal forever. The in-progress gate is what stops a
legitimate walk being torn down, but it is also a hole: a behaviour with no
terminal exit keeps its status `ACTIVE` indefinitely, so the idle bound can
never fire. `FOLLOW` is the demonstrated case -- it returns `RUNNING` for every
PRESENT target (`FollowBehavior.java:94`, `:99`, `:107`) and its only terminal
exit (`OFFLINE_GIVEUP_TICKS`, `:31`, gated at `:66`) requires the target
ABSENT -- and a script may issue it, since `action_binding.py:41` binds
`FOLLOW`. After `SCRIPT_DIRECTIVE_MAX_TICKS` consecutive `ACTIVE` ticks the
goal MUST be yielded for re-planning, with a log line naming the bound and
saying the directive produced no terminal result. The directive itself MUST
NOT be cancelled: the bound is on the wait, not the work, so a re-plan may
re-issue it and it then stops counting. The run MUST be reset whenever no
directive is in flight, so the bound is on CONSECUTIVE ticks and not a total.
It MUST also be reset by any tick that dispatches an action: a dispatched
action is new work, so a directive still `ACTIVE` afterwards is a new wait
rather than the continuation of the one being bounded -- otherwise a script
issuing a directive every tick would accrue to the bound while making progress.
The bound MUST be set per directive type, above that type's own longest
legitimate run, because behaviours do not share a unit: `GOTO` bounds itself
at `MAX_TICKS = 600` (`GotoBehavior.java:37`), while `COMBAT` defaults to 6000
ticks (`CombatBehavior.DEFAULT_DURATION`, `:68`, and more when a count is
given) and `FOLLOW` against a present player has no bound at all. A single
number large enough for `COMBAT` would never fire on `FOLLOW`; one small
enough for `FOLLOW` would cut a working `COMBAT` in half. A type absent from
the table MUST get the largest bound, so it is bounded loosely rather than
not at all.

#### Scenario: A goal-less bot does not yield
- **GIVEN** a bound script that dispatches nothing and no active goal
- **WHEN** `SCRIPT_IDLE_MAX` consecutive ticks pass
- **THEN** `_plan_steps` MUST be unchanged
- **AND** the script MUST stay bound
- **AND** the log MUST NOT claim a goal was unfinished

#### Scenario: A walk in progress is not idleness
- **GIVEN** a script that dispatches nothing while its directive reports `ACTIVE`
- **WHEN** many ticks pass, more than `SCRIPT_IDLE_MAX` but fewer than `SCRIPT_DIRECTIVE_MAX_TICKS`
- **THEN** the goal MUST NOT be yielded
- **AND** the idle run MUST NOT reach the bound while the directive runs

#### Scenario: A directive that never goes terminal yields the goal
- **GIVEN** a bound script with an active goal whose directive stays `ACTIVE`
- **WHEN** `SCRIPT_DIRECTIVE_MAX_TICKS` consecutive ticks pass
- **THEN** the goal MUST be yielded to the planner
- **AND** the directive MUST NOT be cancelled
- **AND** the log MUST name the bound (trial 4.2's wait-that-cannot-end, one layer down)

#### Scenario: Bounded behaviour never trips the directive bound
- **GIVEN** a `GOTO` that runs to its own `MAX_TICKS = 600` limit
- **WHEN** the script polls it to completion
- **THEN** `SCRIPT_DIRECTIVE_MAX_TICKS` MUST NOT have been reached
- **AND** the goal MUST NOT be yielded before the walk finishes

#### Scenario: A productive script does not accrue to the bound
- **GIVEN** a script that dispatches an action on every tick, each leaving a directive `ACTIVE`
- **WHEN** more than `SCRIPT_DIRECTIVE_MAX_TICKS` ticks pass in total
- **THEN** each dispatch MUST restart the ACTIVE run
- **AND** the goal MUST NOT be yielded

### Requirement: A Finished Directive Stays Readable Until The Next One

`look.task()` MUST keep answering for a directive that has finished
(`COMPLETED`, `FAILED` or `CANCELLED`), with its own `status` and `result`,
until a different directive is dispatched. A script waits for its own work to
finish; if the answer vanishes at the moment it becomes `COMPLETED`, the script
can never observe the transition it is polling for.

Trial 4.2 retried on TEST (2026-11-22 04:28Z) hung exactly this way: the script
dispatched `GOTO (-139, -35, -151)`, the mod completed it, and every subsequent
`look.task()` saw no directive, so the wait condition
`type === 'GOTO' && status === 'COMPLETED'` was never once true and the bot
idled until the agent was restarted.

The mod ALREADY retains the terminal directive: `BotBrain.toMap()` answers from
`lastDirective`/`lastProgress` once `activeDirective` is null
(`BotBrain.java:222-225`), which `agent.py:2718` relies on -- that branch is
the "Directive lost after connection errors" fallback, which is only safe
because the mod answers from `lastDirective`. The retention was destroyed by
the agent, not the mod: on seeing `COMPLETED` the L1 poller called
`api.cancel_directive`, and `BotBrain.cancelDirective` clears all three
retention fields (`BotBrain.java:62-64`). Those calls are REMOVED by this
change, so the line numbers moved with them: the `COMPLETED` branch's now-gone
cancel sat immediately before the `print(f"...Directive COMPLETED...")` at
`agent.py:2754`, and the `FAILED`/`CANCELLED` branch is at `agent.py:2765`.
The fix belongs where the damage was: a completion or failure that the agent
has FINISHED observing MUST NOT be followed by a cancel that wipes the record
the scripts read. Cancellation for a directive still running (stuck,
interrupted, user requested) is unaffected and MUST keep clearing, because
that directive has no terminal outcome to retain.

This requirement is about OBSERVABILITY, not about the directive's life. The
bot is idle either way; what changes is whether a script can see that its work
ended and where.

#### Scenario: A script sees its GOTO complete, then acts
- **GIVEN** a script waiting on `type === 'GOTO' && status === 'COMPLETED'`
- **WHEN** the GOTO's last tick returns SUCCESS
- **THEN** on at least the next tick `look.task()` MUST report that directive
  with `status` `COMPLETED`
- **AND** it MUST keep reporting it until a different directive is dispatched

#### Scenario: The retained record survives a full poll cycle
- **GIVEN** a directive the agent has observed complete
- **WHEN** the agent's poll loop finishes handling that completion
- **THEN** a read of `GET /bot/{name}/directive` MUST still carry the directive
  and its `progress.result`
- **AND** this MUST be tested against the real post-completion body, not only
  a hand-made fixture

#### Scenario: A cancelled running directive is still cleared
- **GIVEN** a directive cancelled while still ACTIVE (stuck, interrupted)
- **WHEN** the cancel completes
- **THEN** `look.task()` MUST NOT report that directive afterwards

### Requirement: GOTO Fails Rather Than Silently Relocating An Enclosed Target

A `GOTO` whose target block is enclosed MUST fail with the reason
`target_enclosed` rather than move the target to somewhere reachable. A GOTO
that arrives somewhere other than where it was sent, and reports COMPLETED, is
the failure: the caller cannot tell that the destination changed.

`GotoBehavior.start` (`GotoBehavior.java:57`) resolves the target through
`decideLift` (`:122`), which raises `targetY` one block at a time until the feet
and head are clear. Before this change the loop stopped only at the build
limit. For a target inside solid rock that walks the destination to the
surface: trial 4.2 (2026-11-22, test server) sent `GOTO (-123, -44, -152)`, an
enclosed `deepslate_diamond_ore`, and the bot was sent to `y = -8`, 36 blocks
above, through a different cave.

The search MUST be bounded to `GOTO_MAX_LIFT = 3` blocks above the target. A
few blocks covers a target buried under a floor or under a shallow ledge, which
is a real intent. Beyond that the caller meant that exact place, and moving it
36 blocks is not an adjustment but a different destination.

If no clear standing position exists within that bound, the directive MUST fail
with reason `target_enclosed`, naming the requested coordinates, rather than
walking, climbing or teleporting anywhere else. A silent substitution is the
defect this requirement exists to stop, so an adjustment is only acceptable
when it is bounded AND reported (below).

When the target IS lifted within the bound, the COMPLETED result MUST carry the
actual arrival position and an `adjusted_from` field naming the coordinates
that were asked for, so a script's own arrival check can be written against
what happened rather than what it requested. The result MUST ride the existing
`ProgressReport.putResult` channel. That channel has two consumers and they are
NOT the same: `agent.py:1410-1413` renders it into a `COMPLETED <type> {...}
result={...}` line for the PLANNER, and `look.task()` reads it back to the
SCRIPT (see "A Script Can Read The Directive's Result"). Emitting it is only
half of this requirement; a script that cannot read it is the other half, and
an arrival check written against an unreadable field is the re-issuing-forever
shape of trial 4.3.

A distance-teleport (`GotoBehavior.java:175`, beyond `TELEPORT_THRESHOLD`)
MUST use the same bounded, reported target. It reads `targetY`, which `start`
sets to the bounded lift result, so a far target can no longer be teleported to
a lifted surface position.

#### Scenario: Trial 4.2's enclosed target fails instead of climbing
- **GIVEN** a script that dispatches `GOTO x=-123 y=-44 z=-152`, whose target
  block is enclosed in stone
- **WHEN** no clear standing position exists within `GOTO_MAX_LIFT` blocks above
- **THEN** the directive MUST fail with reason `target_enclosed`
- **AND** the failure MUST name `(-123, -44, -152)`
- **AND** the bot MUST NOT move to or near `y = -8`

#### Scenario: A target under a shallow ledge is still lifted and reported
- **GIVEN** a `GOTO` whose target is covered by one block of stone
- **WHEN** the block above is clear
- **THEN** the directive MUST proceed to the lifted position
- **AND** on arrival the COMPLETED result MUST carry the actual position and an
  `adjusted_from` naming the original coordinates

#### Scenario: An unreachable enclosed target is not teleported to
- **GIVEN** an enclosed `GOTO` target further away than `TELEPORT_THRESHOLD`
- **WHEN** the lift would need to exceed `GOTO_MAX_LIFT`
- **THEN** the directive MUST fail rather than teleport to the lifted `targetY`

#### Scenario: The script surface warns against targeting a block itself
- **GIVEN** the rendered script prompt
- **WHEN** a planner reads it
- **THEN** it MUST say that to work on a block, GOTO a neighbouring open block
  or a position within reach, not the block itself
- **AND** it MUST NOT suggest that GOTO into a solid block is adjusted for the
  caller

### Requirement: A Stop Or Reset Cancels The Work That Would Outlive It

A stop and a reset MUST beat a re-plan that is already in flight, not only the
one running when the player typed. Both terminal transitions MUST cancel work
that was already on its way to re-binding the goal they ended, and a plan that
completes after one of them MUST NOT bind a script or set a plan for the
stopped goal.

The failure this requirement exists to stop: on 2026-11-22 at 07:01:40Z a
player sent `stop` while a script had yielded its goal and the agent was
re-planning it. The log order was the abort, then the nav stop, and only then
`[script] bound (planner, in memory) (0b62fe044f914f1b)` -- a script bound to a
goal the player had just stopped. The stopped goal then re-planned again and
bound a second one (`7df52ecc6ec16e7a`), and the loop continued until the
re-plan bound stopped it. Those scripts dispatched nothing; a mining or
walking script would have acted after the stop.

`_cancel_orchestrator` alone cannot close this. It signals the orchestrator run
that is executing NOW, and a re-plan started after the stop is a new run that
never observes an event set before it began. The cancellation therefore MUST
carry something that outlives a single run:

- A stop and a reset MUST each advance a generation counter.
- A re-plan or plan run MUST capture the generation it was started under and
  MUST refuse to bind a script or set a plan once that generation is stale.
- The yield re-plan MUST NOT start for a goal that was stopped or reset: the
  check MUST be on the path that re-submits the goal, so a running
  orchestrator that finishes after the stop cannot create it either.

The refusal MUST be logged, naming the goal and the fact that a stop or reset
superseded it, so a later log read can tell "nothing happened" from "something
was correctly stopped".

#### Scenario: A stop during an in-flight yield re-plan binds nothing
- **GIVEN** a planner-authored script that yielded its goal G
- **AND** a re-plan of G is running
- **WHEN** the player sends exactly `stop`
- **THEN** no script MUST bind afterwards for G
- **AND** no further re-plan of G MUST start
- **AND** the refusal MUST be logged with G's id

#### Scenario: A reset during an in-flight yield re-plan binds nothing
- **GIVEN** a planner-authored script that yielded its goal G
- **AND** a re-plan of G is running
- **WHEN** the bot is reset
- **THEN** no script MUST bind afterwards for G
- **AND** no further re-plan of G MUST start

#### Scenario: A new goal after a stop is unaffected
- **GIVEN** a stop superseded goal G while a re-plan of G was in flight
- **WHEN** the player gives a new goal H
- **THEN** H MUST be planned normally
- **AND** H MUST be able to bind a planner script

### Requirement: A Planner Script Is Unbound When Its Work Ends Without Succeeding

A planner-authored script MUST NOT outlive the work it was written for. Three
transitions end that work, and each MUST leave the bot in a state where the
script is no longer ticking:

1. The goal closes `done` -- already true, and before this change the only
   case that unbound (`_unbind_planner_script` at the `done` close,
   `agent.py:1259` at this change's base commit).
2. A failure result is handed back to the planner. The script reported that it
   could not do the job; the planner is choosing another approach, so the old
   script is not the thing to keep running. Held at `(cooldown)` forever, it
   pays a runner call every tick and can suppress its own `say` indefinitely.
3. The player sends a stop. A player's "stop" MUST stop a script that mines or
   walks, not only the planner that wrote it.
4. The bot is reset. A reset is terminal in the same way a stop is: it clears
   the plan, the goal and the script hold, so a bound planner script left alone
   would resume ticking with no goal and no plan to serve. `reset()` MUST treat
   a script exactly as a stop does. Without this it is the one terminal path
   that still leaves the planner's script running, which is the same defect
   this requirement closes for (2) and (3).

For (2), (3) and (4) the unbind MUST be `_unbind_planner_script` itself, not a
second mechanism that clears the same fields. That function already refuses to
touch a hand-written script (`_planner_script` is empty for one), so the
"deployment-bound scripts are not unbound" half is structural rather than a
condition someone must remember to check -- which is the property that makes
it safe to call from a path that does not know which kind it has.

A stop is NOT a hold. `_script_hold` is a pause owned by a goal and cleared
when that goal ends; a stop ends the work, so reusing the hold would leave a
halted script waiting for a release that never comes. The two MUST be separate
states, and the log MUST say which one happened.

#### Scenario: A failed hand-back unbinds the planner's script
- **GIVEN** a planner-authored script bound to goal G
- **AND** a tick whose result the planner receives as a failure
- **WHEN** the hand-back path starts the planner
- **THEN** the planner's script MUST be unbound
- **AND** the next tick MUST NOT call the runner for it
- **AND** the goal MUST remain open, so the planner answers it

#### Scenario: A failed hand-back leaves a hand-written script bound
- **GIVEN** a script bound from `bindings.json` for this bot
- **AND** a tick whose result is handed back to the planner as a failure
- **WHEN** the hand-back runs
- **THEN** the hand-written script MUST still be bound
- **AND** it MUST keep ticking

#### Scenario: A stop unbinds the planner's script
- **GIVEN** a planner-authored script bound and ticking
- **WHEN** the player sends exactly `stop`
- **THEN** the script MUST be unbound
- **AND** a subsequent tick MUST NOT call the runner
- **AND** the stop MUST still cancel the orchestrator and the directive, as it
  does today

#### Scenario: A stop halts a hand-written script for the stop period
- **GIVEN** a script bound from `bindings.json` for this bot
- **WHEN** the player sends exactly `stop`
- **THEN** the script MUST NOT dispatch a further action while the bot is
  stopped
- **AND** it MUST remain bound, so the player's deployment is not erased
- **AND** the next goal the bot accepts MUST let it dispatch again

#### Scenario: A reset unbinds the planner's script
- **GIVEN** a planner-authored script bound and ticking
- **WHEN** the bot is reset (`reset()`, the in-game "All tasks cleared")
- **THEN** the script MUST be unbound
- **AND** a subsequent tick MUST NOT call the runner
- **AND** the reset MUST still cancel the orchestrator and the directive, as it
  does today

#### Scenario: A reset halts a hand-written script and keeps it bound
- **GIVEN** a script bound from `bindings.json` for this bot
- **WHEN** the bot is reset
- **THEN** the script MUST NOT dispatch a further action while the bot is
  stopped
- **AND** it MUST remain bound, so the player's deployment is not erased
- **AND** the next goal the bot accepts MUST let it dispatch again

### Requirement: The Script Surface Is Offered Per Bot, Not Per Deployment

Scripts MUST be offered to a bot's planner only when that bot is BOTH enabled
for scripts AND has a runner configured. Today `render_planner_prompt`
substitutes `SCRIPT_SURFACE` unconditionally, so every bot in every deployment
is offered scripts -- including prod, which has no runner at all. There, all
five bots could write scripts that fail at tick for want of a runner and fall
back, spending planner calls to learn something the prompt should never have
offered.

The enabled set MUST come from deployment config, never from a default:

- `SCRIPT_BOTS` is a comma-separated list of bot names, matched case-
  insensitively and stripped of surrounding whitespace.
- Empty or unset `SCRIPT_BOTS` means NO bot is enabled. The default MUST be
  none: a deployment that has not opted in must not silently start offering
  scripts, which is how prod would reach the state this requirement exists to
  prevent.
- A bot is offered scripts only if it is named in `SCRIPT_BOTS` AND a runner
  (`SCRIPT_RUNNER_URL`) is configured. Naming a bot while the runner is unset
  MUST NOT offer scripts -- there is nothing for a script to run on.

A bot that is not offered the surface gets the planner prompt WITHOUT the
script section, and any `script` field it returns anyway MUST be ignored with
one log line naming the bot and saying why. Ignoring is not an error: the
prompt no longer asks for a script, so a stray field is noise, and failing the
plan for it would punish the model for a field the prompt stopped requesting.

`SCRIPT_SURFACE` is spliced into both the planner prompt and the L3 script
prompt, so the two MUST stay in step: whichever gate decides for one decides
for the other, and a change that gates one but not the other is a defect even
though each alone looks right.

At startup the agent MUST log, per bot, whether script mode is on or off and
why -- enabled-and-runner-configured, not in `SCRIPT_BOTS`, or no runner. This
is the only way a deployment can see from its logs that the switch took effect
without reading its own manifests back.

#### Scenario: An enabled bot with a runner is offered the surface
- **GIVEN** `SCRIPT_BOTS` names this bot
- **AND** `SCRIPT_RUNNER_URL` is set
- **WHEN** the planner prompt is rendered
- **THEN** it MUST contain the script surface
- **AND** the startup log MUST say script mode is on and why

#### Scenario: A bot not named is offered nothing
- **GIVEN** `SCRIPT_BOTS` names some other bot
- **WHEN** this bot's planner prompt is rendered
- **THEN** it MUST NOT contain the script surface
- **AND** a `script` field returned anyway MUST be ignored with one log line
- **AND** the goal MUST proceed on the plan's steps rather than failing

#### Scenario: No runner means no bot is offered scripts
- **GIVEN** `SCRIPT_BOTS` names this bot
- **AND** `SCRIPT_RUNNER_URL` is unset
- **WHEN** the planner prompt is rendered
- **THEN** it MUST NOT contain the script surface
- **AND** the startup log MUST say script mode is off because there is no runner

#### Scenario: An unset enabled set offers nothing
- **GIVEN** `SCRIPT_BOTS` is unset or empty
- **AND** a runner is configured
- **WHEN** any bot's planner prompt is rendered
- **THEN** it MUST NOT contain the script surface
- **AND** the startup log MUST say script mode is off and name the bot as not
  enabled

### Requirement: The Plan Prompt Must Not Invite A Script A Bot Is Not Offered

A bot that is not offered the script surface MUST NOT be taught how to ask for
one. Withholding the surface inside a call that still happens does not save the
call: the L3 plan prompt (`_PLAN_SYSTEM_PROMPT`) both explains "Choose between a
STEP LIST and a SCRIPT" and instructs the model to set `"wants_script": true`,
and `call_plan` fires `call_script` whenever that flag is set, with no gate of
its own. A bot outside `SCRIPT_BOTS` therefore reads an invitation, accepts it,
and spends a second planner call to be handed a script prompt with the entire
surface blanked -- the same wasted call this group of requirements exists to
remove, arriving one layer above where the previous gate looks.

The invitation and the capability MUST agree. When a bot is not offered the
surface, the script section of the plan prompt -- the "Choose between a STEP
LIST and a SCRIPT" teaching, the example surface, and the `wants_script` flag --
MUST be absent, so the model is never told to ask for what the deployment cannot
honour. `call_plan` MUST ALSO decline to fetch a script for a bot that is not
offered one, because a plan prompt is not a contract: a model that sets the flag
from habit or from a stale cached prompt MUST NOT cost a second call. Both
halves are required; either alone leaves the invitation and the capability able
to disagree.

Declining to fetch is not an error: the goal MUST proceed on the plan's steps,
exactly as a stray `script` field is ignored rather than failed.

#### Scenario: The plan prompt of a non-enabled bot invites no script
- **GIVEN** `SCRIPT_BOTS` names some other bot
- **WHEN** this bot's plan prompt is rendered
- **THEN** it MUST NOT teach `wants_script`
- **AND** it MUST NOT contain the script API surface
- **AND** the instruction to choose between a step list and a script MUST be
  absent

#### Scenario: A non-enabled bot that asks anyway costs no second call
- **GIVEN** `SCRIPT_BOTS` does not name this bot
- **AND** the plan reply carries `"wants_script": true`
- **WHEN** `call_plan` processes that reply
- **THEN** it MUST NOT make the second, script-writing call
- **AND** the goal MUST proceed on the plan's steps rather than failing
- **AND** it MUST log one line naming the bot and saying why no script was
  fetched

#### Scenario: An enabled bot with a runner keeps both halves
- **GIVEN** `SCRIPT_BOTS` names this bot
- **AND** `SCRIPT_RUNNER_URL` is set
- **WHEN** its plan prompt is rendered and the reply sets `wants_script`
- **THEN** the prompt MUST teach `wants_script` and contain the surface
- **AND** `call_plan` MUST make the second, script-writing call

### Requirement: A Rebuilt Prompt Must Recover Whether Scripts Were Offered

The eval harness rebuilds a recorded plan prompt to score a candidate against
it, and the section is per bot, so the bot's name does not say whether the
recorded call offered scripts. The recorded prompt is the only place that says.
Recovery MUST therefore distinguish three cases rather than two: the section is
present and matches this build (recovers verbatim); the section was never sent
(rebuilds to empty, which is what that call sent); and the prompt carries the
section heading but not this build's text, meaning another build offered scripts
with wording this one does not hold.

The third case MUST be reported unscorable, not rebuilt as empty. An empty
section sends the candidate a prompt the model never saw and compares it to one
that carried the surface -- a plausible substitution, which this harness treats
as a lie everywhere else it can distinguish the cases.

#### Scenario: A recorded offer is recovered verbatim
- **GIVEN** a recorded plan prompt carrying this build's script section
- **WHEN** the prompt is rebuilt
- **THEN** the rebuilt prompt MUST contain that section unchanged

#### Scenario: A recorded absence rebuilds to empty
- **GIVEN** a recorded plan prompt with no script section
- **WHEN** the prompt is rebuilt
- **THEN** the rebuilt prompt MUST contain no script section

#### Scenario: Another build's section makes the case unscorable
- **GIVEN** a recorded plan prompt carrying the script heading with text this
  build does not hold
- **WHEN** the prompt is rebuilt
- **THEN** the case MUST be reported unscorable rather than rebuilt as empty
- **AND** the reason MUST say the recorded prompt offered scripts

### Requirement: The Script Surface Needs The L3 Path, And `SCRIPT_BOTS` Opts A Bot Into It

The script surface is spliced into the L3 plan prompt only, so a bot whose chat
reaches the legacy `decompose` path can never write a script. Prod proves the
gap rather than the theory: its agent config has no `USE_L3_PLAN_LAYER`,
`config.py` defaults the flag to false, and prod therefore plans every chat
through `decompose` -- which makes every script requirement above unreachable
on prod no matter what `SCRIPT_BOTS` says.

`USE_L3_PLAN_LAYER` is asked once per deployment and read at three separate
call sites (chat gating, L3 acceptance, and the order lane), so flipping it
moves every bot in the deployment at once. That is the wrong granularity twice
over: prod cannot enable scripts for one bot without re-planning all five, and
`SCRIPT_BOTS` -- which already names the bots that may script -- has no say in
whether those bots can reach the path their scripts run on.

Routing MUST therefore be decided per bot by a single predicate used at all
three sites, never by the flag alone and never by three copies that can drift:

- The predicate is true when `USE_L3_PLAN_LAYER` is true, OR when this bot is
  named in `SCRIPT_BOTS`. Deployment-level enablement stays a fleet-wide switch;
  naming a bot adds that bot to the L3 path without moving any other bot.
- A bot not named in `SCRIPT_BOTS` MUST behave exactly as it does today for
  whichever value the flag holds. With the flag unset it plans through
  `decompose`; with the flag true it uses L3, unchanged.
- Naming a bot MUST NOT, by itself, offer it the script surface. Reachability
  and offering stay separate: a bot in `SCRIPT_BOTS` with no
  `SCRIPT_RUNNER_URL` reaches L3 and gets the plan prompt WITHOUT the script
  section. That composition is the point -- the path is necessary and not
  sufficient.

Because all three sites must agree, the predicate MUST be one function rather
than three conditions. A change that routes chat to L3 while the order lane
still refuses, or vice versa, leaves a bot that accepts a goal it cannot order,
which is a defect even though each site alone looks correct.

#### Scenario: Flag unset and the bot is listed
- **GIVEN** `USE_L3_PLAN_LAYER` is unset or false
- **AND** `SCRIPT_BOTS` names this bot
- **WHEN** the bot is handed an instruction
- **THEN** it MUST take the L3 path, and MUST NOT fall through to `decompose`
- **AND** this MUST hold at the chat gate, the acceptance check and the order
  lane alike

#### Scenario: Flag unset and the bot is not listed
- **GIVEN** `USE_L3_PLAN_LAYER` is unset or false
- **AND** `SCRIPT_BOTS` names some other bot, or is unset
- **WHEN** this bot is handed an instruction
- **THEN** it MUST plan through `decompose`, exactly as today
- **AND** the order lane MUST still report the L3 layer as disabled for it

#### Scenario: Flag true and the bot is not listed
- **GIVEN** `USE_L3_PLAN_LAYER` is true
- **AND** `SCRIPT_BOTS` does not name this bot
- **WHEN** this bot's plan prompt is rendered
- **THEN** the bot MUST still take the L3 path, because the deployment asked
  for it
- **AND** the prompt MUST NOT contain the script section, because a bot not in
  `SCRIPT_BOTS` is never offered scripts

#### Scenario: Listing a bot without a runner moves no other bot and offers no script
- **GIVEN** `USE_L3_PLAN_LAYER` is unset
- **AND** `SCRIPT_BOTS` names this bot
- **AND** `SCRIPT_RUNNER_URL` is unset
- **WHEN** the deployment starts
- **THEN** this bot MUST reach the L3 path
- **AND** its plan prompt MUST NOT contain the script section
- **AND** no bot outside `SCRIPT_BOTS` MUST change its routing

#### Scenario: One predicate, three sites
- **GIVEN** any combination of the flag and `SCRIPT_BOTS`
- **WHEN** the chat gate, the acceptance check and the order lane each decide
- **THEN** all three MUST return the same answer for the same bot
- **AND** a test that overrides only one site's condition MUST fail this
  scenario
