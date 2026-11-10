# Gate — coded-agents head confirm at 7ad1b73

Row: qitem-20261110111504-f373728585beaba0
Date: 2026-11-10T11:16Z
Reviewer: minecraft-reviewer@minecraft
Verdict: **PASS at 7ad1b73** — the builder may tick 1.4 citing 7ad1b73.
Covers: PASS at `cc68e1f` (REVIEW-gate-cc68e1f.md), carried forward.

Read from the rev: `git cat-file -t 7ad1b73` = commit, diff taken
`cc68e1f..7ad1b73` in ~/minecraft-wt-deepseek/neoforge-ai-player.

## (b) Nothing else changed — confirmed

`git diff --name-only cc68e1f..7ad1b73 -- openspec/` yields exactly two files:
`changes/coded-agents/tasks.md` and `changes/coded-agents/REVIEW-gate-cc68e1f.md`
(my own review, committed by the builder). Filtering those out leaves nothing.
**No spec delta text changed**, so the PASS at cc68e1f stands unamended.

## (a) The 2.6 wording states the reason I gave — confirmed

The old text said a host-side `try/catch` "can catch the error and continue in a
runtime whose state is already unwound". Both halves of that were wrong, and the
new text fixes both:

- "Not because the runtime is left broken — **it is not**; after a host-caught
  overflow at 256 KB the same context still evaluates correctly"
- "that catch only works **below** the host ceiling. In the regime this task
  exists for (512 KB and above, or unset, where Node dies at ~2362 frames) there
  is no error to catch: the process is gone."

That is the correction as I stated it, and it removes a contradiction the
builder had introduced with 2.7, whose own success test ("a later evaluation
succeeds in the same context") asserted the opposite of "unwound".

The text cites the 100k-loop evaluation rather than the 500-deep recursion I
also reported. That is the safer choice: the recursion case was a `bound`
function I wrote, and a reader reproducing the single simple evaluation cannot
get a different answer from a test-construction error. No objection.

## The `re-confirmed at e95b435` wording

I did not gate `e95b435` as its own rev, and I am not claiming to have. I
checked the relation instead: `git merge-base --is-ancestor e95b435 7ad1b73`
= yes, and `cc68e1f..e95b435 -- openspec/` touches the same two files only
(tasks.md 16 lines, plus my review). So the openspec content confirmed at
7ad1b73 contains e95b435's wording, and the phrase is accurate for the tree I
gated. The builder should keep it as written; changing it to `7ad1b73` alone
would be equally true but would lose the fact that the 2.6 text predates the
tick notes.

## Validators

Run by me at head, now, not inherited: `openspec validate coded-agents --strict`
-> "Change 'coded-agents' is valid", and `openspec show coded-agents` renders
from the title with no `show_error`.

## Standing

1.4 may be ticked citing 7ad1b73. 1b.1 remains unticked and correctly so: the
cardgame leg still holds a draft, and the contract has changed twice since — the
new tasks text says to re-send the `e95b435` text before that task ticks, which
is the right instruction. Nothing else in this gate is open.
