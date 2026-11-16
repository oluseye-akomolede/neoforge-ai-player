# Gate — spec delta at 863bd97 (instance-loss-at-scale scenario)

Rev: `863bd97`. Row qitem-20261110113245-8e4778cd397f98a7.
Read from the sha (`git cat-file -t 863bd97` → commit; files via `git show 863bd97:`).
Diff scope since `d029546`: `spec.md` (+20), `contract-v1.md` (+5), my review file.
`openspec validate coded-agents --strict` at `863bd97` → valid, rc 0. `show` rc 0.
Date: 2026-11-10T11:40Z
Reviewer: minecraft-reviewer@minecraft
Verdict: **FAIL — one blocker (an internal contradiction in the new scenario)**

## What is right

**It is a clean ADDED scenario.** No requirement header touched, all four prior
scenarios in that requirement survive unchanged, one scenario added
(`:517-540`). Nothing was dropped or silently renamed, so no delta question.

**It correctly strengthens what I asked for.** My `d029546` note treated 264
simultaneous interface reports as a *presentation* problem. The builder made it a
behavioural constraint with an assertable bound, which is the right disposition —
a presentation note gets skipped, a THEN clause does not.

**The contract addition (`:418-422`) is accurate**: the memory limit now carries
the reason it matters ("decides whether an instance loss is a node event or a
routine one") rather than only the arithmetic.

## The blocker

The scenario's third THEN clause contradicts its own bound:

> **AND** the system's behaviour under this event is **bounded by the number of
> bots**: it MUST NOT issue one dead-endpoint request per bot per tick for the
> duration of the interruption

Read plainly, "bounded by the number of bots" sets the ceiling at one request
per bot — and the same sentence then forbids exactly that. An implementer who
takes the first phrase as the budget builds the prohibited design, because the
phrase *names* N as the bound and the prohibition is N per tick. The two halves
cannot both be satisfied unless the bound is strictly below N, in which case N is
not the bound at all.

This is not a wording quibble. The clause exists to stop 264 requests/tick at a
dead endpoint, which is the correct goal; as written it authorises the number it
forbids. That is the same shape as the `api.log` contradiction from `7698f81`
and the undefined `Stack`/`api.send` rows earlier — a clause that a careful
reader resolves one way and a test written from the literal text resolves the
other way.

**Suggested fix** — state the bound as a property the test can measure, not as a
multiple of the bot count:

> **AND** the number of dead-endpoint requests issued during the interruption
> does not grow with the number of affected bots — the runner is probed at a
> bounded rate (the same bound regardless of whether 2 bots or 264 are affected)

That is assertable (run at two fleet sizes, compare request counts), it states
the actual requirement (bounded *independently* of N, not proportional to it),
and it removes the phrase that currently authorises N/tick.

## Second issue in the same scenario (non-blocking, same paragraph)

> **AND** the operator can distinguish this instance-wide event from a fault
> confined to one bot

The distinguishing predicate has only one term. Nothing in the spec or contract
defines what a "fault confined to one bot" *is* as a separate reported signal —
the per-tick classes (`worker_died`, `script_error`, …) are per-bot outcomes, and
the new "single runner-level condition" is the other side, but no text says how
the operator tells them apart in the interface. The scenario asks for
distinguishability without naming the second signal.

Combined with the clause above, this is one request: name the bound and name the
two signals. Both are cheap; the scenario is otherwise a good addition and I do
not want it cut.

## A tree-state observation for the builder, not part of this gate

`minecraft-wt-deepseek` points at `7698f81`; every commit from `03d6493` through
`863bd97` (16 commits) was made on a **detached HEAD** and no branch contains it.
The commits are intact and reachable by sha, so nothing is lost — but the
contract-v1 sequence is not on a branch, and a checkout or reset in that worktree
would strand it. I reached them by sha only. Worth re-attaching before more work
lands on top.

I did not move the branch. The one `checkout --detach` I ran was mine, for
validation at the rev, and I returned the worktree to its branch tip unchanged
(`git status` clean).

## Scope

Document gate. `validate --strict` and `show` run at the rev in a detached
checkout, restored after. No writes to the change. The request-count claim was
not executed — it is a document property, and I am not asserting the runner
behaves that way, only that the sentence does not currently say it.
