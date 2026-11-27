# find_blocks reports its own failure

## Why

A failed block search and a genuine empty one are the same bytes on the wire
today. `HttpApiServer.java:1117-1127` runs `bot.findBlocks(...)` on the server
thread and, in its `catch`, completes the future with `List.of()` and logs
`findBlocks error` (`:1124`). The handler then answers every outcome with
`Map.of("blocks", ...)` — there is no `error` key on any path. So a planner or a
script that searches for iron ore and gets `{blocks: []}` cannot tell "there is
no iron ore within 32 blocks" from "the search threw". The first is a fact about
the world; the second is a fact about the mod. Collapsing them reports a broken
search as an empty world, which is the same silent-wrong-answer shape the agent
side was just fixed for.

The agent half is already live. `agent/script_tick.py:run_declared_queries` maps
a mod answer carrying an `error` key to `{ok: false, reason: "error", ...}` for
that one declared query, and leaves its siblings alone. That guard (commit
`9a8a083`, reviewed) is **inert today by construction**: no declared query kind
sends an `error` key, so it has never fired against a real mod answer. This
change is what makes it fire.

## What the failure looks like now, measured at `2f019c0`

| layer | on a failure | on a genuine empty |
|---|---|---|
| `BotPlayer.findBlocks` (`bot/BotPlayer.java:1286-1310`) | throws | returns `[]` |
| `HttpApiServer` `find_blocks` (`:1117-1127`) | `{blocks: []}` | `{blocks: []}` |
| `agent/api.py` `find_blocks` (`:133`) → `_post` (`:33-35`) | returns the dict, raises nothing | returns the dict |
| `agent/script_tick.py` `run_declared_queries` (`:734-753`) | `{ok: true, matches: []}` | `{ok: true, matches: []}` |

The throw is real and it is the only evidence of the failure: `findBlocks`
reaches the level, the registry and `formatBlockPos`, any of which can throw.
The mod catches it, logs it on the server, and answers 200.

## What Changes

1. **The mod distinguishes the two outcomes.** A `find_blocks` whose search
   throws answers with an `error` key naming it, plus its empty list, rather
   than a bare empty list. The success path is byte-identical to today.
2. **The agent half is pinned end to end.** The scenario that already exists for
   the agent's error handling gets a second one that drives the mod's *new*
   answer shape through the *real* normaliser, so the seam is tested, not the
   stub.

## Ordering against `script-lookups-and-results`

**This section replaces an earlier one that was wrong.** An earlier draft of this
change argued the requirement was not yet live and fixed an archive order against
`script-lookups-and-results`. That was true of the tree I tested and false of
`origin/main`: `script-lookups-and-results` was archived at `bf560d2`, which was
by then main's tip, and the requirement has been live since. The builder caught
it before writing any Java. The lesson is recorded here because it shaped the
delta: a scratch archive proves a property of the tree it ran on, and main moves.

So the requirement "A Script Declares The Searches It Needs And Reads Them As
`look.queries.<name>`" is **live** in `openspec/specs/bot-coded-agents/spec.md` at
`:1619`, with seven scenarios. This change is therefore **MODIFIED** against that
requirement, not ADDED beside it.

That is forced, not a preference: an ADDED delta cannot modify a live
requirement, and ADDED would have stranded the seven existing scenarios instead
of extending them. The delta was generated from the live text by substitution,
not retyped, so no scenario can be dropped by omission — ten scenarios in the
delta are the seven live ones verbatim plus three new.

There is no archive-order constraint left. `script-lookups-and-results` is
already archived, so this change can land in order whenever it is ready.

## What the live spec already says, and what it does not

The live requirement already carries the general rule, at `:1730-1735`:

> **A failed or timed-out query is not an empty result.** Each result MUST be
> `{ ok: false, reason, message }` on failure or timeout, never
> `{ ok: true, matches: [] }` …

So the agent-side obligation is already normative and this change does not invent
it. What the live text does not do is place any obligation on the **mod**: it
never says a caught exception must carry an `error` key, and its only failure
scenario (`:1799`) is `GIVEN … a declared query whose mod call times out` —
timeout only. A thrown `findBlocks` or `findEntities` is uncovered. Both sites
violate the general rule today. That is the gap this change closes, and it closes
it from the producer side so the rule becomes reachable.

## Repo and deploy scope

- The Java change is `neoforge-ai-player` `src/main/java`, unit-tested on the
  JVM; the deterministic half (the handler's failure mapping) goes in a plain
  JUnit test with no Minecraft classpath, in the shape
  `src/test/java/com/sigmastrain/aiplayermod/api/BoundedWaitTest.java`
  established. The end-to-end half needs a real world and belongs to the deploy
  run plan.
- **This ships as a new mod jar**, in a mod-side batch, not in A2's deploy. A2
  is not blocked by this change and ships first.
- No agent Python changes. No runner changes. No dashboard changes.

## What this does not do

- **`find_entities` is IN scope**, by the lead's decision of 11:58Z, reached
  independently from the live spec text: the general rule says a failed query
  MUST be `{ok: false, …}` and never `{ok: true, matches: []}`, and `:1134`
  breaks it exactly as `:1124` does. Both verbs are fixed here, each with its own
  api-http requirement so that neither half ships without a spec witness. They
  are two cases in one file with one wire shape and one consumer; reviewing them
  apart would review the identical delta twice, and shipping them apart would
  leave the mod lying about one verb for another release cycle.
- **It does not change `scan_data` or `surface_scan`.** `scan_data` already
  answers `{blocks: [], count: 0, error: "..."}` on its failure path (`:1420`)
  and is the model this change copies. `surface_scan` (`:1425`) is a different
  verb with a different answer shape and keeps its own behaviour.
- **It does not change the timeout path.** `boundedJoin` ↔ `BoundedWait` already
  turns a stalled server thread into a 503 with an `error` body (api-http: "Timeouts
  MUST be bounded and reported"), and the agent already maps a 503 to
  `reason: "unavailable"`. That path is untouched by this change and its
  scenario says so.
- **It does not widen or clamp any radius.** `find_blocks` still takes whatever
  it is sent (`HttpApiServer.java:1117-1120`); the caller-side clamp stays in
  `agent/script_tick.py:plan_declared_queries`.
