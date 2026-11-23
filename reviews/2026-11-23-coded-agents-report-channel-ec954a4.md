# Review — coded-agents agent→mod report channel, spec only (`ec954a4`)

**Row:** `qitem-20261123101120-1f4d9734eab584ea`.
**Rev:** `ec954a4` on `ship-ca27-harness`, one commit on `1f524a5`. Delta:
`design.md` and `specs/bot-coded-agents/spec.md` only — `git diff --name-only
1f524a5 ec954a4` returns exactly those two, `tasks.md` untouched, confirming the
builder's correction to their earlier claim. No product code. Read from a clean
`git archive`.

**Verdict: PASS.** Both F-1 findings are genuinely fixed, and the fix is the
right shape rather than a rewording of the problem. One new non-blocking finding
(F-3) in the same family, on a sentence the fix introduced.

## F-1a — closed, and closed properly

`code_time.py` at this rev: `:84` `self._seconds = 0.0`, `:101` `self._seconds
+= self._tick_period`, `:113` `return self._seconds / 3600.0`. A
process-lifetime monotonic total; no day field, no rollover. Verified by reading
the lines, not by taking the message's word.

The channel no longer asserts a window. "Usage shown is the figure the agent
reported" says the mod shows what the agent sent and must not compute, estimate
or accumulate its own figure; the window ("a day, a process lifetime, some other
period") is explicitly 5.4's. That is unbindable-to-bindable: the scenario can
now be satisfied by the meter as it exists, and it stops over-claiming.

I checked the builder's claim that no WHEN uses "day boundary" or "current day"
any more. `grep` over the delta: two hits, `design.md:138` and `spec.md:638`,
both inside AND-clauses naming what is *not* decided. **No WHEN anywhere in the
block uses either phrase.** Claim holds.

## F-1b — closed, with a design choice I endorse

`previous_code_hours` (≤ 20 bytes, "the figure this one replaces; absent on a
bot's first report") makes a fall readable from a single report while the mod
still keeps only the latest. The pair is now consistent: `design.md:105-107`
"keeps the latest report per bot and nothing older" and `design.md:134-135` "a
fall is readable from the new report alone and the mod still keeps only the
latest" say the same thing instead of contradicting each other.

**The not-restoring-the-marker judgement is correct and better than my
suggestion.** A `restarted: true` field asserts a *cause* the agent cannot know
— from the sender's side a restart, a day rollover and a replaced meter are the
same event, a jump to zero. `previous_code_hours` asserts only what was actually
sent. That is the smaller, more honest claim, and it is why the channel can stay
out of 5.4's decision instead of quietly making it. I withdraw the marker option
from my previous review.

The scenario also crosses the line exactly where it should: it states that the
report carries the figure it replaces and that the difference is not presented
as spending, and declines to say *what* a fall means. Sound.

## F-3 (non-blocking) — a restart's fall is the one the field cannot carry

`design.md:193-196` says: "a restart or a day rollover producing a fall **is
observable from `previous_code_hours`**". For a day rollover that is true — the
same process reports the new day's figure against the previous one. For a
**restart it is false in the case that matters.**

By the field's own rule, `previous_code_hours` is "absent on a bot's first
report". After an agent restart the meter is a new process starting at
`_seconds = 0.0`, so the bot's first report of the new process carries
`code_hours: 0.0` and **no previous value** — and that is precisely the report
where the fall from 1.4 h to 0.0 h happens. The report that carries the fall is
the one that has nothing to compare against, because the knowledge of the old
figure died with the old process.

There are only three ways to have it, and all three are 5.4's or out of scope:

1. the agent remembers its last sent figure somewhere that survives the restart
   (that is persistence, which this channel explicitly does not decide);
2. the mod remembers the previous report (which "latest-only storage" forbids);
3. a marker asserting the cause — which the builder correctly rejected.

So the sentence over-claims in exactly the way F-1a did: it asserts an
observability the payload does not provide, for one of the two causes it names.

**The fix is one clause, not a redesign**, and I would take it in this row: say
the day-rollover fall is observable from `previous_code_hours`, and that a
restart's fall is **not** observable from the report in the same way — the new
process's first report has no previous value, so a restart reads as a bot
appearing at `0.0 h` and whether that should be labelled is 5.4's. That is
honest, it keeps the channel neutral, and it does not require choosing any of
the three mechanisms above.

This does not block. The requirement block itself is correct; F-3 is in the
design's "deliberately does not decide" section, which is commentary, and a
reader who trusts it would build against a guarantee that fails on restart. Fix
it in this row if cheap; otherwise it belongs verbatim in 5.4's brief.

## F-2 — recorded correctly

The `ticks` purpose line now says "within one process", and a dedicated bullet
says hours > 0 with `ticks: 0` is normal after a restart. Cites `:85`/`:100`,
read at `:124` — all resolve (`self._ticks = 0`, `self._ticks += 1`, `return
self._ticks`). Closed.

## Line cites checked (builder's question 2)

Every cite in the delta, read against `agent/code_time.py` at `ec954a4`:

| Cite | Line as it exists | Correct |
|---|---|---|
| `:84` | `self._seconds = 0.0` | yes |
| `:101` | `self._seconds += self._tick_period` | yes |
| `:113` | `return self._seconds / 3600.0` | yes |
| `:85` | `self._ticks = 0` | yes |
| `:100` | `self._ticks += 1` | yes |
| `:124` | `return self._ticks` | yes |

One stale phrase, not a cite: `tick_count`'s own docstring (`:121`) still says
the count "Equals `usage_seconds / tick_period`". It does not, exactly — both
are integer accumulations of the same tick, so they agree up to float drift, but
the identity is asserted rather than constructed. Harmless and pre-existing;
noting it because the design now leans on `ticks` meaning something precise.

## F-4 (non-blocking) — the corrected size bound is still under the real cap

The builder corrected "under 200 bytes" to "under 220". Both are low. Measured
from the design's own field caps, serialised compactly, counting keys, quotes,
commas and braces:

- **Every field at its cap:** 268 bytes. (24+20+20+10+20+72 = 166 bytes of
  values, plus 102 bytes of JSON structure and keys.)
- **The design's own example payload** with a realistic full-length revision
  (`sha256:` + 64 hex) and default separators: **223 bytes** — already over 220
  before any field is pushed to its cap.

So "under 220" is false for the example the design itself prints, and false by
48 bytes for the worst case the field table permits. The bound is harmless —
nothing in the channel's design depends on the number, and 268 bytes is still
tiny — but it is the same species as the two findings above: a quantitative
claim in the prose that the artefact does not support. If 220 is meant as a
soft target, say "about 0.25 KB"; if it is meant as a guarantee, the caps or
`revision`'s ≤ 72 need to come down.

Recording rather than blocking: no reader builds against this number, and the
builder has already shown they fix these when named. My earlier draft of this
section said the corrected figure was right — it is not, and I corrected it
before committing.

## Checked and clean

- `openspec validate coded-agents --strict` — valid at `ec954a4` (re-run by me).
- Delta is exactly two files, no `.py`/`.java`/`tasks.md`.
- No WHEN in the requirement block states a rule this channel does not own; I
  read the whole block, not only the changed scenarios.
- `previous_code_hours` does not breach "a repeat report does not accumulate":
  the mod still stores one record per bot; the extra field rides in that record.
- No secret named or read.

## Not done, stated plainly

- No code review, and no live exercise of the channel — none exists yet.
- I did not re-review the options table; that remains the lead's design call.
- I did not verify against a real agent process that the *first* report after a
  restart genuinely omits `previous_code_hours` — that is from the design text
  plus `code_time.py`'s `__init__`, since no sender code exists at this rev.
  The claim in F-3 rests on those two things and would become checkable at 5.6.
