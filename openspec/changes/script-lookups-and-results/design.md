# Design: script lookups (b) and script results (c)

Read before acting. Every claim about existing behaviour below carries a
`file:line` from the tree as it stands at `5adc9c2` (agent) / `549c80d`
(runner). Where I could not establish a fact from the source, it says so.

## Facts this design rests on

**The tick's data is already complete for most lookups.** Every tick the agent
sends a snapshot built by `agent/snapshot.py:49-77`:

| Field | Source | Shape |
|---|---|---|
| `health` | `api.status` line 68 | number or null |
| `food` | `api.status` line 69 | number or null |
| `position` | `api.status` line 70 | object or null |
| `inventory` | `api.inventory(bot)` line 71 | list |
| `nearby.blocks` | `api.blocks(bot, 8)` line 73 | **radius 5 in practice** — see below |
| `nearby.mobs` | `api.entities(bot, 24.0)` line 74 | **radius 16 in practice** — see below |
| `task` | directive line 76 | object or null |

Wrapped by `build_envelope` (`snapshot.py:80-100`) with `tick`, `server_ms`,
`events`, and sent as the tick request's `snapshot` key
(`agent/script_tick.py:419`).

**The radii the agent asks for are not the radii the bot gets.** `snapshot.py:49`
defaults `block_radius=8, entity_radius=24.0`, but the request lands on endpoints
that ignore the radius: `HttpApiServer.java:505` returns `bot.getCachedBlocks()`
and `:504` returns `bot.getCachedEntities()`, neither reading a radius from the
body. Those caches are built in `BotPlayer.refreshCache()`
(`BotPlayer.java:616-621`) every 40 ticks (`:531-532`):

- `cachedEntities = getNearbyEntities(16.0)` — **radius 16**
- `cachedBlocks = getNearbyBlocks(5)` — **radius 5**

So the answerable volume is smaller than the request implies in both dimensions.
Everything below uses 5 and 16, because those are the numbers the product has.

**The shapes of the two nearby lists are fixed by the Java that builds them**
(`BotPlayer.java:878-919`), not by the Python that forwards them:

- **`nearby.blocks`**: `{block: <display name>, position: <pos>}`. `block` is
  `state.getBlock().getName().getString()` (`:905`) — a **display name** such as
  `"Oak Planks"`, not a registry id. One entry per distinct name
  (`seen.add(blockName)`, `:906`), so the list holds the **first** position seen
  for each name and no others: a second chest is invisible. Within radius 5 this
  is the 11×11×11 cube around the bot (`1331` cells).
- **`nearby.mobs`**: `{type, name, position, distance, health?}`. `distance` is
  `String.format("%.1f", ...)` — **a string**, not a number (`:886`), so any
  comparison must parse it. `health` is present only for `LivingEntity`.

**The runner installs it as a read-only global** named `snapshot`
(`src/engine.js:737-750` install comment, `#installSnapshot` at `:752`, called
at `:418`; the freeze source is built at `:771` and the global is set at
`:778`), separate from `api`.

**Only six host functions exist** (`src/binding.js:230-330`): `do`, `say`,
`send`, `recall`, `remember`, `log`.

**The host-call budget is 8 per tick and it is shared**
(`src/binding.js:32` `MAX_HOST_CALLS`, counted in `accept()` at
`:138-145`). `do`, `say` and `send` each spend from it. A lookup that spends a
host call is spending a slot that a game action wanted.

**The CPU budget is 250 ms of measured CPU per tick**
(`src/engine.js:62` `TICK_CPU_MS`), measured with QuickJS's interrupt handler
(`:65-102`) and checked every 64 calls (`:88`). It is CPU, not wall time.

**The snapshot is up to 2 seconds old.** The caches refresh every 40 ticks
(`BotPlayer.java:531-532`), and a tick is 20 ticks/s, so a script reads data
aged 0–2000 ms. Fine for "nearest sheep" at walking speed; a real hazard for
"is there lava adjacent". `server_ms` is in the envelope (`snapshot.py:80-100`),
so the age is reportable rather than merely known.

**What is NOT established:** whether radius 5/16 is wide enough for the lookups
the planner actually wanted, because the scripts the planner has produced so far
needed no lookup at all (§1, "Observed demand").

---

## §1 What a lookup is

### Option A — a pure function over the snapshot already sent (RECOMMENDED)

A `look` object is installed beside `api` and `snapshot`, holding functions
that walk the tick's snapshot literal. No host call, no network, no mod.

```js
// The script, this tick:
const sheep = look.nearest({ kind: 'mob', type: 'sheep' });
if (sheep && sheep.dist < 6) api.do('SHEAR_NEAREST', { id: sheep.id });
```

**Cost.** Zero host calls, so none taken from the 8. Zero imposed latency. CPU
spent walking a list of at most a few hundred entries, well inside the 250 ms
budget, and the existing interrupt handler already bounds a runaway walk.

**The bound that comes with it.** A pure lookup can only answer questions the
agent already put in the snapshot. Anything outside radius 5 (blocks) or 16
(mobs), anything whose colour or block state matters, and any second instance of
a block name are unanswerable — and a lookup that silently returns empty for data
that was never sent is the failure mode to guard against (§2).

### Option B — a live read that calls back to the agent or mod during the tick

The script calls `look.blocks(radius=32)` and the runner makes a round trip
mid-evaluate.

**Cost.** Each call spends one of the 8 host slots, competing directly with
`api.do`. It also blocks the tick on a network round trip inside a 250 ms CPU
budget that measures CPU and therefore does not stop a call that is asleep
waiting — so a hung agent turns the tick budget off rather than on. It requires
the runner to hold a request open mid-evaluation, which no current path does:
`main.js` handles one request and returns (`src/server.js` validates and
routes tick requests; there is no callback channel).

**Rejected.** The eight-host-call cap makes every live read a trade against the
bot's actions, and the mid-tick round trip has no existing transport to reuse.

### The lookups that matter, and what data each needs

Named by the task; "answered today" means the field is already in the snapshot,
"needs" means what a pure lookup would additionally require.

| Lookup | Needs | Answered by a snapshot lookup today? |
|---|---|---|
| sheep nearby | mobs filtered by type, with distance | **Yes**, radius 16; `distance` is a string and must be parsed |
| flower of a colour | block **state**, wide radius | **No.** Neither the cache nor the snapshot carries block state, and colour cannot be recovered from a display name reliably across resource packs and languages. Not "Partly". |
| inventory contents / count of an item | `inventory` | **Yes** |
| position | `position` | **Yes** |
| nearest block of a kind | blocks filtered by name | **Partly** — radius 5, display names only, and only the first of each name |

So of the five lookups the task named, **three are answered in full, one is
answered badly, and one cannot be answered at all**. That is a thinner result
than "Option A covers the cases" implies, and it is the fact the
recommendation below turns on.

### Observed demand

The scripts the planner has actually produced on test needed **no lookup**: the
repeating goal (`"<Scout> all clear"`) is a `say` on a timer; the sheep goal
dry-ticked, bound and "ticked idle"; and the one-shot goal that would have
needed the richest lookup — "go find a flower nearby and tell me what colour it
is" — never became a script (2a.9 trial record in
`openspec/changes/ai-written-scripts/tasks.md`). Demand for (b) is a plausible
future need, **not an observed one**. Step (b) is still the owner's explicit
requirement and is not gated on demand (F3); what demand should decide is
*which lookups come first*, not whether to build the step.

### Option A is too thin as it stands: re-decision

Option A over today's snapshot can answer three of five queries, and the two it
misses are the ones a script is most likely to want — "find a thing of this
kind nearby" over a useful distance, and anything about block state. Making A
adequate needs three changes to what the agent sends:

| Change | Effect | Cost |
|---|---|---|
| Real registry ids in `nearby.blocks` | colour or block kind can be matched on `minecraft:poppy` rather than `"Poppy"` | the Java builder must put `BuiltInRegistries.BLOCK.getKey(...)` in each entry; the display name is kept alongside. No extra scan. |
| Stop deduplicating by name | a second chest becomes visible | the entry count for radius 5 is bounded by distinct **positions**, worst case the 1331-cell cube; today it is bounded by distinct names (tens). The tick payload grows. |
| Widen the radius | "chest within 16" becomes answerable | scanning is cubic: radius 5 is 1331 cells, radius 8 is 4913, radius 16 is 35937, radius 32 is 274625. At radius 16 the mod scans ~27× more cells than today, every 40 ticks, on the server thread (`BotPlayer.java:616-621` is called from the tick). |

The third row is the expensive one and the one I cannot cost in milliseconds
from source — §5 makes it a measurement, not an estimate.

### The alternative: expose `find_blocks` as one host-call lookup

`findBlocks(blockName, radius, maxCount)` already exists
(`BotPlayer.java:1238-1263`) and is already reachable from a planner step as
`agent/api.py:110` (`find_blocks`, default radius 32). It returns **real
registry ids** (`info.put("block", id)`, `:1253`), no deduplication, and stops at
`maxCount` (default 10). It scans the same cube, but **on demand for one query**
rather than every 40 ticks for all queries.

**Cost, in numbers from source:** one host call out of the 8 shared per tick
(`binding.js:32`), so a script that calls it twice has spent a quarter of its
action budget. It is a live read, so it needs the mid-tick transport Option B
lacks — *unless* it is fetched by the **agent** before the tick and put in the
snapshot, which is the shape below.

### Recommendation

**Ship (b) as Option A, but grow the snapshot first, and do not build a
`look` that pretends to search further than it does.** Concretely:

1. **Add real ids and drop the dedup** in the three block/mob fields. This is
   cheap (same scan, larger payload) and fixes the two failures that make A thin.
2. **Leave the radii at 5/16 for the first ship**, and have `look` report the
   radius it searched and return a distinguishable "not searched that far"
   rather than `[]`. §5 measures whether a wider radius is affordable before any
   change.
3. **Do not add a host-call lookup in this change.** If a later trial shows a
   script asking for something beyond the radius, the answer is to widen the
   snapshot (§5), not to spend an action slot — but the *task* to count that
   demand is added (tasks 1.4) so the decision is made on evidence.

This is the lead's F1–F3 applied: A is not sufficient as written, the cheap
grow-snapshot step is separable from the expensive widen-radius step, and the
host-call alternative is costed rather than dismissed.

---

## §2 Read-only guarantee

The guarantee is structural, not a policy the lookup code agrees to follow.

**How a lookup provably cannot act.** `look` has no reference to `api`. It is
built from the snapshot literal and closes over nothing else. It cannot call
`api.do`, because `api` is not in its scope; it cannot spend a host call,
because `accept()` (`binding.js:138-147`) is only reachable through `api`'s
methods; and it cannot reach the network or the mod, because QuickJS in this
runner exposes no I/O and the only path to the agent is the tick response.

**How it cannot write.** The snapshot is installed read-only
(`engine.js:752`, freeze path `:771-778`). A lookup returns new objects derived
from it; it never
returns a live reference the script could mutate back into the shared literal.
**Design decision:** `look` results are deep copies, not views. A script that
mutates a returned array must not affect the next lookup in the same tick.

**How it cannot reach a secret.** The snapshot is built from six
`api` reads (`snapshot.py:68-76`) — health, food, position, inventory, blocks,
entities. It carries no token, no game id, no environment. A lookup over it can
therefore only return data the game already handed the bot. This is the reason
the snapshot is the right substrate and a live read is not: a live read would
put the agent's own request path within a script's reach.

**The script must be told how old its data is.** The snapshot is a cache up to
2 s stale (facts above). A lookup that answers "is there lava adjacent" from
2000 ms-old data is a hazard, and the script cannot currently tell. `look` gains
`look.age_ms()` and every result object carries `age_ms`, computed from the
envelope's `server_ms` (`snapshot.py:80-100`) and the tick's own time — no new
field on the wire, no extra call. A script that cares can refuse to act on stale
data; one that does not is at least able to log it.

**What the dry tick sees.** A dry tick runs the same script against the same
snapshot: `snapshot` is set unconditionally in the tick body at
`agent/script_tick.py:419`, while `dry` is added only when set at `:425-426`, so
the snapshot travels on both paths. Lookups behave identically under dry, which is what
makes the dry gate a true preview of what the script will see. This follows
from Option A falling out of the snapshot; under Option B it would not be true
without extra work, because a dry tick must not reach the live agent.

---

## §3 What "result" means and when it goes back

### What the result is

**The script's return value, and nothing else.** Not its logs (already
delivered through `last_logs` and printed by the agent, `script_tick.py`), not
its delivered actions (already dispatched), not a separate "final report" API.

Rationale: the runner already decides how a script's return value is obtained —
`#evalSource` distinguishes a body with a top-level `return` from a bare
expression whose value *is* the result (`engine.js:666` onwards). The mechanism
exists and is tested; a new "report" channel would duplicate it.

**Shape.** A script that wants to report returns an object:

```js
return { done: true, say: 'furnace is full', items: 64 };
```

**Size cap.** 2 KiB of JSON after serialisation. A script returning more has the
result truncated with a marker, not dropped — a truncated result the planner can
see beats a missing one, and the script's 8-host-call and 250 ms budgets are
untouched either way. (2 KiB is a proposal, not a measurement; it should be set
against the largest genuinely useful report in the trial, §4.)

### When it goes back

Three triggers, and only three:

1. **On completion** — the result object carries `done: true`.
2. **On error** — the tick failed and the script had returned nothing yet.
3. **On a stated escalation** — the script returns `escalate: true` without
   `done`.

**Not every tick.** A per-tick result is one planner call per tick per bot:
with ~61 s ticks that is ~59 an hour per bot, on the owner's shared
subscription. Rejected on cost alone.

### The delivery contract

"Renders on the next `call_plan`" is not a contract until it says what "next"
means and what happens when there is none. All four of these are stated here
because each has a failure mode in the current loop.

**What keys a result: bot + goal.** `bindings.json` is per **bot**, not per goal
(`ai-written-scripts` spec, condition 2), so a result keyed only by bot can be
rendered into a call about a *different* goal — the planner would read a result
from the goal it abandoned. Every result therefore carries `{bot, goal_id}` and
is only rendered into a `call_plan` for that same `goal_id`.

**What triggers the planner call that reads it.** Today the only path that
starts the planner from the world is `_maybe_plan(new_messages)`
(`agent/agent.py:518`, called at `:3413`), and it returns immediately on
`if not new_messages: return` (`:520`). **A script that reaches `done` releases
its binding and says nothing, so no `call_plan` runs until a player next
speaks.** A result therefore sits unread until someone talks. This is accepted,
not worked around: waking the planner on a result would be the per-tick planner
call this design rejected on cost. **A result is delivered on the next player
message, or not at all** — and §3's "bounding" caps then act as belt and braces
rather than as the load-bearing guard.

**The one slot and its eviction rule.** There is one pending result per
`{bot, goal_id}`. A newer result for the same key **overwrites** the older one,
and the overwrite is logged with both results' triggers. A result is
**discarded**, not delivered, when:

- the goal it belongs to is no longer the bot's current goal (a new directive
  arrived) — the discard is logged with both goal ids;
- it has been pending for more than **30 minutes** — older than that, the world
  it describes has moved on and the planner should plan fresh;
- the next planning call is for a different `goal_id` (rule 1).

**What is never done:** a result does not start a planner call, does not
interrupt a running script, and does not queue more than one entry per key. The
worst case is one stale observation rendered once, which the discard rules bound.

### Bounding the loop

Three caps, each independently sufficient to stop a runaway:

- **Per bot, at most 4 result-driven planner calls per hour.** A fourth within
  the hour is logged and dropped, with the drop counted. At ~59 ticks an hour
  this is the difference between 4 planner calls and 59.
- **A cooldown after each delivered result** — no second result from the same
  script within 15 minutes, whatever its trigger. This is what stops a script
  whose `done: true` is a bug from re-planning every tick.
- **The script stops on completion.** A `done: true` result releases the
  binding, so there is no next tick to trigger on until the planner writes a
  new script.

**Cost stated plainly:** worst case 4 planner calls/hour/bot from results. For
the bots on test that is a bounded, small number; it is not zero, and the trial
in §4 measures it.

---

## §4 How (b) and (c) are proven on test

Same shape as the 2a.9 trial: the lead runs it, I design the observable, and
every claim is counted from the log with grep against a stated revision.

**Lookup trial.**
- A goal needing a lookup the snapshot already answers: "whenever a sheep is
  within 6 blocks, shear it". Expect: the script runs, calls `look.nearest`,
  and dispatches `SHEAR_NEAREST` only when a sheep is actually near.
- A goal needing data beyond the snapshot's radius: "when you find
  diamonds within 40 blocks…". Expect: the lookup reports "not searched that
  far" and the script escalates rather than silently doing nothing — this is
  the assertion that proves the §1 insufficiency is visible rather than silent.
- Count: `grep -c 'look:' agent.log` for lookups, and the dispatch line for
  the action.

**Result trial.**
- A goal that completes: expect exactly one result delivered, one planner call,
  and `grep -c 'result delivered'` == 1 over the run.
- A goal whose script errors: expect a result on the error path, not a silent
  log line.
- A deliberately looping script (returns `done: true` every tick): expect the
  per-bot 4/hour cap and the 15-minute cooldown to hold, and the drop counter
  to be non-zero — this is the trial that proves the loop bound actually binds.

**Tests that must red under a mutant** (each a test plus a deliberately wrong
implementation that turns it red, as every prior test in this path has done):
- A lookup that returns a live reference into the snapshot — mutant: return
  the snapshot's own array; the test mutates the result and asserts the next
  lookup is unaffected.
- A lookup that spends a host call — mutant: route through `accept()`; the test
  asserts `hostCalls` is unchanged after 20 lookups.
- A result path that fires every tick — mutant: remove the cooldown; the test
  drives 10 ticks and asserts exactly 1 delivered result.
- A result over the size cap — mutant: drop instead of truncate; the test
  asserts the truncation marker is present.

---

## §5 Out of scope

- Any agent or runner code. This change is design only.
- A lookup outside the snapshot's data (Option B). If a trial shows a recurring
  need beyond radius 5/16, the first move is to widen the snapshot — a separate
  decision with its own cost, measured in §5 of the tasks rather than estimated
  here: scanning is cubic, so radius 8 is 4913 cells and radius 16 is 35937
  against radius 5's 1331.
- Adding a host-call lookup (`find_blocks`) inside the sandbox in this change.
  It is costed in §1 and deferred; the task that would justify it is tasks 1.4.
- Delivering logs or actions to the planner.
- Changing the `done`/`escalate` vocabulary into anything richer (a typed
  report schema) before a trial shows the simple object is not enough.
- The chat-pauses-script rule (M3-1g) and the dry gate's semantics, both
  unchanged.
- Archiving `ai-written-scripts`. This change is separate and lands on its own.
  **Noted for the lead (F6.2):** there is no archived `bot-coded-agents` spec —
  it exists only as a delta target under four unfinished changes, and
  `openspec/specs/` has no such directory. So `bot-coded-agents` stays
  unarchived across all of them and there is no live spec to regress against.
  Not fixed here; recorded so it is not discovered late.
