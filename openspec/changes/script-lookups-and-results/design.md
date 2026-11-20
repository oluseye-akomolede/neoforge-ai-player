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
| Stop deduplicating by name | a second chest becomes visible | the entry count for radius 5 is bounded by distinct **positions**, worst case the 1331-cell cube; today it is bounded by distinct names (tens). **The tick payload grows from about 1-3 KiB to about 57 KiB** — see the arithmetic below. |
| Widen the radius | "chest within 16" becomes answerable | scanning is cubic: radius 5 is 1331 cells, radius 8 is 4913, radius 16 is 35937, radius 32 is 274625. At radius 16 the mod scans ~27× more cells than today, every 40 ticks, on the server thread (`BotPlayer.java:616-621` is called from the tick). |

The third row is the expensive one and the one I cannot cost in milliseconds
from source — §5 makes it a measurement, not an estimate.

**The payload arithmetic for row 2.** One entry is built at
`BotPlayer.java:907-910` as `{"block":"<display name>","position":"<x,y,z>"}`.
Over 20 real block display names (`BotPlayer.java:905` is
`state.getBlock().getName().getString()`) the names run 4-14 chars, median 7,
so an entry is 41-51 bytes, median **44**. Today `seen.add(blockName)` at
`:906` keeps one entry per distinct name, so a radius-5 tick carries roughly
**0.9-2.6 KiB** for 20-60 distinct names: that is the 1-3 KiB of today's
payload. Remove the dedup and the entry count becomes every non-air cell in
the 1331-cell cube: **1331 entries × 44 B ≈ 57 KiB** — 30-54 KiB was the
reviewer's estimate under partial fill; 57 KiB is the full-cube bound computed
from the same 44-byte entry. Sent every 40 ticks that is about 1.5 KiB/s of
extra egress per bot for a payload most ticks cannot use.

**If that is too big every tick, bound it rather than ship it.** The bound is
**true nearest K per block id** for this ship:
for K=2 and 40 distinct names, 80 entries ≈ **3.4 KiB**; K=4 gives ≈ 6.9 KiB.
That keeps "a second chest" answerable (K≥2) and stays inside today's order of
magnitude.

**It is a ranking, not a counter.** The obvious cheaper reading — "keep the
first K entries of each id" — is wrong, and wrong in a way that looks fine
until replayed. `BotPlayer.java:893-897` walks `x`, then `y`, then `z` upward
from `(-r,-r,-r)` and computes **no distance at all**: `state.getBlock()`,
`getName()`, and a `position` string, nothing else. So a counter keeps whichever
K were met first in scan order, which is the K nearest the **far corner**, not
the bot. Replayed at K=1 that keeps a chest 8.66 blocks away and drops one 2.83
blocks away — the bound would silently starve the lookups it exists to serve.

What true nearest-K needs, stated as three changes to that method:

1. **A squared distance per candidate**, computed from the bot's block position
   at cache-refresh time: `dx*dx + dy*dy + dz*dz`. Integer, no square root, no
   allocation.
2. **K-bounded insertion per block id** rather than first-K: each id keeps its
   best K, inserting a candidate and evicting the worst when full. K is tiny
   (2 or 4), so this is an insertion into a short list, not a sort of the cube.
3. **A deterministic tie-break**: equal distances are ordered by **scan order**
   (the existing `x`, `y`, `z` walk), so two runs over the same world produce
   the same payload and a test can pin it.

**Cost, honestly:** up to **1331 integer distance computations** per refresh
for the worst-case cube (fewer when air is skipped earlier, which it is not —
air is tested inside the loop at `:904`), plus a K-bounded insertion for every
non-air cell. Every 40 ticks. It is real work on the server thread in the same
walk, but it is arithmetic and short-list insertion, not a sort and not a
second scan. I am not calling it "a few lines with no sort" — it is a ranking
with a stated bound, and its cost is the 1331 computations above.

**Pinned by the case that catches it:** a chest at `(2,0,2)` and another at
`(-5,-5,-5)` from a bot at the origin, K=1. True nearest-K keeps `(2,0,2)`
(8 squared) and drops `(-5,-5,-5)` (75 squared). Scan-order code keeps the
opposite. The test asserts the kept position, so it fails on scan-order.

### A named follow-up: `find_blocks` as a script lookup

Exposing `find_blocks` as a host call at radius 32 is **not in this ship**. It
is recorded here as the follow-up that removes the radius ceiling entirely,
with its cost, so the decision to defer it is on the page rather than implied.
Its numbers are in the next section.

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

**An explicit `api.result(v)` host call, and nothing else.** Not the script's
logs (already delivered through `last_logs` and printed by the agent,
`script_tick.py`), not its delivered actions (already dispatched), and *not*
the script's top-level return value.

**Why not the return value.** The runner drops it on purpose.
`worker.js:147` destructures it off the tick result at the single place that
result is formed:

```js
const { value: _discarded, ...wire } = result;
```

and that is deliberate: it implements the lead's 2026-11-10 rule that a
script's top-level return value *ends the tick and reaches no result field*
(`32b592a`, re-affirmed at `6a755d6`). Using the return value for a second
purpose would reverse a standing decision whose commit records four defects
behind it. `api.result(v)` leaves the rule intact and makes "this is my
report" something the script states, rather than something inferred from a
value that already means "the tick is over".

**Shape.** A script that wants to report calls:

```js
api.result({ done: true, say: 'furnace is full', items: 64 });
```

**(a) It costs a host call.** `api.result(v)` counts against the same 8
host calls per tick as `api.do`/`say`/`send`/`recall`/`remember`/`log` — the
budget is shared, so reporting spends a slot an action might have wanted.

**(b) Its value is capped by the same 2 KiB marked cut as the rest of this
section** (`cap_result`, `script_tick.py`; task 3.2). The value is
JSON-serialised, capped at 2 KiB, and marked with a truncation marker when cut
— never dropped, never cut mid-character.

**(c) Last call wins.** If a script calls `api.result` more than once in a
tick, the LAST value is the one kept; earlier calls are overwritten. The
stored value is what goes back to the planner on the next
done/error/escalate trigger, under §3's caps.

**(d) A result raises no trigger on its own.** Calling `api.result` does not
end the tick, does not schedule a planner call, and does not change the
script's loop state. It stores a value. The trigger that wakes the planner is
still only done/error/escalate — so a script that reports and keeps ticking is
reporting into a slot that is read when its script ends, not when it reports.

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
`if not new_messages: return` (`:520`). A script that reaches `done` releases
its binding and says nothing, so **without a new entry point a finished
script's result would go nowhere until a player happened to speak** — which
defeats step c, whose point is that the planner gets the result back.

So step c adds a second entry point beside `_maybe_plan`:
`_maybe_plan_on_result()`. The loop at `:3400-3413` is a 10-second
`_wait_for_idle_or_chat` followed by `_observe`, so this entry is *evaluated*
every pass but *acts* only when there is a pending result for the bot's current
goal. That test is what makes it a result-triggered call and not a per-tick
planner call: with no result pending it returns without calling `call_plan`.
Results fire only on `done`, `error` or `escalate` — never per tick — so the
call frequency is set by how often scripts finish, not by the loop interval.

**The caps are the load-bearing guard.** Because this entry can start a planner
call with no player involved, §3's caps stop being belt and braces and become
the thing that bounds spend: **4 planner calls per bot per hour and a 15-minute
cooldown between result-triggered calls**. A result that arrives while the cap
or cooldown is in force is **queued in the one slot, not discarded** — the caps
delay delivery, they do not silently drop it — and the delay is logged with the
cap that caused it. If the slot already holds a result, rule 2's overwrite
applies.

**Ordering with `_maybe_plan`.** Both entries can want to call `call_plan` on
the same pass. A player message wins: `_maybe_plan` runs first (it is called
before the result check), and a result-triggered call is skipped for that pass
because the player's call will render the pending result anyway (rule 1's
goal check still applies). This keeps one planner call per pass and keeps new
player intent ahead of a stale result.

**What the planner does with the result.** The result is passed into
`call_plan` as context, not as an instruction, and the planner chooses one of
three outcomes: **continue** (the goal is unfinished — write the next script or
step toward the same `goal_id`), **finish** (the goal's stated condition is
met — clear it and say so), or **replace** (the goal is wrong or unachievable as
stated — write a new script or directive **under the same `goal_id`**, with the
reason logged). The planner is told which goal the result belongs to and is not
asked to infer it.

**The planner does not mint goal ids.** `replace` keeps the existing `goal_id`:
a goal id is created only by a player message (`_new_goal_id` stays
player-message only), so a planner that rewrote its own goal would be handing
itself a fresh id and, with it, the ability to slip the per-goal rules. Keeping
the id means the result-keying rule (rule 1) and the discard rule keep working
through a replace, and a replaced goal is still recognisably the same goal to
whoever reads the log.

**The one slot and its eviction rule.** There is one pending result per
`{bot, goal_id}`. A newer result for the same key **overwrites** the older one,
and the overwrite is logged with both results' triggers. A result is
**discarded**, not delivered, when:

- the goal it belongs to is no longer the bot's current goal (a new directive
  arrived) — the discard is logged with both goal ids;
- it has been pending for more than **30 minutes** — older than that, the world
  it describes has moved on and the planner should plan fresh;
- the next planning call is for a different `goal_id` (rule 1).

**When the result arrives while the bot is busy.** Two cases, both explicit:

- **already planning** (a `call_plan` is in flight) — the result goes into the
  one slot and is delivered on the next pass, not mid-call. A planner call is
  never interrupted, and never fed a result it has not asked for.
- **holding a goal** (the bot has a current `goal_id` and is working it) — this
  is the normal case for a script that finished inside a live goal: the result
  matches the current goal, so `_maybe_plan_on_result` renders it on the next
  pass under the caps. If a new directive arrived in the meantime, the goal ids
  differ and rule 3's discard applies instead.

**What is never done:** a result does not interrupt a running script, does not
interrupt an in-flight planner call, and does not queue more than one entry per
key. The caps bound how often a result can start a planner call, and the
discard rules bound how long one can sit before it is stale.

### Bounding the loop

Three caps, each independently sufficient to stop a runaway:

- **Per bot, at most 4 result-driven planner calls per hour.** A result beyond
  the cap is queued in the pending slot, not dropped (rule 2), and the
  suppressed call is logged with the cap named. At ~59 ticks an hour this is
  the difference between 4 planner calls and 59.
- **A cooldown after each result-triggered planner call** — no second
  result-triggered call for the same **bot** within 15 minutes, whatever script
  produced the result. It is per bot, not per script, because a `done: true`
  releases the binding and the next script is a different one; a per-script
  cooldown would bound nothing. This is what stops a planner that keeps
  writing a script whose `done: true` is a bug from re-planning every tick.
- **The script stops on completion.** A `done: true` result releases the
  binding, so there is no next tick to trigger on until the planner writes a
  new script.

**Where the cap and cooldown state lives.** Per **bot**, for the lifetime of the
agent process — two counters and a timestamp next to the other per-bot agent
state, keyed by bot name. It MUST **not** be cleared by `reset()`: `reset()`
(`agent/agent.py:385-400`) clears script hold, conversation history and
orchestration, and a reset is the one moment a bot is most likely to be handed
a fresh goal and run again, so clearing the counters there would hand back the
full hourly budget on demand. Losing the state on process restart is accepted —
it costs at most one extra batch of 4 — because the alternative is persisting a
rate counter, which is more machinery than the bound is worth. A test MUST fail
if `reset()` clears it.

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
