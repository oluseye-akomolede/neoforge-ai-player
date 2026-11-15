# REVIEW 2482fb5 — roll aibot-agent-test to agent@sha256:2914fb85

Reviewed from the parsed YAML at the rev (`git show 2482fb5:base/minecraft/agent.yaml`),
not from the diff, and from the push log.

## Verdict

**PASS for apply.** One condition on the lead's request, and one thing to check
before the roll is called done; neither blocks the apply.

## Verified

- **Exactly one image line moved, and it is the test deployment.** Parsed every
  `image:` line in the file at `2482fb5`: L42 `aibot-agent` (prod) `e80c2e8b`,
  L142 `aibot-agent-test` `2914fb85`, L185 `seed-profiles` initContainer
  `agent:2026-11-05-c193f76`. Within the 200-line gap between deployments, L142
  sits under `aibot-agent-test` (declared L114) and L185 is the init container at
  L184 — so the init image is still the test deployment's, unchanged. `git diff
  --name-only 6ca3b45 2482fb5` is one file; `git show --stat` is 1 insertion, 1
  deletion. Both agree.
- **The digest is the one that was pushed.** `/tmp/img-ca27b6e-push.log` ends
  `ca27b6e: digest: sha256:2914fb85ff2220…880083`, and the manifest carries that
  digest in full. Only one digest appears in that log, and the tag is `ca27b6e`,
  which matches the rev this rollout is about. Comparing against the wrong log was
  the builder's own near-miss; the comparison here is against the right one.
- **A digest pin under `IfNotPresent` is what makes this reviewable at all.** The
  manifest is the declared state; a tag move could not be reviewed, and this could.
  Both deployments remain on `IfNotPresent`.
- **The branch state reported matches the repo.** `origin/main` is `2e7c756`, and
  `origin/main..pin-agent-digest` is the four commits the builder says are there:
  `e41368a`, `327e708`, `6ca3b45`, `2482fb5`. Nothing else is on the branch, and
  the worktree is clean, so the sha is the tree.

## Condition 1 — prod is still on the pre-fix image, and that is the lead's call

This is a test-only roll: prod stays on `e80c2e8b`, which is the image carrying the
plan regression this whole row exists to fix. That is correct for a test rollout and
I am not flagging it as a defect. But it means applying this branch applies four
commits, and three of them (`e41368a`, `327e708`, `6ca3b45`) change the **prod**
deployment's declared state too. The lead should apply knowing that: after the apply,
prod's manifest declares its existing digest with `IfNotPresent` and the thread-limit
env block, so the prod pods should not restart — but "should not" is a prediction, and
the lead should check `generation` and pod age on prod after the apply, not just
that the apply succeeded.

## Condition 2 — nothing in the harness has ever run this image

The digest resolves in Harbor and the manifest points at it, but the image has not
been exercised. `evals/job-evals.yaml` still pins `a9e75ad1` while this roll uses
`2914fb85`, so the eval Job will not measure the image the test deployment is
about to run. That gap predates this commit and I raised it on the harness row;
restating it here because a green eval Job after this roll will be evidence about
`a9e75ad1`, not about `2914fb85`.

## Not verified, and why

The image's **contents** — I have not confirmed `2914fb85` was built from `ca27b6e`
beyond the log's tag line. The tag-to-sha link in a push log is the builder's build,
and I am taking the log as the record of what was pushed. A stronger check is a
`docker image inspect` on the tag, which is the builder's environment, not mine.

## Rollback

`git revert 2482fb5` on the branch and re-apply. Since both old and new are digest
pins under `IfNotPresent`, the reverted manifest will re-point test at `e80c2e8b`
and the old image is already on the nodes.
