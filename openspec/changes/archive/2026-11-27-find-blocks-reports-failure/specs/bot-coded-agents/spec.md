## MODIFIED Requirements

### Requirement: A Script Declares The Searches It Needs And Reads Them As `look.queries.<name>`

A script MUST be able to search the world the way the planner's own
`find_blocks` / `find_entities` / `locate` do (owner A2, 2026-11-25 00:59Z), and
the lead settled HOW on 2026-11-25 04:17Z: **option 1 with a declared list.**

A script declares the searches it wants in a top-of-script statement named
`queries` (`const queries = [...]` or `queries = [...]`), using the same kinds
and parameters as the bot's existing query functions (`agent/api.py`). Before
each tick, the agent runs exactly those declared queries through the existing
mod reads and installs each result on the `look` object's `queries` map under
the declared `name`. Script code reads `look.queries.<name>` like any other
lookup: a plain value, no call, no host call. It is NOT `look.<name>` because
`look` already has accessors named `blocks`, `entities`, `age`, `inventory`,
`self` and `task`; a declaration named `blocks` would either overwrite one of
them or silently lose to it, depending on the order of an edit nobody would
notice. One reserved namespace has neither failure.

```js
queries = [
  {name: "ore",   kind: "blocks",   id: "minecraft:diamond_ore", radius: 32},
  {name: "cows",  kind: "entities", id: "minecraft:cow"},
  {name: "here",  kind: "block_at", x: 10, y: 64, z: 10},
]
var first = look.queries.ore.matches[0]
return first
  ? api.do("goto", {x: first.position.x, y: first.position.y, z: first.position.z})
  : api.done("none");
```

A `blocks` match carries `block` (registry id), `name` (display name) and
`position` (`{x, y, z}`) — the fields `BotPlayer.findBlocks` builds — and the
action that walks there is the existing `goto` kind taking `x`/`y`/`z`, not a
`goto_block` kind (there is none; an example that says otherwise is refused at
dispatch, found on the 2026-11-27 live probe).

The properties that make this the chosen design MUST hold:

- **Zero host calls.** A declared query is answered from data the agent fetched
  BEFORE the tick, so reading `look.queries.<name>` spends none of the 8 host calls and
  the sandbox stays hermetic (`src/engine.js` `#installSnapshot`). `look` keeps
  closing over the snapshot; the query results are additional read-only data on
  it, not a host function.
- **No stall.** The mod reads happen on the agent's tick boundary, before the
  script is evaluated, never inside it, so a slow `findBlocks` delays that tick's
  start (a bounded, visible cost) rather than blocking mid-script with no
  timeout.
- **No state across ticks.** The results live for exactly the tick they were
  fetched for, like the snapshot itself (§4.4: nothing a script declares survives).
- **A tick with no declared queries costs zero mod reads.** No `queries`
  assignment, or an empty list, MUST fetch nothing.

**How `queries` is read.** The script is JavaScript and runs as a function body
(`src/engine.js:evaluate`, contract §4.4); nothing it declares at top level
survives, and the sandbox has no JS parser exposed to the agent. The agent
therefore MUST read the declaration from the SOURCE TEXT before evaluating,
without executing any script code, by a strict parse that accepts only a literal
form: a declaration `[const|let|var] queries = <literal>` whose right side is an
array of object literals with only the allowed keys (`name`, `kind`, `id`,
`x`/`y`/`z`, `radius`, `max`). Anything dynamic (a function call, a property access, a spread, a
template literal, a variable reference) MUST be refused at bind time with a clear
reason, NOT silently ignored and NOT executed — a declaration that is executed to
be read is arbitrary code running before the tick's budget.

Two rules the parse MUST also enforce, because dropping them was measured to
pass attackers (prototype in tasks 7.1): **the declaration MUST appear at most
once** (a second `queries =` later in the script would diverge from the one that
was validated), and **nothing MAY follow the closing `]` on its statement except a
terminator or comment** (`queries = [...literal...] + evil()` otherwise parses as
the array while `+ evil()` still executes when the script runs — validation that
gives false assurance). A `__proto__` or other unknown key is refused by the key
allow-list, not by trusting the JSON parse.

The terminator rule is about the STATEMENT ENDING, not about the character that
ends it: a `;` starts a NEW statement, so `queries = [...]; evil()` is refused on
the same grounds as `+ evil()` — accepted by a literal reading of "on its
statement", which is why the intent is written out here (review finding F-1,
measured: the first implementation accepted exactly that form, and the runner
service executes the script). Concretely: after the closing `]`, on the
terminator's line, only spaces, tabs, `\r`, one or more `;` and comments may
appear; anything else is refused. The first line break ends the statement and
code may follow it. The `;` is optional — `] // why` then code on the next
line is as legal as `]; // why` then code (F-2, then the residual the re-check
found: pinning only the `];` shapes let the no-semicolon forms be refused while
this sentence claimed they were allowed). A comment MUST NOT span more than one
line: `]; /* a` / ` */ evil()` is refused, not treated as a line break —
measured, allowing it accepted a form where `evil()` runs.

**The declaration is validated when a script is BOUND, before it has run a tick.**
The same parser runs at `tick()` time to read the queries; a script whose
declaration is invalid at bind time MUST be refused there with a reason naming
the declaration (the path a hand-written binding already takes, `PlannerScriptBindTest`),
so a broken declaration is visible in the bind log rather than only in a tick's
detail line. A tick whose declaration becomes invalid mid-run (a script edited
under a live binding) is refused at the tick, never executed with a partial list.

**Kinds and parameters** (from `agent/api.py`, which wraps the mod):

| kind | declared keys | mod call | caller-side clamp |
|---|---|---|---|
| `blocks` | `id`, `radius`, `max` | `api.find_blocks(bot, id, radius, max)` (`agent/api.py` `find_blocks`) | radius <= 32, max <= 16 |
| `entities` | `id`, `radius` | `api.find_entities(bot, id, radius)` (`agent/api.py` `find_entities`) | radius <= 32 |
| `block_at` | `x`, `y`, `z` | `api.block_at(bot, x, y, z)` (`agent/api.py` `block_at`) | one cell |
| `locate` | `id` | `api.locate(bot, id)` (`agent/api.py` `locate`) | fixed chunk_radius 100 |

The clamps above are a PROPOSAL; the numbers that decide their safety are
measured by tasks 7.6 (scan cost) and the lead accepts or overrules them. A
declared value above a clamp MUST be narrowed to it and the clamp MUST be
reported in that query's result, so the script can tell a search was narrower
than it asked.

**A failed or timed-out query is not an empty result.** Each result MUST be
`{ ok: false, reason, message }` on failure or timeout, never `{ ok: true,
matches: [] }`, for the reason `look` already draws (`src/look.js:103-110`):
"searched, found none" and "could not search" are different facts. One failed
query MUST NOT fail the tick or drop the other queries — each is independent and
each failure is reported in its own `look.queries.<name>`.

**What a successful result looks like.** The mod answers `find_blocks` as
`{blocks: [...]}` and `find_entities` as `{entities: [...]}`
(`HttpApiServer.java`, `find_blocks` / `find_entities` cases), and the runner
binds the agent's `queries` map verbatim. So the agent MUST rename those lists
to `matches` before installing them: the examples above read
`look.queries.ore.matches`, and a script written exactly as this spec shows MUST
work. A `blocks` or `entities` result is `{ ok: true, kind, matches: [...] }`.
`block_at` and `locate` are single answers, not lists: their result keeps the
mod's own fields (`block_at`: the block map; `locate`: its `found`/position
fields) and adds `ok` and `kind`. A unit test that stubs `find_blocks` to return
`matches` directly does NOT satisfy this requirement — it hides the real
response shape the agent has to normalise.

**A duplicate name is refused.** Two declarations with the same `name` would
silently make one overwrite the other, so it MUST be refused at bind time with a
reason naming the name. Duplicates of the same `(kind, id)` under DIFFERENT names
are allowed and collapse to one mod call, because they are one search.

**Read-only.** The query path MUST NOT reach any mod route that moves, mines,
places, attacks or sets a directive. It calls only the four reads above.

The mod clamps nothing: `HttpApiServer.java:1117-1134` takes whatever `radius` and
`max` it is sent, and `findBlocks` iterates the full cube
(`BotPlayer.java:1286-1309`). So the clamp lives in the agent, before the call.

#### Scenario: A declared query answers from data fetched before the tick
- **GIVEN** a script declaring `queries = [{name:"ore", kind:"blocks", id:"minecraft:diamond_ore", radius:32}]`
- **WHEN** the tick runs
- **THEN** `look.queries.ore` MUST be the result of one `find_blocks` call made BEFORE
  the script was evaluated
- **AND** reading `look.queries.ore` MUST spend no host call
- **AND** with the real `find_blocks` answer `{blocks: [...]}`, the script MUST
  read `{ok: true, kind: "blocks", matches: [...]}` (the agent renamed the list)

#### Scenario: A script reads matches exactly as this spec's example does
- **GIVEN** a declared `blocks` query and a real `find_blocks` answer carrying two blocks
- **WHEN** the tick installs the result
- **THEN** `look.queries.<name>.matches` MUST be those two blocks, `ok` MUST be true
- **AND** `look.queries.<name>.blocks` MUST be absent
- **AND** the test MUST feed the api's real response shape, not a hand-made `matches`
  (the 2026-11-27 live probe read `matches` from the spec example and got undefined
  while `ok` was true, because the agent passed `{blocks: [...]}` through)

#### Scenario: A tick with no declared queries costs no mod read
- **GIVEN** a script with no `queries` assignment
- **WHEN** the tick runs
- **THEN** no `find_blocks`, `find_entities`, `block_at` or `locate` call MUST be made
- **AND** `look` MUST still answer from the snapshot as before

#### Scenario: A dynamic declaration is refused, not executed
- **GIVEN** `queries = [getQuery()]` or `queries = someVar`
- **WHEN** the script is bound
- **THEN** it MUST be refused with a reason naming the declaration, before any
  part of it runs
- **AND** no code inside the declaration MUST execute

#### Scenario: A declared value above the clamp is narrowed and says so
- **GIVEN** `{kind:"blocks", id:"minecraft:stone", radius:128}`
- **WHEN** the query is run
- **THEN** the mod MUST be asked for at most radius 32
- **AND** `look.queries.<name>` MUST carry the clamp (e.g. `clamped: {radius: 32}`)

#### Scenario: A failed query is not an empty one
- **GIVEN** a declared query whose mod call times out
- **WHEN** the tick runs
- **THEN** `look.queries.<name>` MUST be `{ ok: false, reason: "timeout", ... }`
- **AND** it MUST NOT be `{ ok: true, matches: [] }`
- **AND** the other declared queries MUST still be present and correct
- **AND** the tick MUST NOT fail because of it

#### Scenario: A query cannot act
- **GIVEN** the code that runs declared queries
- **WHEN** its call sites are inspected
- **THEN** they MUST be only `find_blocks`, `find_entities`, `block_at`, `locate`
- **AND** no `goto`, `mine`, `place`, `attack` or `set_directive` route


**An answer carrying an `error` key is a failure, not an empty list.**
Both search verbs catch their own exception and complete with an empty list
(`HttpApiServer` `find_blocks` at `:1124`, `find_entities` at `:1134`), so today
a search that threw and a search that found nothing are the same bytes on the
wire. The mod MUST answer a failed search from either verb with an `error` key
beside its list (`{blocks: [], error: "<reason>"}` and
`{entities: [], error: "<reason>"}`, the shape `scan_data` already uses at
`:1420`), and this agent MUST read that key as a failure for that query only:
`look.queries.<name>` is
`{ok: false, reason: "error", message: <the mod's own text>}`. A bare
`{blocks: []}` or `{entities: []}` with no `error` key MUST stay
`{ok: true, matches: []}`, because that is a search that ran and found nothing --
the opposite fact, and the one a planner acts on. Both halves are required: the
mod fix alone leaves the agent reporting success on a failed search, and the
agent guard alone is inert while nothing sends an error key. The agent half is
one rule for both verbs, because `_normalise_query_result` reads the `error` key
without knowing which verb produced it; a second, parallel agent rule for
`entities` would be a copy that can drift.

#### Scenario: A search that threw is a failure, not an empty result
- **GIVEN** a declared `blocks` query, and the mod answering
  `{blocks: [], error: "findBlocks error: ..."}` because its search threw
- **AND** a declared `entities` query, and the mod answering
  `{entities: [], error: "findEntities error: ..."}` because its search threw
- **WHEN** the tick runs
- **THEN** each `look.queries.<name>` MUST be `{ ok: false, reason: "error" }`
- **AND** each `message` MUST carry the mod's own error text, so the planner can
  tell a broken search from a world with nothing in it
- **AND** the other declared queries MUST still be present and correct
- **AND** the tick MUST NOT fail because of either one

#### Scenario: A genuine empty result stays a success
- **GIVEN** a declared `blocks` query, and the mod answering `{blocks: []}` with
  no `error` key because the search ran and found nothing
- **AND** a declared `entities` query, and the mod answering `{entities: []}`
  with no `error` key for the same reason
- **WHEN** the tick runs
- **THEN** each `look.queries.<name>` MUST be `{ ok: true, matches: [] }`
- **AND** neither MUST carry `ok: false`, so the fix never turns a world with
  nothing in it into a reported failure

#### Scenario: The error-key path is driven by the mod's answer, not a raising stub
- **GIVEN** the tests for the scenarios above
- **WHEN** they are inspected
- **THEN** they MUST feed `{blocks: [], error: ...}` and
  `{entities: [], error: ...}` through the agent's declared-query normaliser
- **AND** they MUST NOT stand in for it by making `find_blocks` or
  `find_entities` raise, because a raising stub exercises the transport's
  `except` branch rather than the error-key path, and the guard could be deleted
  with the suite still green
