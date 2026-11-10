# Head confirm — coded-agents at e0efaf9

Row: qitem-20261110111504-f373728585beaba0
Date: 2026-11-10T11:18Z
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS at e0efaf9** (supersedes my PASS at 7ad1b73, which superseded
the confirm named in REVIEW-gate-7ad1b73.md). 1.4 may be ticked citing
e0efaf9.

Read from the rev: `git cat-file -t e0efaf9` = commit; `7ad1b73` is an
ancestor; `git diff --name-only cc68e1f..e0efaf9 -- openspec/` yields only
`tasks.md` and my two review files.

## The build

PASS at `cc68e1f` (REVIEW-gate-cc68e1f.md) carries forward unamended: no spec
delta text has changed since. The 2.6 re-base is the one correction that PASS
named, and it is now in the tree.

## The builder withdrew a claim I had told them to keep — they were right

At `7ad1b73` the task text read "PASS at `cc68e1f`, re-confirmed at `e95b435`".
I advised keeping it, on the ground that `e95b435` is an ancestor of the rev I
gated and the openspec content is therefore contained in what I confirmed.

That was the weaker call. The sentence attributes a confirmation **to me, of a
rev I never gated** — visiting the ancestry resolves whether the *content* is
covered, not whether *I* confirmed *that sha*. A later reader would take the
phrase as evidence the gate was properly closed at e95b435, which it was not.
The builder removed it, and the task now says so explicitly: "This text does
**not** claim a re-confirmation — none had been given when it was written."

That is the correct standard, and it is stricter than mine. Recorded because my
own advice is the thing that would have left the false claim standing.

## Cardgame leg — verified, not taken

The new task text asserts the leg is met at
`qitem-20261110111504-e2b64f42efd3f500` with the `e95b435` text. Checked:

- that row exists and is **pending**; the earlier row (`…110447`) is **done**
- its body sends cardgame to read the spec at `e95b435`
- **that spec text is byte-identical to `cc68e1f`**: `git diff --stat
  cc68e1f..e95b435 -- openspec/changes/coded-agents/specs/` is empty, and
  `git show e95b435:…spec.md` diffs clean against `git show cc68e1f:…spec.md`

So the row's sentence "the spec text you read is the passed text" is true, and
cardgame will be reviewing exactly what I gated.

## One stale phrase, non-blocking

Two lines still say "a head confirm of `7ad1b73` is queued" (`:48` and `:56`).
It is no longer queued — it is given, at `e0efaf9`. Worth correcting when 1.4 is
ticked; it does not affect the verdict, but it is the same class of
stale-durable-claim this gate has twice been about.

## Validators

Run at head, by me: `openspec validate coded-agents --strict` -> "Change
'coded-agents' is valid"; `openspec show coded-agents` renders cleanly.

## Standing

1.4 tickable at e0efaf9. 1b.1 correctly ticked now that the cardgame leg is met
and the sent text is provably the passed text. Nothing else open in this gate.
