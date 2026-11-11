# Gate — M2 plan §1 opening and /bots row at d18582e

Rev: `d18582e`, parent `08804f1`, `openspec/changes/coded-agents/M2-PLAN.md`
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS.** Both changes are right, and the `/bots` min is a substantive
data correction rather than a wording fix — worth naming as such.

## The opening sentence now matches the evidence

`08804f1` left `:82` saying "The result is **bimodal**, which is the whole
finding" while its own correction four paragraphs later established that only
`/directive` is bimodal. `d18582e` replaces it with "Two different shapes came
back — `/directive` **bimodal**, `/bots` **deterministic** — and the distinction
is the finding." The section's first sentence now states what its table and its
correction both support.

## The /bots row was wrong in a second way, and they caught it

The old row read min **2.5 ms**, median 41.9 ms. The new row reads min **41.9 ms**,
median 42.2 ms. That is not a rewording: a 2.5 ms minimum is exactly what an
alternating endpoint produces, so the old row was still carrying a value from the
withdrawn reading even after the prose had abandoned it. With the minimum gone,
the table itself now says "this endpoint never goes fast."

This is the same defect class as the prose one — a number surviving a correction
its sentence went through — but one step harder to see, because it survived in a
column rather than in a claim. Worth recording that the prose fix at `08804f1` did
not carry into the table and the table fix at `d18582e` did; the two arrived one
commit apart.

## Consistency check

All three places `/bots` is described now agree: the row (`41.9 ms` min,
`deterministic ~42 ms`, cause unexplained), the interleaving evidence
(`41.9–44.3 ms on every sample`), and the correction's "not established". A grep
for `41.9|2.5 ms|every.*sample|14 times` across the file returns no fourth
figure and no contradiction.

## The decision is unchanged and I have nothing further

`/bots` deterministic at ~42 ms is strictly better for the bound than alternating
(no tail), 129.5 ms worst case against 300 ms, per-tick cache keeps it off the
critical path on hits. The unexplained 38 ms gap is recorded as unexplained rather
than papered over, which is the right resting state for a plan that says what it
does not know.

I re-ran nothing. This is a plan-only commit; no code moved.
