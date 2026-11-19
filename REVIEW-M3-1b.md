# Review: M3-1b — 2b52ef1 (cause B), 92de520 (cause A), 7de8c76 (tasks)

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-19
Row: qitem-20261119130645-8da37565c4465e50
Under review: 2b52ef1, 92de520, 7de8c76 on ship-ca27-harness

## Verdict

**PASS on all three.** Both causes are correctly diagnosed and correctly fixed;
the producer-side answer to the lead's question (a) **holds at source** and is
the answer the lead needs for 9.4.

One citation is wrong in the task text (not just the message) and should be
corrected before 9.4 is argued from it. Two observations, neither blocking.

## What I reproduced

| claim | builder | mine |
|---|---|---|
| suite at 7de8c76 | 56/56 | **56/56 OK** |
| mirror sha | c55b704d, 10410 bytes | **identical, byte-equal** |
| cause A mutant (carry removed) | 2 red | **2 red** |
| cause B mutant (log removed) | 3 of 4 red | **3 red**, 4th stays green |

Mutant anchors asserted at exactly 1 before mutating, on the real code lines.

## Cause A — the memory round-trip

The diagnosis is right and I verified the mechanism at source rather than
accepting it:

- `worker.js:81-82` base64-encodes `memory_out` on the way back;
  `engine.js:1059` `decodeMemory` base64-decodes on the way in. **Both cited
  lines are exact.**
- So a value taken from `memory_out` is already encoded and must be sent back
  verbatim, while a caller-supplied string must be encoded once. The code does
  exactly that: the constructor runs `_encode_memory`, and `:337` assigns
  `self._memory = result.memory` **without** re-encoding. No double-encode on
  either path — this is the bug that would have hidden inside a "fix" that
  looked symmetric.
- Fallback carries `memory=None` and `:323-325` returns before `:337`, so a
  timeout cannot wipe a good blob. The mutant proves this separately from the
  carry: removing `:337` reddens *both* the verbatim test and the
  don't-wipe test.

**Lifetime claim verified structurally.** `ScriptTick` is constructed once, at
`agent.py:2819`, on `self._script_tick` — a per-agent instance whose lifetime is
the agent process, the same lifetime `self._tick` has (`snapshot.py:135-136`).
So a cooldown stamp cannot meet a tick counter from a previous process. The
claim is true for the reason given, not by coincidence.

**The new test is the real path, which was the actual defect in 9.1.** The stub
plays the *runner* (it returns `memory_out`), and the test reads `bodies[1]` —
what the second real request carried. It does not hand-feed the value into the
request. That is precisely the fixture-not-from-the-producer gap the builder
self-flagged, and it is now closed in the right place.

## Cause B — the silent hold

The fix logs the phase while leaving the gate's decision untouched, and the
builder is right that this is the correct split: holding on an unreadable
directive is the safe direction, and the silence was the bug.

Mutant confirmed at 3 red: `test_busy_tick_logs_the_phase_it_saw`,
`test_completed_plan_still_logs_and_holds`,
`test_unreadable_directive_is_distinguished_from_a_known_phase`. The fourth
stays green under the mutant, which is what an over-firing guard should do.

## The lead's question (a) — confirmed independently

The claim: **a completed plan never reports `idle`**, so the gate blocks
forever after completion. I checked the producer rather than the inference:

- `BotBrain.java:94` — on completion, `lastProgress = activeBehavior.getProgress()`
  is captured **before** `:96` swaps in the idle behavior. So the reported
  progress is the completed behavior's, not idle's.
- `Directive.java:50` — `complete()` sets only `status`. Confirmed: progress is
  untouched.
- `SkillBehavior.java:365` — sets phase `skill:done` on success.
  `LocateBehavior.java:317` — sets phase `done`. **Both line numbers exact.**
- `BotBrain.java:189-192` — reports `lastProgress` alongside `lastDirective`.
  **Exact.**

So the answer to the lead's first alternative is **yes, confirmed from the
producer**: post-completion the phase is `skill:done` or `done`, never `idle`,
and the gate holds forever. That belongs to 9.4 as a decision about intent, and
leaving the decision alone here was right.

## Finding — a wrong citation in the task text

`tasks.md:397` says `complete()` sets only `status` **(`:82`)**.
`BotBrain.java:82` is blank. The completion path is `:87-95`; `complete()`
itself is `Directive.java:50`.

The builder's *message* also said "BotBrain.java:82", but the message is not the
artefact — the task text is, and 9.4 will be argued from it. This is the third
time this thread has produced an off-by-one/gone-stale line citation
(`scout.js:50` last round). The pattern is worth naming: the prose is
regenerated when the code moves, but the line numbers are retyped. Whoever
writes 9.4 should re-derive them.

Not blocking: every substantive claim the citation supports is true, and I have
verified each independently above.

## Two observations, neither blocking

1. **The gate now logs on every held tick.** For a bot holding 16 cobblestone
   across a long plan that is one line per tick. That is the intended trade —
   visibility over silence — but if the C1/C4 arms grep these logs, the volume
   is worth knowing about before, not after.

2. **`worker_died` on the first two ticks is noted, not investigated**, per the
   lead. Agreed it should stay out of this review; recorded here only so it is
   not lost.

## Method notes (mine)

- Clean `git archive 7de8c76` for every run; the builder's worktree was not the
  tree under test.
- No `ulimit -v` on any Node-bearing run; `NODE_OPTIONS=--max-old-space-size=2048`,
  `nice -n 19`.
- Mirror equality by `yaml.safe_load` + sha256 of the key value, not text diff.
- Mutant anchors asserted to exactly one match before mutating.
- No apply, no push, no exec into any pod, no secret values read.

## Status

Nothing further owed from me on this row. Nothing pushed, nothing applied; the
M3-1b build/deploy and the 9.4 ruling remain the lead's.
