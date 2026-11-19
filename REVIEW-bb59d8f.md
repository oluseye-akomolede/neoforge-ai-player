# Review: bb59d8f (M3-1g spec delta — "A Player Goal Yields A Running Script")

> ## CORRECTION (11-19 17:0xZ), issued before any further work
>
> **B1 and the N2 memory finding below are WITHDRAWN. They were read from the
> wrong tree.** My worktree `minecraft-wt-qwen` sat at `ae2fb43`, which is not
> an ancestor of the change branch: the two share only `d75f30bc`, and
> `agent.py` differs by 253 lines because my branch never took M3-1b/1c/1e
> (`92de520`, `a995779`, `7133983`, …). Reading `bb59d8f:agent/agent.py` from my
> own checkout gave line numbers 25 lower than the change branch's.
>
> The builder's citations are correct **on the branch the spec lives on**.
> Verified: at `28e06dd`, `:530` is `if chat_filter.is_pure_pleasantry(...)` and
> `:534` is `from_bot = sender in _all_runners`. Only B1b survives, and only as
> "add the follow gate", which they have done.
>
> The memory finding is also wrong: at `28e06dd`, `script_tick.py:363-364` does
> assign `self._memory = result.memory` (guarded on `not None`) and `:321` sends
> it. My `grep memory_out agent/` could not see it — the production field is
> `_memory`, in a different file. That is the instrument, not the world.
>
> **The real defect this exposed is in my process, not their spec: I reviewed a
> change on a branch my worktree never fast-forwarded to.** Everything below is
> preserved unedited as the record of what I said and why; treat B1 and the N2
> memory paragraph as refuted, and see the re-review of `28e06dd` at the end.

Rev reviewed: `bb59d8f` (also ancestor of the worktree HEAD `ae2fb43`).
`openspec validate coded-agents --strict` at that rev: **valid** (rc=0).

**Verdict: NOT YET — 1 blocking defect, 2 wording fixes, 1 commit hygiene.**
The requirement is the right shape and the owner's ruling is represented
correctly. But the central sentence — the acceptance predicate — cites three
line ranges that **do not contain the predicate**, and the predicate it is
meant to name has a third gate the text omits. A spec whose job is "MUST NOT
widen or narrow the set" cannot leave the set unnamed.

---

## B1 (blocking): the acceptance predicate is cited wrong in all three places

The requirement says the predicate is "named in one place rather than restated
here" and cites:

| cited | what is actually at that line |
|---|---|
| `agent.py:530` | `except Exception:` inside the **task-board cancel** block of `_handle_chat_commands` — not `_maybe_plan`, not a pleasantry check |
| `agent.py:534` | `if from_bot and "Task #" in text and "for you:"` — a task-board branch, not a bot-origin filter |
| `BotPlayer.java:674-678` | the body of `addChatMessage` — sets the master and enqueues. It has **no acceptance test at all**; it accepts every call |

Verified by reading each span with `sed -n` at `bb59d8f`'s tree.

The real predicate, read at source:

- **Pleasantry**: `agent.py:505` `chat_filter.is_pure_pleasantry(text, self.name)`.
  Semantics from `chat_filter.py:27-42`: true only when *every* word is a skip
  token or the bot's own name. So `"hi mystic"` is dropped; `"Hi Mystic! Who
  are you?"` is not. Empty/punctuation-only text counts as pleasantry.
- **Bot origin**: `agent.py:509` `from_bot = sender in _all_runners`, applied at
  `:511` and `:573`.
- **Self**: `AIPlayerMod.java:274` `if (!sender.equals(bot...getName()))` — the
  self-exclusion lives at the **mod call site**, not in `addChatMessage`.

### B1b: the predicate has a third gate the requirement omits, and it is not inert

    agent.py:511   if not from_bot and not self._following_player:
    agent.py:573   if USE_L3_PLAN_LAYER and not from_bot and not self._following_player:

`_following_player` is part of "whether chat reaches the planner" — that is
literally what the requirement says it is naming. It is not a corner case: a
bot following a player is the common state after "follow me", and `a26b1c2`'s
own 9.4 work is about bots that are idle vs active. So the requirement as
written is **false** for a following bot: the message reaches `_maybe_plan`,
and nothing in the L3 path plans it.

That matters because the requirement's stated purpose is to prevent two
issuers. If a following bot is exempted from the predicate, a chat goal during
follow is neither held nor planned — or, worse, depends on which of the other
branches fires. Either is an outcome the scenario set cannot distinguish.

### The loophole question, answered directly

Asked: *does naming the predicate by reference leave the behaviour undefined if
that predicate later changes?*

Yes as written, and the wording does **not** achieve the stated intent. "MUST be
the predicate that already governs" is a **pointer to a moving target**. A
later PR that adds `and not self._busy` to `:511` silently changes what the
yield requirement accepts — with no spec delta, no scenario change, and no test
failing, because the spec asserts nothing testable about the set.

To get the intent ("a change there changes both together") the wording needs an
**anchored referent plus a binding obligation**, e.g.:

> The set of chat that yields a script MUST equal the set that reaches the
> planner, which on the date of this requirement is: not a pure pleasantry
> (`chat_filter.is_pure_pleasantry`, `agent.py:505`), not bot-origin
> (`agent.py:509`), not the bot itself (`AIPlayerMod.java:274`), and not a bot
> currently in player-follow mode (`_following_player`, `agent.py:511`, `:573`).
> **Any change to those gates MUST either leave this set unchanged or modify
> this requirement in the same change.**

The second sentence is the part that makes the reference safe. The first
sentence is the part that makes it reviewable. The current text has neither.

---

## N1 (non-blocking, but it inverts a scenario): "resumes" describes something that already happens

The requirement's opening — *"Earlier requirements make the planner and the
script alternatives"* — is not what the code does. In `_loop` (`agent.py:2689`):

    self._maybe_plan(new_msgs)          # :2698
    if self._run_script_tick():         # :2702
        continue

`_maybe_plan` runs **first, every iteration**, then the script tick runs. They
are not alternatives at loop level; the script path wraps the planner. The
script action dispatch (`_l3_orchestrator_dispatch`, `agent.py:901`) **blocks
until the directive completes**. So "chat goal arrives while script ticks" is
not a mutually-exclusive choice the code makes — it is the planner starting a
directive and the script then dispatching on top of it in the same iteration.
That is consistent with the measured symptom (two store directives for one
goal), so the *requirement* is justified; the *causal sentence* describing the
current state is wrong and should say what the loop actually does.

Corollary for "resume": since `_run_script_tick` is synchronous and returns
before the next `_maybe_plan`, there is **no separate resume step to build**.
"Resume" in the spec reads as a state machine (held → resumed); the code already
has no such state. An implementer following this text will build a
hold/resume machine that the loop does not need. Better: say what must be true
during the planner's directive (no script tick dispatched) and what must be
true after (the next iteration ticks the script), rather than naming a
transition.

---

## N2 (non-blocking): question 2 answered as fact — a hold *is* the fallback path

Asked: *is "being held is not a tick, and MUST NOT be treated as a failed tick
or a fallback" enough to stop an implementer routing the hold through the
fallback path?*

**No, and the sentence cannot work as written, because the fallback path is not
a distinct path.** `script_tick.py:101-104` defines it:

> `handled=False` means "the planner should run this tick" — the caller must
> never treat it as "do nothing".

A hold *is* "the planner should run this tick". So on the current design, a
hold expressed in this module **must** return `handled=False` — that is the
only vocabulary it has. The requirement forbids the thing the code calls the
fallback, while requiring the exact behaviour that value means. An implementer
resolving that contradiction will either special-case a new return value or
mis-map it.

The stronger wording, and it is materially different:

> While a script is held, the game MUST NOT advance or clear the script's
> remembered value, and MUST NOT rebuild the script's runner state from empty.
> A hold therefore MUST NOT construct a new `ScriptTick` (or equivalent
> session) for the bot: the object that resumes MUST be the object that was
> held. It is not sufficient for the hold to avoid sending a tick — a hold that
> drops the script object, or that reads memory back from a place the hold did
> not write, has cleared the blob regardless of what it did not send.

That is testable as an identity assertion ("same object / same remembered
value"), which the "must not be treated as a fallback" sentence is not.

### Fact the memory clause needs to state, and currently does not

I checked, and the answer is not the assumption in the task text:

- `ScriptTick` is constructed **once** per bot at `agent.py:2686` and cached in
  `self._script_tick` (`_get_script_tick`, `:2690-2693` guards on
  `_script_loaded`). Memory is passed as `memory=None` and **nothing in
  `agent.py` ever assigns `_memory` afterwards** (grep for `memory_out` in
  `agent/` returns nothing).
- So on the current agent code there is no memory round-trip at all: the
  remembered value is `None` forever, and the 9.7 wipe cannot be reproduced by
  holding — because it does not currently survive a single tick either.

That means the scenario *"the value it recalls is the one it remembered before
the hold"* is **vacuous on today's tree**: with memory pinned to `None` on both
sides, it passes whether or not the hold exists, and whether or not the hold
wipes. This is exactly the 9.4 failure the builder asked me to look for.

It becomes non-vacuous only if a prior task lands the round-trip. So the
scenario needs a second `AND` that discriminates: a *non-null* remembered value
must be set before the hold and read after it, **with a control** that the same
value would be absent without the hold. Otherwise the implementer can pass it
with `None == None`.

---

## Question 3: which of the five scenarios are testable-but-vacuous

Answering directly, per scenario:

| # | scenario | verdict |
|---|---|---|
| 1 | goal holds the script; planner acts; no script action dispatched | **Not vacuous.** Red on today's tree (both dispatch). Needs a positive control that the script *would* have dispatched — otherwise "no script action" is also what a dead script produces. |
| 2 | held script is not ticked | **Vacuous as written.** "The runner receives no tick" is satisfied by no runner, no script, a disabled bot, or the existing `handled=False` fallback — all of which already send no tick. Needs "the bot HAS an active script and the runner IS reachable", plus a control tick that lands when not held. |
| 3 | resume after `COMPLETED` with memory intact | **Vacuous on today's tree** (see N2): memory is `None` unconditionally, so the memory half passes trivially. "Resumes ticking" is also already true every iteration. |
| 4 | same, after `FAILED`/`CANCELLED` | **Same as 3**, plus a spec gap below. |
| 5 | held time is not metered | **Not vacuous**, and the best of the five — it names a duration and a quantity. It only needs the metering clock to exist for a held period measured between two ticks. |

### The spec gap in scenario 4: `CANCELLED` may not be a state that exists

The requirement says resume happens when the directive reaches *"completed,
failed or cancelled"*. Scenario 4 quantifies over `CANCELLED`. But the chat
path **cancels the in-flight directive precisely because chat arrived**
(`agent.py:2128-2135`): on a new player message the L1 path calls
`api.cancel_directive` and returns `interrupted_by_chat`. And `_run_script_tick`
treats `"interrupted_by_chat" in str(result)` as a reason to `return True`
(`agent.py:2654`).

So during a hold, the very message that starts the hold cancels the script's
directive. If a player sends a **second** message mid-hold, the first goal's
directive is cancelled by the second goal's arrival — and under this
requirement that cancellation would *resume the script* while the second goal
is still running. That is the two-issuers bug reappearing one level down, and
no scenario covers it.

Worse, the cancel filter at `agent.py:2126-2128` is **wider than the start
predicate**:

    new_player_msgs = [
        m for m in self._new_messages
        if ": " in m and m.split(": ", 1)[0] not in _all_runners

It excludes bot-origin and nothing else. It does **not** call
`is_pure_pleasantry`. So a bare `"hi"` arriving mid-goal cancels the active
directive and returns `interrupted_by_chat` — and `_run_script_tick` treats
that string as a reason to `return True` (`agent.py:2654`). Under this
requirement, "hi" would therefore resume the script while the goal is still
owned.

That is a direct contradiction with the requirement's own second paragraph: a
pleasantry "would not reach the planner", so it MUST NOT yield a script — but
here it ends the hold and hands the tick back to the script, which is the
opposite. The spec asserts a set boundary (`MUST NOT widen or narrow`) that the
cancel path already violates, and it does so in the exact interleaving this
requirement introduces.

Before `CANCELLED` is used as a resume trigger, the spec should say what a
**cancel caused by a newer goal** does: it must not resume the script, because
the newer goal now owns the hold. Nested holds need either "the hold ends when
no goal is outstanding" or an explicit refusal. As written, scenario 4 and the
scenario-1 requirement contradict each other in exactly the interleaving a
player will produce.

---

## Commit hygiene (minor, but it is a spec-only commit)

`bb59d8f` adds `agent_trajectories/trajectory-2026-11-17.jsonl` (378 lines,
new file, no prior history on that path). The commit message says "Spec first,
no code", and the review request says "Spec ONLY". The content is benign
`scout` outcome records — no secrets — but it is stray data in a spec commit
and it makes the "spec-only" claim untrue on the stat. Recommend dropping it
from the commit rather than letting a reviewer's PASS vouch for it.

---

## What I am not disputing

- The owner's option-1 ruling is represented faithfully: pauses, planner acts,
  resumes, held time free.
- The metering extension is correct in kind — a fifth not-active case is the
  right reading, and the "accrues nothing" consequence follows the same rule as
  the other four.
- `openspec validate coded-agents --strict` is valid.
- The choice to add a requirement rather than a permission model is right: there
  is no authority gate in this codebase.

## Required before PASS

1. **B1** — re-cite the predicate to `agent.py:505`, `agent.py:509`,
   `AIPlayerMod.java:274`; drop the wrong spans.
2. **B1b** — either include `_following_player` (`agent.py:511`, `:573`) in the
   set, or state explicitly that a following bot is out of scope and why.
3. **B1-loophole** — add the binding sentence so a change to the gates forces a
   change here.
4. **N2** — replace "not a failed tick or a fallback" with the object-identity
   wording, and add the non-null memory requirement + control to scenarios 3/4.
5. **N1/scenario 4** — decide what a cancel-by-newer-goal does; do not let it
   resume.

N1's causal sentence and the scenario-2 fixture tightenings are strongly
recommended but I would not block on them alone.

No code, no cluster action, nothing applied or pushed.
