# N-1 fix: comment is honest, one cite is off by five

Rev reviewed: `agent-script-runner` `b4e773d` (parent `8834ac0`).
Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

## Verdict: PASS with one nit. N-1 is closed.

N-1 asked for `test/look-engine.test.mjs:217`'s stale rationale to go. It is gone,
and the sentence that replaced it keeps the part that still holds.

## What changed, verified

`git show b4e773d -- test/look-engine.test.mjs`, 6 insertions / 6 deletions, one
file. The old comment said the fixture "carries position as a comma-joined
string"; the new one says `getStatus` calls `formatPos` so position is a
`{x, y, z}` map, and gives the surviving reason for building the body locally
(vary one field, hold the rest fixed).

The stale claim is genuinely absent at this rev. `git show b4e773d:test/look-engine.test.mjs
| grep -i 'comma.joined'` is empty. Note for anyone repeating the sweep: the
worktree is checked out at `8834ac0`, so a plain `grep` over the file returns
the OLD hit at `:217`. That is a checkout-state artefact, not a surviving
comment — read the rev, not the worktree.

## The one defect: a cite that does not resolve

The new comment says:

    (BotPlayer.java:762, defined at :1235 as Map<String, Double>)

`:762` is correct — `status.put("position", formatPos(player.position()));`.
`:1235` is **wrong**. `formatPos` is defined at **`:1230`**:

    1230:    private Map<String, Double> formatPos(Vec3 pos) {

Line 1235 is inside the method body (`map.put("y", ...)`). The comment was
presumably written against the older `:1235-1240` range that N-1 removed, and
the range's start was carried over instead of the definition's line.

This is the same fault class N-1 filed — a comment whose citations do not
resolve — surviving inside N-1's own fix. It is a one-character edit
(`:1235` -> `:1230`) and blocks nothing.

## Suite

`npm test` at `b4e773d`, declared script (glob, not directory form), read
unpiped: **tests 195, pass 195, fail 0, rc=0**.

## Not established

Nothing ran against a live bot. The trial 4.3 end-to-end (a script GOTO that
arrives and stops re-issuing) remains unobserved, as in the parent review.
