# Review — coded-agents agent→mod report channel, spec only (`1f524a5`)

**Row:** `qitem-20261123101120-1f4d9734eab584ea` (summary pins `0dbe08c`; the builder
nominated `1f524a5` and I reviewed that — `1f524a5` is two commits on).
**Rev:** `1f524a5` on `ship-ca27-harness`. Delta: `design.md` +17/−7,
`specs/bot-coded-agents/spec.md` +21/−6. No product code. Read from a clean
`git archive`, `openspec validate --strict` re-run by me (valid).

**Verdict: FAIL.** One blocking finding (F-1, two clauses of it) and one
non-blocking observation (F-2). The direction of `1f524a5` is right — it removes
a scenario that wrote an undecided behaviour into the spec — but it replaces it
with two scenarios that cannot be satisfied by what reaches the mod, and it
removes the only field that could have made one of them work.

## What `1f524a5` gets right

`0dbe08c`'s "Usage does not carry over from a previous process" asserted, as
required behaviour, that the counter restarts at zero — which is today's
implementation detail, not a decision anyone made. The spec is silent on day
boundary and restart persistence; making the channel neutral on both is correct,
and 5.4 is the right owner. I do not dispute the judgement to withdraw it.

## F-1 (blocking) — the two new scenarios are not observable from the payload

The builder asked specifically whether the reset scenario is observable from
what reaches the mod. It is not, and neither is the "current day" premise of the
one before it.

**The payload carries no day concept and no previous value.** `code_hours` is
`usage_hours() as sent`, and `usage_hours()` is `self._seconds / 3600.0` over a
counter that starts at 0.0 in `__init__` and only ever increases
(`agent/code_time.py:84`, `:101`, `:113`). It is a **process-lifetime monotonic
total**. There is no day field, no day rollover, no reset, and no notion of
"current day" anywhere in the meter or the payload. So:

**F-1a — "Usage shows the meter's current figure for the current day" is
unbindable.** The scenario's THEN says the figure is "the meter's … figure for
that bot **and the current day**, not a total summed across days". The meter has
no per-day figure to report. Until 5.4 defines a day boundary and something
tracks a day, the agent cannot distinguish today's hours from a lifetime total,
so an implementation can only report the lifetime total — which the scenario
explicitly forbids. A conforming implementation does not exist yet, and the
scenario gives no way to tell whether one would pass.

**F-1b — "A drop in usage is reported as a reset" has nothing to fall.** The
channel sends one current figure; "the reported usage … falls" is a comparison
against a value the mod must already hold. But `design.md:104` (unchanged by
this commit, quoted below) says the mod "keeps the **latest** report per bot
**and nothing older**". With only the latest report retained there is no
previous figure to compare, so a fall is not detectable at all — the receiver
cannot implement the scenario.

This is not hypothetical: **the commit removed the field that made it
detectable.** `0dbe08c` sent an explicit `restarted: true` on the first report
after start, which carried the cause *in the payload*. `1f524a5` deletes that
marker and replaces the mechanism with "the mod notices a fall" — which needs
either a retained previous value or a field, and the design now provides
neither. The old bullet was wrong about *what* the spec requires (it asserted
persistence behaviour); the new one is wrong about *what the receiver can see*.

**The design contradicts itself in the same file.** `design.md:104` says the mod
retains nothing older than the latest report; `design.md:139-142` (new) requires
it to detect "a figure falling from 1.4 h to 0.0 h unlabelled". Both cannot hold.
The fresh-staleness rules lean on "latest only" — it is what makes "a repeat
report does not accumulate" true and why the channel "does not need storage".

**Also: "the day boundary" is undefined.** The phrase occurs three times in the
delta (`design.md:132`, `:137`, `spec.md:624`) and not once with a definition.
Twice that is correct — the design bullets explicitly defer the day boundary to
5.4 and say the channel neither requires nor forbids it. The problem is the
third: the spec scenario uses "not at the day boundary" as a **condition** the
receiver must evaluate. A negative condition naming an event nobody has defined
cannot be evaluated, so the scenario fails for a second, independent reason.
Deferring a definition is fine in a design note; it is not fine inside a
requirement's WHEN.

**What I would accept** (builder's choice, all small, this row):

1. **Neutralise both scenarios as the restart one was neutralised** — say what
   the channel *transports* (the figure the meter holds; the change in that
   figure from the previous report) and record that the day boundary, the
   persistence question and the meaning of a fall are 5.4's. That honours the
   commit's own stated principle ("the channel must not decide") consistently,
   instead of deciding day semantics in one scenario while disclaiming them in
   the other.
2. **Or keep the detection rule and give the receiver the means**: state in the
   requirement that the mod retains the previous `code_hours` per bot (one float,
   nothing else — "latest only" in `design.md:104` becomes "latest plus the value
   before it"), and define a day boundary or explicitly drop "current day" from
   F-1a's THEN. Restoring an explicit marker field is the third option and is
   also fine; it just makes the payload non-minimal.

Option 1 is the smaller edit and consistent with what the commit says it is
doing. I am not asking for 5.4's answers in this row — I am asking that the
channel not state a rule it has no route to observe.

## F-2 (non-blocking) — `ticks` is described as a unit, but it is per-process

`design.md:96` says `ticks` exists "so a reader can tell 'zero usage' from 'never
ticked'". `tick_count()` returns `_seconds / tick_period` from the same
process-lifetime counter (`code_time.py:120`). It does distinguish never-ticked
from zero-hours within one process, so the stated purpose holds — but after a
restart a bot that has run for hours reads `ticks: 0`, indistinguishable from a
bot that never started. Given F-1's restart ambiguity that may be acceptable,
and 5.4 owns it; flagged so it is a decision and not an oversight. The design's
own `observed_at` field is what a reader would actually need to disambiguate, and
it is not referenced from this purpose.

## Checked and clean

- `openspec validate --strict coded-agents` — valid at `1f524a5` (I re-ran it).
- The delta is spec/design only: `git diff --name-only 0dbe08c 1f524a5` returns
  exactly `design.md` and `specs/bot-coded-agents/spec.md` — no `.py`, no
  `.java`, and `tasks.md` is not touched at all in this commit. (The builder's
  message said the delta covers `tasks.md`; it does not. Harmless — the 5.6
  wording change they describe is in `design.md`'s task list — but noted so the
  row's record matches the commit.)
- Requirement vocabulary stays closed as the requirement claims:
  `script_state` is the four runner states, and `runner_unreachable` /
  `allowance_exhausted` are untouched (`grep` on the block).
- The unknown-bot, dedup, and staleness scenarios are unchanged by this commit
  and still consistent with each other; F-1b's fix must preserve the dedup
  scenario's "does not grow with time" property — retaining *one* previous float
  does, retaining a history would not.
- No secret named or read; `MOD_API_KEY` appears only as the existing auth
  header, per the row's constraint.

## Not done, stated plainly

- No code review — there is no code in this delta.
- I did not exercise the channel against a running mod or agent; nothing exists
  to exercise yet. Every claim above is from the spec text, the design text, and
  the accessors in `agent/code_time.py` at `1f524a5`.
- I did not review the options table (options 2–4 and their rejection reasons)
  beyond confirming it is present and option 1 is chosen with reasons — the lead
  owns the design decision, and my row is the spec-vs-itself check.
