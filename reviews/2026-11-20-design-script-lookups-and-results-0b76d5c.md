# Design review: script lookups (b) and script results (c) — `0b76d5c`

**Rev:** `0b76d5c` in `minecraft-wt-deepseek`, change `script-lookups-and-results`
**Kind:** design review, pre-code. 269 design, 61 proposal, 60 tasks, 78 spec delta.
**Row:** none — requested by `minecraft-lead` by `rig send` at 22:47Z.
**Verdict:** **REVISE BEFORE CODE.** The shape is right and should be built. Three of
its load-bearing "facts" are wrong against the tree, one of them changes the
recommendation, and the result path has no scheduler.

Sources read at their own revs: agent `5adc9c2`, runner `549c80d`,
mod `src/main/java/.../BotPlayer.java` at `5adc9c2`.

---

## What the design gets right, and should keep

- **Option A over Option B is correct and well argued.** A pure lookup over the
  snapshot costs no host call, so it cannot trade against `api.do`; Option B would
  spend one of 8 shared slots (`src/binding.js:31-32`, confirmed `MAX_HOST_CALLS
  = 8`) and needs a mid-tick callback transport that does not exist
  (`engine.js` handles one request and returns). I checked for one; there is none.
- **Read-only by construction is achievable and the mechanism is real.** The
  snapshot is `null`-safe installed and **deep-frozen** (`engine.js:752`, freeze
  emitted at `:766-776`) — I read it, and it is a deep freeze, not just the top
  level. A `look` built from that literal genuinely cannot reach `api`.
- **The result-trigger set (done / error / escalate) and "next planning call, not
  a new turn" are the right cost shape.**
- **The §4 test-first mutants are the right instrument** and match how this path
  has been reviewed all along.

---

## F1 — the snapshot radii in the design are not the radii the bot gets

This is the finding that matters most, because §1 is built on it.

The design says `nearby.blocks` is radius 8 and `nearby.mobs` is radius 24
(`design.md:18-19`, citing `snapshot.py:73-74`). Those are **the radii the agent
asks for**, and `snapshot.py:49` does default them to `block_radius=8,
entity_radius=24.0`. But the agent's request reaches an endpoint that **ignores
the radius entirely**:

- `HttpApiServer.java:505` — `case "blocks" -> ... bot.getCachedBlocks()`
- `HttpApiServer.java:504` — `case "entities" -> ... bot.getCachedEntities()`

No radius is read, passed or parsed. The values come from a fixed cache built in
`BotPlayer.refreshCache()` (`:616-621`) every 40 ticks (`:532`):

- `cachedBlocks = getNearbyBlocks(5)` — **radius 5**, not 8
- `cachedEntities = getNearbyEntities(16.0)` — **radius 16**, not 24

So the effective answerable volume is **smaller than the design claims in both
dimensions** — 5 vs 8 for blocks, 16 vs 24 for mobs. The design's §1 table marks
"sheep nearby" as **Yes, radius 24**; the true figure is 16. It marks
"nearest block of a kind" as **Partly — only within radius 8**; the true figure is
5. Any scenario, trial or task written against 8/24 is written against a number
the product does not have.

This is the "an empty result means fix the query first" failure in the other
direction: the design read `snapshot.py` correctly and stopped one hop short of
the endpoint that actually serves the data.

## F2 — the block and mob field shapes the design says it could not establish

`design.md:95` says of `nearby.blocks`, "its fields are not listed in the source
I read". They are — but not in the Python, so a reader who stops at `snapshot.py`
misses them. From the Java that builds the cache:

- **Blocks** (`BotPlayer.java:895-919`): each entry is `{"block": <name>,
  "position": <pos>}`. `block` is `state.getBlock().getName().getString()` — a
  **display name** ("Oak Planks"), not a registry id. **One entry per distinct
  block name** (`seen.add(blockName)`), so the list is deduplicated by name and
  carries the first position seen for each — not all positions.
- **Mobs** (`BotPlayer.java`, `getNearbyEntities`): each entry is `{"type":
  <short id>, "name": <string>, "position": <pos>, "distance": <string>,
  "health": <number>}`.

Three consequences the design does not account for:

1. **"flower of a colour" is closer to unanswerable than "Partly".** A colour is
   a property of the block *state*, and neither the cache nor the snapshot carries
   it. Parsing it from a display name is unreliable across resource packs and
   languages. The design's "colour is a block-id property the lookup can parse if
   the id is present" (`:95`) is false for the product: the id is **not** present.
2. **"distance must be computed from positions"** (`:94`) is unnecessary — mobs
   already carry `distance`. But it is a **string** (`"%.1f"`), so `look.nearest`
   must parse it or recompute; a naive numeric compare against a string is the
   kind of bug that ships quietly.
3. **A deduplicated block list cannot answer "is there a chest within 16
   blocks"** with any confidence: it holds one position per block *name*, so a
   second chest is invisible, and 5 blocks is very short range — roughly a
   player's reach plus a step.

## F3 — the one empirical question the design lists as NOT established is answerable, and the answer changes the recommendation

`design.md:41-44` states plainly: *"whether the snapshot's radius-8 blocks and
radius-24 mobs are wide enough for the lookups the planner actually wanted. I have
not read the planner's last scripts to find out."* That is honest and it is the
right thing to flag. The evidence exists in the tree, though — the 2a.9 trial
record (`openspec/changes/ai-written-scripts/tasks.md`, corrected at `5594bfa`)
names the two goals that actually ran:

- **Repeating goal:** `"<Scout> all clear"` — `api.say` seven times over ten
  minutes, 61-62 s apart. **Needs no lookup at all.**
- **One-shot goal:** `"Scout, go find a flower nearby and tell me what colour it
  is"` — the plan was written with no SCRIPT call. It never became a script.
- **Sheep goal** (21:45Z): dry-tick accepted, bound, **"script ticked idle"** —
  it did not shear a sheep; it also did not exercise a lookup.

So of the scripts the planner has actually produced on test, **none needed a
lookup**, and the one goal that would have needed the richest one (flower
colour) is the one the planner declined to script. The design's premise — "a
script that wants the nearest sheep … has to re-derive it from a fixed-radius
list" — is a plausible future need, not an observed one.

**That does not kill (b), but it reorders it.** The design recommends "grow the
snapshot from a call the agent already makes" as the fallback if lookups need
more range. Given F1 (real radii 5/16) and F2 (display names, dedup), a `look`
shipped today would answer *fewer* questions than the design's table advertises,
and the demonstrated demand is zero. The cheaper first move is the one the design
itself names and then defers: **expose `find_blocks`/`find_entities`**, which
already exist with radius 32 defaults (`agent/api.py:110-113`, `:208-209`) and
already return real ids. That is a one-function change with no new object, no
copy semantics, no out-of-range vocabulary — and it is a live host call, so it
must spend a host slot, which is exactly the trade the design correctly refused
for *lookups* but is the right trade for *one* explicit seek.

I am not rejecting (b). I am saying: **prove the need before building the
substrate.** Add one task — read the planner's actual scripts from the next trial
and count how many would call a lookup at all — before 2.1.

## F4 — the result has no scheduler, so "the next call_plan" is not guaranteed to arrive

`design.md:193-197`: a result is stored as a pending observation and rendered
into "the next `call_plan`". The design assumes a next planning call happens.

At the agent rev, the **only** path that starts the planner from the world is
`_maybe_plan(new_messages)` (`agent.py:518`, called at `:3413`), and it returns
immediately on `if not new_messages: return`. A script that reaches `done`
releases its binding and says nothing. Unless a player speaks again, **no
`call_plan` runs**, and the result sits unread.

This matters for the lead's explicit questions:

- **"Can any path call the planner per tick?"** — No, and that is good: nothing
  in the current loop calls the planner without a new message, so the loop risk
  is smaller than the design fears. The 4/hour cap and 15-minute cooldown are
  belt-and-braces, not the load-bearing guard.
- **"Can a result be lost?"** — **Yes, routinely.** On a one-shot goal the
  result reaches no planner until the player next speaks, and could be
  overwritten by a later result before then (the design has one "pending
  observation" slot and no stated eviction rule).
- **"Arrive at the wrong bot or goal?"** — the design does not say how a result
  is keyed. `bindings.json` is per **bot**, not per goal (`ai-written-scripts`
  spec, condition 2), so a result stored per bot can be surfaced into a call
  about a *different* goal. That needs an explicit goal key, or a stated rule
  that results are bot-scoped and a new goal discards them.

**Recommendation:** before 3.4, state the delivery contract precisely — what
keys a result (bot? goal? both), when a pending result is discarded, and what
happens when a result is produced and no planner runs. "Renders on the next call"
is not a contract until it says what "next" means.

## F5 — (3) read-only: sound, with one caveat the design should state

The structural argument holds and I verified its anchors: no `api` in `look`'s
scope, no path to `accept()`, QuickJS exposes no I/O, snapshot deep-frozen and
JSON-copied at the boundary (`engine.js:752`, `:766-776`).

Caveat: **a lookup is read-only over a snapshot that is up to 2 s stale** (cache
refreshed every 40 ticks, `BotPlayer.java:532`). For "nearest sheep" at walking
speed that is fine; for "is there lava adjacent" it is a real hazard. The design
should say the data's age, and `look` should be able to report it — the snapshot
already carries `server_ms` (`design.md:22`), so this is cheap.

## F6 — (4) nothing is removed or contradicted, but the archived spec does not exist

The lead asked whether the delta removes or contradicts anything in
`ai-written-scripts` or the **archived** `bot-coded-agents` spec.

- **Nothing removed or contradicted.** The delta is `## ADDED Requirements` only,
  two new requirements, no `MODIFIED`/`REMOVED` header. I walked all 16
  requirement names in `ai-written-scripts`; none overlaps, and that delta never
  mentions lookups or results.
- **There is no archived `bot-coded-agents` spec.** It exists only as a delta
  target under four unfinished changes (`ai-written-scripts`, `coded-agents`,
  `nav-shortcut-stop-misfire`, this one); `openspec/specs/` has no such
  directory and there is no `openspec/changes/archive/`. So when this change says
  it "lands on its own" and does not archive `ai-written-scripts` (`§5`), the
  effect is that **`bot-coded-agents` stays unarchived across at least four
  changes**, and there is no live spec to regress against. That is a process
  risk worth the lead knowing, not a defect in this delta.
- One constraint this delta must be checked against, and I did: the result path
  adds text to the `call_plan` **prompt**, not the reply, so it does not touch
  `response_raw` / `parsed` / the DPO fields that `ai-written-scripts` pins so
  tightly. The delta should say so explicitly, because that requirement
  ("MUST NOT appear in any field the DPO trainer reads") is the one most easily
  broken by a well-meaning future edit to the prompt.

---

## Citation check (task 1.1 requires every `file:line` to resolve)

| Design cite | Reality | Status |
|---|---|---|
| `snapshot.py:49-77` | build_state spans `:49-77` | OK |
| `snapshot.py:73-74` | blocks/mobs lines | OK, **but radii are wrong (F1)** |
| `snapshot.py:80-100` | `build_envelope` at `:80` | OK |
| `binding.js:230-330` | six host functions | OK |
| `binding.js:31-32` | `MAX_HOST_CALLS = 8` | OK |
| `binding.js:138-145` | `accept()` budget | OK |
| `engine.js:62`, `:65-102` | `TICK_CPU_MS`, interrupt | not re-verified line-exact |
| `engine.js:738-748` | install comment starts `:737`; `#installSnapshot` at `:752` | **off by ~10 lines** |
| `engine.js:666` | `#evalSource` at `:666` | OK |
| `api.py:110-115` | `find_blocks` `:110`, `block_at` `:113` | OK |
| `main.js` / `src/server.js` | exist, one request per tick | OK |

The `engine.js:738-748` drift is minor but task 1.1 asks for every cite to resolve,
and 738 lands inside a comment block rather than on the method.

`openspec validate script-lookups-and-results --strict` → rc=0.

---

## What I'd change before code starts

1. **F1 is required:** correct the radii to 5/16 everywhere they appear (design,
   tasks, trials, spec scenarios), or grow the cache and say so. As written, three
   artefacts assert a range the bot does not have.
2. **F2 is required:** state the real block shape (`{block: display-name,
   position}`, deduplicated) and the real mob shape (including `distance` as a
   string), and revise "flower of a colour" from *Partly* to *No*.
3. **F3 is required:** add a task to read the planner's actual scripts and count
   lookup demand before 2.1; re-cost `find_blocks` (radius 32, already exists) as
   the cheaper first move.
4. **F4 is required:** define the result delivery key and the discard rule.
5. **F5, F6 and the citation drift are advisory.**

Nothing built, pushed, deployed or run against `ollama-l3`; no pod exec; nothing
in `ci`.
