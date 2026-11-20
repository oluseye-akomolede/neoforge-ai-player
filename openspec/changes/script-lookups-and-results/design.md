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
| `nearby.blocks` | `api.blocks(bot, 8)` line 73 | radius 8, list |
| `nearby.mobs` | `api.entities(bot, 24.0)` line 74 | radius 24, list |
| `task` | directive line 76 | object or null |

Wrapped by `build_envelope` (`snapshot.py:80-100`) with `tick`, `server_ms`,
`events`, and sent as the tick request's `snapshot` key
(`agent/script_tick.py:419`).

**The runner installs it as a read-only global** named `snapshot`
(`src/engine.js:738-748`), separate from `api`.

**Only six host functions exist** (`src/binding.js:230-330`): `do`, `say`,
`send`, `recall`, `remember`, `log`.

**The host-call budget is 8 per tick and it is shared**
(`src/binding.js:31-32` `MAX_HOST_CALLS`, counted in `accept()` at
`:138-145`). `do`, `say` and `send` each spend from it. A lookup that spends a
host call is spending a slot that a game action wanted.

**The CPU budget is 250 ms of measured CPU per tick**
(`src/engine.js:62` `TICK_CPU_MS`), measured with QuickJS's interrupt handler
(`:65-102`) and checked every 64 calls (`:88`). It is CPU, not wall time.

**What is NOT established:** whether the snapshot's radius-8 blocks and
radius-24 mobs are wide enough for the lookups the planner actually wanted. I
have not read the planner's last scripts to find out; §1 lists the lookups the
task named and says which the current fields already answer.

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
agent already put in the snapshot. Anything outside radius 8 (blocks) or 24
(mobs), or anything not in the six fields, is unanswerable — and a lookup that
silently returns empty for data that was never sent is the failure mode to
guard against (§2).

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

| Lookup | Needs | Answered today? |
|---|---|---|
| sheep nearby | `nearby.mobs` filtered by type, with distance | **Yes**, radius 24; distance must be computed from positions |
| flower of a colour | block id + position, radius-wide | **Partly** — `nearby.blocks` is radius 8 and its fields are not listed in the source I read; colour is a block-id property the lookup can parse if the id is present |
| inventory contents / count of an item | `inventory` | **Yes** |
| position | `position` | **Yes** |
| nearest block of a kind | `nearby.blocks` filtered | **Partly** — only within radius 8 |

**The agent can already answer some of these live, just not inside the sandbox.**
`agent/api.py:110-115` has `find_blocks(bot, block, radius=32)` and
`block_at`, both reachable from a planner step but not from a script. So the
radius-8 gap is not a missing capability — it is a capability the script path
cannot reach. That is the strongest argument for Option A being a *sandbox*
question and not an *agent* one, and it dates any Option B revival: if the
planner's scripts need `find_blocks`, the cheaper first move is to grow the
snapshot from a call the agent already makes, not to give the sandbox a
callback.

**Recommendation:** ship Option A, and make the snapshot's insufficiency
explicit in two ways — `look` reports what radius it searched, and an
out-of-range query returns a distinguishable "not searched that far" rather
than an empty list that reads as "nothing there". If the planner's scripts show
a recurring need beyond radius 8, that is a snapshot-size decision (§5), not a
reason to adopt Option B.

---

## §2 Read-only guarantee

The guarantee is structural, not a policy the lookup code agrees to follow.

**How a lookup provably cannot act.** `look` has no reference to `api`. It is
built from the snapshot literal and closes over nothing else. It cannot call
`api.do`, because `api` is not in its scope; it cannot spend a host call,
because `accept()` (`binding.js:138-145`) is only reachable through `api`'s
methods; and it cannot reach the network or the mod, because QuickJS in this
runner exposes no I/O and the only path to the agent is the tick response.

**How it cannot write.** The snapshot is installed read-only
(`engine.js:738-748`). A lookup returns new objects derived from it; it never
returns a live reference the script could mutate back into the shared literal.
**Design decision:** `look` results are deep copies, not views. A script that
mutates a returned array must not affect the next lookup in the same tick.

**How it cannot reach a secret.** The snapshot is built from six
`api` reads (`snapshot.py:68-76`) — health, food, position, inventory, blocks,
entities. It carries no token, no game id, no environment. A lookup over it can
therefore only return data the game already handed the bot. This is the reason
the snapshot is the right substrate and a live read is not: a live read would
put the agent's own request path within a script's reach.

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

### How the planner reads it

**The next planning call's context**, not a new turn. When a result is
delivered, the agent stores it as a pending observation; the next `call_plan`
renders it into the prompt as "your script returned: …". No extra LLM call is
made — the planner sees the result exactly when it next plans, which is when a
script has stopped and the planner is needed again.

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
- A lookup outside the snapshot's data (Option B). If the trial shows a
  recurring need beyond radius 8, growing the snapshot is a separate decision
  with its own cost (tick payload size).
- Delivering logs or actions to the planner.
- Changing the `done`/`escalate` vocabulary into anything richer (a typed
  report schema) before a trial shows the simple object is not enough.
- The chat-pauses-script rule (M3-1g) and the dry gate's semantics, both
  unchanged.
- Archiving `ai-written-scripts`. This change is separate and lands on its own.
