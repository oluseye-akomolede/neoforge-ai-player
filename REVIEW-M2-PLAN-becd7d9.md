# Review — M2 plan stale pointer fixed at `becd7d9`

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-11
Scope: the one defect from `REVIEW-M2-PLAN-STALE-8e6c6f5.md`.
Closes `qitem-20261111112423-c75f166d5c5db537`.

## Verdict: PASS. The defect is fixed in the form I asked for, and the fix is
better than the minimum.

## 1. The fix

`M2-PLAN.md:499-501` now reads:

    1. Tick 4.1/4.2/8.1 in `tasks.md` — **done**, commit `5f52a79`, corrected at
       `73fd81f`. Read the ticks at `73fd81f`: `5f52a79` records the superseded
       `416ef999` digest, which is now only the rollback target (reviewer 11:34Z).

Three properties, all wanted:

- history kept — `5f52a79` is still named as the commit that ticked;
- the correction is pointed at by sha, so the reader is sent to the right rev;
- it says **why**, not just where: "read the ticks at `73fd81f`" tells a reader
  which line matters, rather than leaving them to diff two commits to find out.

That third property is the improvement on what I asked for. I proposed citing
`73fd81f` or writing "corrected at"; they did the second *and* explained the
consequence for the reader.

## 2. Independent sweep of every sha in the plan

My own sweep, not theirs:

    grep -noE '\b[0-9a-f]{7,40}\b' M2-PLAN.md
      499:5f52a79   500:5f52a79   500:73fd81f   501:416ef999

Four occurrences, three distinct tokens.

    git cat-file -e 5f52a79^{commit}  -> OK: "tasks: tick 4.1, 4.2, 8.1 - runner live on TEST"
    git cat-file -e 73fd81f^{commit}  -> OK: "tasks: 4.1/8.1 cite the deployed digest, not the supers..."

Both resolve. `416ef999` is a digest, not a commit, and appears once — at
`:501`, in rollback-target context, correctly identified as such. Their report
of the sweep matches my re-run.

**No digest is pinned anywhere in the plan.** My reading stands: the only
digest-shaped string elsewhere is the `sha256:…` ellipsis in the `scout.json`
example at `:418`, which is an illustration, not a pin.

## 3. The bad query, and why it matters more than the fix

They report their first grep missed even the `:418` hit because it required 8+
hex characters after `sha256:`, so `sha256:…` never matched — a too-strict
regex reported as an absence. My reading was right and theirs was a query that
could not return a positive.

That is the failure I check for in others and still nearly made in this
session: an empty result is a claim about the query until a positive control
proves otherwise. Worth recording that it cost them here in the *opposite*
direction — the too-strict pattern made them under-report their own file's
contents, and had I taken the row's description at face value I would have
carried a wrong statement into the review.

## 4. Validation

    openspec validate coded-agents --strict
      Change 'coded-agents' is valid
    git rev-parse --short HEAD
      becd7d9

The sha is printed by the validating command itself and matches HEAD. This is
the habit applied, not merely described — and it matters here because my own
review commit will move HEAD again after this.

## 5. What remains unchecked

Unchanged from the prior review and re-stated because a PASS tends to bury it:
neither of us has re-read all 539 lines this session. The plan's file list
(§7) and its TEST proof (§8) are untested claims until step 2 runs. This PASS
covers the pointer defect and the sha sweep, not the plan's correctness as a
programme of work.

## Standing

PASS. `qitem-20261111112423-c75f166d5c5db537` closed.

Co-Authored-By: Claude Code <noreply@anthropic.com>
