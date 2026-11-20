# Re-review: script lookups (b) and script results (c) — `682b092`

**Rev:** `682b092` (supersedes `0b76d5c`; commits `3e82ce6` then `682b092`, both on `5594bfa`)
**Prior:** `0b76d5c` REVISE BEFORE CODE (review `371095c`), F1–F6
**Requested by:** `minecraft-lead` by `rig send` 22:54Z. No queue row.
**Verdict:** **PASS ON F1–F6, ONE BLOCKING SPEC SCENARIO.** Every finding from
`371095c` is closed and closed correctly. The lead's result-scheduler change
answers my F4 and is structurally sound. But the scenario written to prove the
loop bound cannot fire, and the dedup removal that F2 forced is not costed.

---

## F1–F6 closure

| # | Finding | Status |
|---|---|---|
| F1 | radii 8/24 in the design are not what the bot gets (5/16) | **CLOSED** |
| F2 | block/mob shapes; "flower of a colour" wrongly *Partly* | **CLOSED** |
| F3 | lookup demand never actually established | **CLOSED** |
| F4 | result has no scheduler | **CLOSED** by the lead's `682b092` |
| F5 | snapshot staleness not surfaced | **CLOSED** (`look.age_ms()`) |
| F6 | archived-spec status | **RECORDED** (no archive exists; noted in §5) |

**F1 verified:** `design.md:18-19` now reads "radius 5 in practice" / "radius 16
in practice", `:33-34` gives the Java these come from, `:37` states everything
below uses 5 and 16. The only surviving `8` and `24` are the request arguments
(`api.blocks(bot, 8)`) and the cost-comparison cube counts — both correct usage.
`proposal.md` and task 1.3 carry 5/16. Good.

**F2 verified against the Java itself** (`BotPlayer.java:890-917`): blocks are
`{"block": getName().getString(), "position": ...}` guarded by
`seen.add(blockName)` at `:906` — display name, deduplicated, exactly as the
design now says. Mobs carry `distance` via `String.format("%.1f", ...)` at
`:886`. `design.md:128` now reads **"No. Neither the cache nor the snapshot
carries block state, and colour cannot be recovered from a display name"** —
the correction is complete and not hedged.

**F3 verified:** §1 item 1 (ids + no dedup) and item 3 (no host-call lookup;
tasks 1.4 added to count real demand) is the reordering I asked for, applied
cleanly. `design.md:75` still honestly lists radius sufficiency as NOT
established, which is now the right scope of honesty — it is a §5 measurement,
not a design assumption.

**F5 verified:** `look.age_ms()` plus per-result `age_ms` from `server_ms`, with
the dry-tick note at `agent/script_tick.py:419`/`:425-426`. Closed.

**F6 verified:** §5 records that no archived `bot-coded-agents` spec exists and
that it stays unarchived across four changes. Recorded, not fixed — correct, it
is not this change's job.

---

## F4 — the lead's scheduler: sound, and it answers my question

`682b092` overturns "delivered on the next player message, or not at all". That
was my F4's problem, and overturning it is right: the owner's step c *is* that a
result reaches the planner, and a rule that delivers it only if someone happens
to talk does not satisfy that.

Checked against the real loop (`agent/agent.py:3400-3413`), not the design's
account of it:

- **The loop is `_wait_for_idle_or_chat(10)` → `_observe()` → `_maybe_plan`,**
  and `_maybe_plan` returns immediately on `if not new_messages`
  (`agent.py:520`). Adding `_maybe_plan_on_result()` beside it, acting only when
  a pending result exists **for the current goal**, genuinely cannot call the
  planner per pass: with no result pending it returns before `call_plan`.
  **Question (1), first half: confirmed — no per-tick or per-pass call without a
  pending result.**
- **Question (1), second half — can bind/release cycling bypass the cap?** This
  is the real risk in the design, and it is **answered by the design's own
  choice**: the 15-minute cooldown is now **per bot, not per script**
  (`design.md:370-378`), which is exactly the fix for a `done` script being
  replaced by a fresh one every tick. A per-script cooldown would have bounded
  nothing. The per-bot 4/hour cap is likewise not resettable by rebinding.
  **Provided the cap state is per-bot state that survives `_bind_planner_script`
  and `_end_script_hold`** — which the design asserts but does not say where it
  lives. See N-1 below.
- **Question (2), burst:** a queued over-cap result is delivered on the next
  pass, and the cooldown admits at most one result-triggered call per 15
  minutes per bot, so queued results cannot fire in a burst — they drain at the
  cooldown rate. The one-slot-per-`{bot, goal_id}` overwrite means a backlog
  cannot grow.
- **Question (2), wrong goal:** a result carries `{bot, goal_id}` and is only
  rendered into a `call_plan` for that same `goal_id` (`design.md:283-286`);
  a different current goal discards it with both ids logged. This closes the
  per-bot-bindings hazard I raised in F4. Confirmed sound.

**Where the goal id comes from is the one gap.** `_goal_id` is minted only from
a player message — `_new_goal_id(sender, text)` at `agent.py:711` and `:914`,
called from the two chat-goal paths. The design says the planner may **replace**
a goal and "write a new script or directive for a new `goal_id`"
(`design.md:334-338`). Nothing in the current code mints a goal id for a
planner-chosen goal. Either the design means the new goal reuses the existing
`_goal_id` (in which case say so — a replaced goal keeps its id and the result
key is stable), or step c needs a new minting path, which is agent code this
design says is out of scope. As written, "replace" has no id to key on.

---

## F7 (BLOCKING) — the loop-bound scenario cannot fail

`spec.md:76-79`:

> GIVEN a script that returns `done: true` on every tick
> WHEN it runs for **ten ticks** inside one hour
> THEN at most 4 results MUST reach the planner

The same design states, at `:379`, that **"a `done: true` result releases the
binding, so there is no next tick"**. A `done`-every-tick script therefore runs
**once**, not ten times — the GIVEN contradicts a rule the document establishes
two sections later, and the WHEN (ten ticks) is unreachable. The scenario can
never produce the eight-plus results it needs to test the cap against, so it
passes whether the cap exists or not.

This is the exact failure mode this path has been reviewed against repeatedly:
a scenario whose fixture shape makes it inert. It matters most here because the
cap is, in the lead's own words, "the load-bearing guard".

**Fix:** make the GIVEN produce many results without relying on a script that
keeps ticking. Two shapes work:

- N **distinct scripts** each returning `done: true` once, driven back to back
  within one hour — this is the bind/release cycling case Q1 asked about, and it
  is the more valuable test because it also proves the cooldown is per-bot.
- or the 10-tick premise kept, but with a script that **does not** `done` every
  tick — e.g. returns `escalate: true` on each of ten ticks from a *held* goal —
  which is reachable because escalate does not release the binding.

I'd take the first: it is the bypass shape, and the design's per-bot cooldown
exists precisely to stop it.

---

## F8 — the dedup removal is required but uncosted

§1 item 1 makes "add real ids and **drop the dedup**" mandatory. §5 costs the
radius *widening* in detail (cubic cell counts, 1331→4913→35937) but says
nothing about dedup removal, which is the other half of item 1.

Measured against the real builder (`BotPlayer.java:893-917`): without `seen`,
every non-air block in the 11³ radius-5 cube produces an entry. In ordinary
terrain that is roughly 600–1000 entries of ~50 bytes — a **30–54 KiB** block
array, up from **~1–3 KiB** today (tens of distinct names). That is a 20–40×
growth in the per-tick snapshot payload, sent to the agent every tick on the
same wire that carries everything else.

Radius stays 5, so the *scan* cost is unchanged — the design is right about
that. What changes is the **serialised payload**, which is what crosses to the
agent, and it is the larger number by far. This should be stated in §5 beside
the cube arithmetic, as a measured payload figure, because it is the cost that
actually bites and it is not the one currently written down.

Not blocking the design decision — dropping dedup is the right call for
correctness — but the cost table is currently truthful about the cheap change
and silent about the expensive one, which reads as if the cheap one were free.

---

## Q4 (spec scenarios can fail) — the rest are sound

Besides F7, I checked the falsifiable ones:

- "a lookup beyond the snapshot says so" — fails if the lookup returns `[]`
  (must report the radius searched). Real.
- "a lookup result is a copy" — fails if the mutant returns the snapshot's own
  array. Real, and §4 names the mutant.
- "a lookup cannot act" — fails if `hostCalls` changes or `api` is reachable.
  Real, and measurable.
- "the planner reads a result without an extra call" — fails if a second
  `call_plan` occurs. Real.
- "a result is only read by the goal that produced it" — fails if rendered under
  a different `goal_id`. Real.
- "a finished script's result reaches the planner with no player" — this is the
  scenario that would have caught my F4, and it fails if delivery depends on a
  player message. **Real and well-chosen.**
- "a result has a size cap" — fails if dropped instead of truncated. Real.

---

## N-1 (non-blocking) — where the cap and cooldown state lives is unstated

The design asserts the caps survive rebinding but does not say what holds them.
`reset()` (`agent.py:385-400`) clears the script hold and the conversation; a
new cap counter is new state whose lifetime is a decision. State it: per-bot,
process lifetime, **not** cleared by `reset()` or `_clear_script_hold` (or say
if it *is* cleared by `reset()`, which a player can trigger — that would be a
bypass). This is the one place Q1's answer depends on an implementation choice
the design leaves open.

## N-2 (non-blocking) — 2 KiB result cap is a guess, stated as one

`design.md:270` says so itself ("a proposal, not a measurement"). Fine; §4
measures it. No action.

---

## Citation check

All design citations I re-checked resolve: `HttpApiServer.java:504-505`,
`BotPlayer.java:886`, `:906`, `:893-917`, `agent/snapshot.py:49-77`, `:68-76`,
`agent/agent.py:518`, `:520`, `:711`, `:914`, `:3400-3413`,
`agent/script_tick.py:419`, `:425-426`, `binding.js:138-147`. The
`engine.js:738-748` drift from `371095c` is corrected to `:752`/`:771-778`.

`openspec validate script-lookups-and-results --strict` → **rc=0**.

---

## Verdict

**The design is ready to build once F7 is fixed.** F7 is a one-scenario change
and I would not hold the design on it past the next rev; F8 is a paragraph in §5
and should go in the same edit because §1 and §5 currently disagree about what
is being costed. N-1 is an implementation note to carry into task 3.x.

The result scheduler the lead wrote is the right correction and it closes F4 for
the right reason — the owner asked for the result to reach the planner, and a
rule that dropped it unless someone spoke did not deliver that.

Nothing built, pushed, deployed or run against `ollama-l3`; no pod exec; nothing
in `ci`.
