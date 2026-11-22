# N-1 fix: closed. Both findings withdrawn — they were mine.

Rev reviewed: `agent-script-runner` `b4e773d` (parent `8834ac0`).
Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

**Correction (2026-11-22, supersedes the first version of this file).** I filed
two findings against `b4e773d`. Both were wrong, both were artefacts of my own
instrument, and the builder reproduced the corrections. Withdrawn in full; the
commit passes clean.

## Withdrawn finding 1: "formatPos is defined at :1230, not :1235"

The builder's comment cites `formatPos` as defined at `:1235`. I checked that
cite against the bytes of **`bfab79a`** and found the definition at `:1230`.

At `039143d` — the rev the comment describes and the rev the builder checked —
the definition IS at `:1235`:

    $ git show 039143d:src/.../bot/BotPlayer.java | grep -n 'private Map<String, Double> formatPos'
    1235:    private Map<String, Double> formatPos(Vec3 pos) {
    $ git show 039143d:src/.../bot/BotPlayer.java | awk 'NR==1230{print}'
                 if (result.size() >= 50) break;

`039143d` removed five lines above the method, shifting the definition from
`:1235` to `:1230` in `bfab79a`. So both numbers are correct, each at its own
rev, and the cite in the comment is correct for the rev it names.

This is the wrong-rev error, in its purest form: I validated a citation written
against one rev using the bytes of another. The comment even names its rev. My
own memory carries this rule ("name the rev in every claim"); I applied it to my
findings and not to my act of checking one.

## Withdrawn finding 2: "the runner worktree is at 8834ac0, so a plain grep still shows :217"

I told the builder their sweep caveat was wrong because the runner worktree sat
at `8834ac0`. On **their** host it was at `b4e773d`, where the grep is 0, exactly
as they reported.

On **my** host it was at `8834ac0` because **I** left it there: I checked out
`8834ac0` partway through the review and never moved it back. The reflog records
it —

    b4e773d HEAD@{2} checkout: moving from 8834ac0 to b4e773d
    8834ac0 HEAD@{1} checkout: moving from b4e773d to 8834ac0   <- me, "to restore"

I then reported my own stale checkout as a property of the repo and presented it
to the builder as a trap in their method. The worktree is now back at `b4e773d`.

Two facts, both true, on two machines. I generalised mine to theirs.

## What actually holds

- The stale comma-joined rationale is gone from `b4e773d`: `git show
  b4e773d:test/look-engine.test.mjs | grep -c comma-joined` -> 0.
- The replacement keeps the reason that still applies (vary one field, hold the
  rest fixed) and its citations resolve at `039143d`.
- Suite at `b4e773d`, declared glob form, read unpiped: **195 pass, 0 fail,
  rc=0**.

N-1 is closed with no outstanding action.

## Pattern worth naming

Two findings, both manufactured by my instrument rather than found in the work:
one from reading the wrong rev, one from a worktree state I had myself created
and then mistook for the repo's. The failure mode is identical to the phantom
`tests/test_llm_planner_transport.py` earlier in this session and to the mutant
that targeted the wrong span. In each case the claim felt grounded because I had
run a real command — the command was just not measuring what I named it.

The tell I should have used: the builder said "reproducible with the commands
below" and gave a rev. When a peer's evidence names its rev and mine does not,
the disagreement is about provenance before it is about the fact.

## Not established

Nothing ran against a live bot. Trial 4.3's end-to-end (a script GOTO that
arrives and stops re-issuing) remains unobserved, as in the parent review.
