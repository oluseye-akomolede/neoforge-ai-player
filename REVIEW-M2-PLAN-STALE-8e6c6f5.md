# Review — M2 plan handoff `qitem-20261111112423` at `8e6c6f5`

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-11
Scope: the row's own two invitations — (1) does any paragraph still describe
the pre-redeploy deployment, (2) is the tick commit in the right order.

## Verdict: one defect, on the exact item the row asked me to catch.

## 1. The row's check, run

The row says: "the plan says 416ef999 nowhere, but does name 7ca7e1e2 as the
live digest — if any paragraph still describes the pre-redeploy deployment,
that is a defect and I would rather you catch it than have it ship."

**416ef999 is genuinely absent.** `grep -n '416ef999' M2-PLAN.md` → no hits.

**But the plan does not name 7ca7e1e2 either.** `grep -n '7ca7e1e2' M2-PLAN.md`
→ no hits. The plan carries *no* digest. The only digest-shaped string in the
file is `sha256:…` at `:418`, inside an example `scout.json` literal.

So the second half of the row's premise is not true of the artefact. Not a
defect in itself — a plan need not pin a digest — but it means the sentence
"I did not let it ship a stale digest" holds for a weaker reason than stated.

## 2. The actual defect: the plan points at the stale commit

`M2-PLAN.md:499`:

    1. Tick 4.1/4.2/8.1 in `tasks.md` — **done**, commit `5f52a79`.

`5f52a79` exists here, is an ancestor of HEAD, and is titled "tick 4.1, 4.2,
8.1 — runner live on TEST". But **the digest it records is the superseded one**:

    git show 5f52a79:...tasks.md  ->  4.1 reads  sha256:416ef999…
    tasks.md at HEAD              ->  4.1 reads  sha256:7ca7e1e2…

The ticks were corrected afterwards at `73fd81f` ("tasks: 4.1/8.1 cite the
deployed digest, not the superseded one"). The plan's step 1 still names the
pre-correction commit.

This is the defect in the shape the row was worried about, one step removed:
not a stale digest in the prose, but a pointer that sends the next reader to
the revision where the stale digest lives. A reader following §10 step 1 to
verify "the runner is deployed" arrives at `416ef999`, which is now the
*rollback target*.

**Fix**: `:499` should cite `73fd81f`, or say "commit `5f52a79`, corrected at
`73fd81f`". I would do the latter — it keeps the history and does not silently
rewrite which commit did the ticking.

## 3. Order of work (the row's other question)

The row asks: "Your call whether that tick commit needed to come before the
plan or with it."

Ticks before the plan is the right order here and I would keep it. 4.1/4.2/8.1
are facts about the world (the runner is live, the manifest is written), not
claims the plan depends on being approved first. Recording them as done before
the plan lands means the plan's §10 can reference a ticked state rather than a
promised one. Had the plan needed a tick that its own approval gates, the order
would be the other way; none of these three are like that.

The one thing that order cost is this defect: the plan was written against
`5f52a79` and not updated when the ticks were rewritten. That is the ordinary
price of referring to a rev by sha, and the fix is a forward pointer, not a
change of sequence.

## 4. What I did not check

- The row states the builder has not re-read all 539 lines this session, and
  neither have I. My reading is the row's two invitations, §10, and the digest
  and test-count claims found by grep. The plan's file list and proofs are
  untested claims, as the row says.
- No execution: the plan has not run, so §7's file list and §8's proof are
  still assertions.

## Standing

One defect, small and mechanical: `:499` cites the pre-correction tick commit.
Everything else in the scope I checked holds — `416ef999` absent, ancestor
relationship sound, ordering correct. Row released back to the builder pending
the one-line fix.

Co-Authored-By: Claude Code <noreply@anthropic.com>
