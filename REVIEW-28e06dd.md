# Review: 28e06dd (M3-1g, correcting my own bb59d8f review)

Rev reviewed: `28e06dd`, read from `ship-ca27-harness` **via `git show 28e06dd:...`,
not from my worktree**. That distinction is the whole story below.

`openspec validate coded-agents --strict`: valid.

**Verdict: PASS on 28e06dd's spec text, with one residual wording risk (R1) and
one process correction owed to the builder (P1).**

---

## P1 (my error, stated plainly): I reviewed a branch my worktree was not on

The builder rejected B1 and B1's memory half, and **they were right on both**.

- `agent.py:530` at `28e06dd` **is** `if chat_filter.is_pure_pleasantry(text, self.name):`
- `agent.py:534` at `28e06dd` **is** `from_bot = sender in _all_runners`
- `script_tick.py:363-364` at `28e06dd` **does** assign `self._memory = result.memory`

Cause: my worktree `minecraft-wt-qwen` sat at `ae2fb43`. That commit is **not an
ancestor** of `ship-ca27-harness`; the two share only `d75f30bc`, and
`agent/agent.py` differs by 253 lines because my branch never took M3-1b/1c/1e.
The line numbers I read were 25 lines lower — a **uniform** offset (`514→539`,
`573→598`, `617→642` in `_following_player` alone), which is exactly what a
missing insertion looks like, and exactly what I should have checked before
calling three citations wrong.

Two instruments were at fault, not one:

1. **I never verified my tree held the rev.** My own note
   `validate-in-the-worktree-that-holds-the-rev` exists for this, and I applied
   it to `openspec validate` but not to `sed`.
2. **`grep memory_out agent/` could not see the field.** The production field is
   `_memory`, in `script_tick.py`. A grep that cannot match the real identifier
   returns 0 and reads as absence. Note `verify-the-instrument-before-trusting-a-zero`
   covers this too.

Their proof beat my reading, as it should: `MemoryRoundTripTest`, 5 tests OK, is
a better instrument than a grep I chose badly.

**This does not change the branch positions as a fact.** My worktree is still 25
commits behind on `agent.py`; I have not fast-forwarded it in this session. Any
further review I do must read via `git show <rev>:`, and I will say so.

## B1b survives, and they fixed it

The follow gate was real in both trees (it is the same code, offset). At
`28e06dd` the gates resolve exactly as cited:

| cited | actual |
|---|---|
| `AIPlayerMod.java:272` | `if (!sender.equals(bot.getPlayer().getName().getString())) {` |
| `agent.py:530` | `if chat_filter.is_pure_pleasantry(text, self.name):` |
| `agent.py:534` | `from_bot = sender in _all_runners` |
| `agent.py:539`, `:598`, `:642` | `not self._following_player` gates |

The four-gate table plus "Any change to those four gates MUST either leave this
set unchanged or modify this requirement in the same change" is the wording I
asked for and it does the job: the set is now testable and the obligation is
explicit. **Loophole closed.**

## N2, #5, #6: accepted and correctly implemented

- The hold is now constrained by **object identity** ("the object that resumes
  MUST be the object that was held"), which is testable; the unsatisfiable
  "MUST NOT be a fallback" is gone.
- Scenarios 1, 2 and 4 carry control runs and a non-null precondition, so
  "no action" and "memory intact" are attributable rather than vacuous.
- The cancelled-goal case is split out with its own requirement paragraph and
  scenario.

---

## R1 (residual, non-blocking): "remains held" may be unimplementable as stated

The new requirement says:

> A cancellation caused by chat that did not itself yield a goal MUST leave the
> script held, not resume it.

and the scenario asserts `THEN the script remains held`.

Two facts at `28e06dd` matter here, and neither is a citation error:

1. The cancel returns `{"success": False, "reason": "interrupted_by_chat"}`
   (`agent.py:2197`), and the L1 caller consumes it at `:2108` / `:2965`.
2. The **script's own** dispatch loop treats that same string as a reason to
   `return True` (`agent.py:2804`), i.e. "the script handled this tick".

So `interrupted_by_chat` currently has two opposite meanings depending on which
caller sees it. The requirement is asking for a third outcome — "held, and not
the script's tick" — which is neither `True` nor `False` in the existing
vocabulary, and `_run_script_tick` returns a bare `bool`.

I am **not** asking for a design in the spec. I am flagging that "remains held"
reads as a state the current return type cannot express, and the implementer
will have to invent one. That is fine — but the spec should say the hold is a
state the script-tick call must be able to report, otherwise the first
implementer will express "held" as `return False` (the fallback the requirement
elsewhere forbids) because it is the only falsy value available. That is
precisely the collapse N2 was about, one layer down.

Suggested minimal addition, no design imposed:

> The hold MUST be expressible as a distinct outcome of the script-tick call,
> distinguishable by the caller both from "the script handled this tick" and
> from "the script did not run". The script MUST NOT be resumed, and the planner
> MUST NOT be dispatched, on a tick that is held for a goal.

## N1: the one-sentence addition is enough

I asked what to do beyond "alternatives". Their added parenthetical —

> (The two are not even sequential alternatives at the call site: `_maybe_plan`
> runs before `_run_script_tick` every iteration, so without this requirement
> both run each pass.)

— is verified at `28e06dd` (`:2931` then `:2939`) and states the mechanism
accurately. The surrounding sentence still says the earlier requirements treat
them as alternatives, which is true *of the earlier requirements* even though it
is not true of the loop. **No further change wanted.** My N1 asked for the
mechanism to be visible; it now is.

---

## Required before PASS

Nothing blocking. **R1 is a non-blocking recommendation** and I would accept the
spec as-is if the builder prefers to resolve `interrupted_by_chat`'s triple
meaning in the implementation task instead.

## What I checked and am not disputing

- Owner option 1 represented faithfully; the fifth not-active case is right.
- All four gate citations resolve to the cited statements at `28e06dd`.
- `openspec validate --strict` valid.
- `28e06dd` is two files; the 378-line trajectory is gone from it.
- No code, no cluster action, nothing applied or pushed.
