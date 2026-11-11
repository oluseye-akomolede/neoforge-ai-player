# Review — M2 task ticks at `73fd81f`

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-11
Scope: `d569df6..73fd81f`, which touches `tasks.md` only (`contract-v1.md` and
`REVIEW-M2-PLAN-d569df6.md` were reviewed previously). `M2-PLAN.md` itself is
unchanged since `d569df6`.

## Verdict: PASS. Every ticked task is backed by evidence I have seen or run.

The handoff title is "M2 plan ready for review: first bot runs from a script on
TEST (plan only, no code)". That is accurate: 8.2, the first-bot task, is still
`[ ]`. Nothing was ticked beyond what was done, which is the failure mode that
would have mattered most here.

## 1. 4.1 — the runner is live, and the figures are the ones that were reported

Claimed: digest `sha256:7ca7e1e2…` (push of `c0c33bc`), 5/5 §5 checks,
rollout 1/1, `/readyz` 200, cold→warm 130.2→2.9 ms, token 401/401/200,
wall median 121.1 / max 143.5 against 250 ms over 60 cold bots.

Checked against the §5 report and my review at `5dfd7f7`: **every figure
matches**, and the §5.4 three-row shape (401, 401 `wrong_game_token`, 200) is
what the plan at `TEST-RUN-PLAN.md:224-228` requires. The digest is the one I
verified from the registry's `Docker-Content-Digest` header and pulled by
digest.

The supersession is handled correctly: `416ef999…` is named as the earlier
figure now serving as the rollback target, rather than being deleted. That is
the right way to record a same-day correction — a later reader can see both
and know which is live.

## 2. 4.2 — ownership and hosting

Claimed: local repo `~/minecraft/agent-script-runner`, no remote, its own
deployment in k8s. Verified: `git remote -v` is empty; the manifest deploys
`agent-script-runner` into `minecraft-test`.

One nit, not a defect: the task says "its own k8s namespace" but the manifest
deploys into `minecraft-test` (`:18`, `:173`), shared with the server. The
substance — the runner is a separate Deployment it owns, not part of the game
server — is true. Worth tightening the wording on a future edit so nobody later
greps for a namespace that does not exist.

## 3. 8.1 — tests and deploy

Claimed: deployed by OCI index digest from the registry header with
`application/vnd.oci.image.index.v1+json`, **not** from a local image ID;
119/119 at that revision; the earlier 102/102 was at `9de61db`, before the four
review fixes.

This is the strongest edit in the commit. It retires the exact inference I got
wrong earlier in this work — I once claimed a pinned digest was a local image ID
on the strength of its shape and a missing local tag, without querying the
registry. The task text now states the provenance method rather than the bare
figure, so the claim is checkable rather than trustable.

119/119 is confirmed by my own suite run at `c839d24` (`REVIEW-c839d24.md:10`,
`# pass 119`, `# fail 0`), and `src/`/`test/` are byte-identical from `c839d24`
through `c0c33bc` to the deployed image. The 102→119 note is honest about the
earlier figure instead of overwriting it.

## 4. `openspec validate`

    openspec validate coded-agents --strict   ->  valid, rc=0

Run at `73fd81f` in the worktree that holds the change, with the rev printed in
the same command.

## Standing

PASS. No unproven tick. The only correction is the 4.2 "own namespace" wording.

Co-Authored-By: Claude Code <noreply@anthropic.com>
