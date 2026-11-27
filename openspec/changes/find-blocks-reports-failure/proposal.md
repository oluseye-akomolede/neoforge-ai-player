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

## What this change does

1. **The mod distinguishes the two outcomes.** A `find_blocks` whose search
   throws answers with an `error` key naming it, plus its empty list, rather
   than a bare empty list. The success path is byte-identical to today.
2. **The agent half is pinned end to end.** The scenario that already exists for
   the agent's error handling gets a second one that drives the mod's *new*
   answer shape through the *real* normaliser, so the seam is tested, not the
   stub.

## Ordering against `script-lookups-and-results`

This change is written as **ADDED** against `bot-coded-agents`, not MODIFIED,
and that is a deliberate constraint rather than a preference.

The requirement it qualifies — "A Script Declares The Searches It Needs And
Reads Them As `look.queries.<name>`" — is not in `openspec/specs/bot-coded-agents/spec.md`
at `2f019c0`. It lives only in the pending change `script-lookups-and-results`.
I found this by writing the delta as MODIFIED first and running
`openspec validate --strict` (rc=0, "valid") and then `openspec archive`, which
warned: *"Archive would refuse this delta: bot-coded-agents MODIFIED failed for
header … not found"*. **Validation passing did not mean the change was
archivable** — the informational line, not the exit code, carried that.

So the spec requirement here is ADDED, and the two changes have a fixed archive
order: `script-lookups-and-results` first, this second. Verified by archiving
this change into a scratch copy of `origin/main`'s `openspec/`: it applies
(`+2, ~0, -0`) and the specs stay at 16/16.

**The cost of that order, stated plainly:** while
`script-lookups-and-results` is unarchived, the live spec contains no text
defining `look.queries` at all, so this requirement describes a construct with no
live definition. Archiving this change first makes the spec *more* incoherent,
not less — I archived it into the scratch tree and confirmed the resulting spec
names `look.queries` with nothing defining it. Archiving `script-lookups-and-results`
first closes that gap; this change should not land alone.

That pending change is also the normative source for the shape this change
extends, including the sentence "A failed or timed-out query is not an empty
result", and it already carries the agent-side failure rule. This change is the
mod-side half of it, split out because the mod half is a new jar and the agent
half is already deployed.

**This is not the agent's job to fix and not a behaviour change the agent can
make.** The agent cannot invent the distinction; it can only pass on what the
mod sends. Until the mod sends it, `run_declared_queries` is provably unable to
tell the two apart, and the guard it already carries is dead code.

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

- **It does not touch `find_entities`.** That route has the same swallow at
  `:1134` and the same missing `error` key. It is the same defect in a sibling
  handler and it is out of scope here on purpose: one defect, one change, one
  reviewable diff. It is recorded in the delta's reasoning and should be filed
  as its own row rather than quietly swept in. If the lead would rather fix both
  in one diff, say so before the builder starts — the shape is identical and the
  cost is one more case.
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
