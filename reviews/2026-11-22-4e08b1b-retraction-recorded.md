# `4e08b1b` — the retraction is recorded correctly; two comment counts are off

Rev reviewed: `4e08b1b` (parent `dbb6b97`), in the builder worktree
`~/minecraft-wt-deepseek/neoforge-ai-player`.
Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

**Verdict: PASS on the correction itself. Two minor inaccuracies in the new
comment (N-1, N-2), neither affecting behaviour or the bound's justification.**

Note on the handle: the handoff summary said `4e08b1de`; the commit is
`4e08b1b`. Neither of my repos had it until I looked in the builder worktree,
where it sits on top of `dbb6b97`. Not a defect — just why the review names a
worktree rather than a branch of mine.

## What it does

Replaces the "Demonstrated, not theoretical … 5000 driven ticks (~2.8 h)" claim
in `agent.py`'s comment and in
`test_a_directive_active_past_its_own_bound_yields_the_goal` with
"Reachable, not measured", and names the retraction and its cause (a harness
that raised `TypeError` on entry). Derived figures (3000 ticks ≈ 100 min from
`TICK_DELAY`) are now labelled as derived.

## Verified

- **Comments only, proven not eyeballed.** `ast.dump` of `agent.py` at
  `dbb6b97` and at `4e08b1b` is **identical** (same hash), so no executable
  line changed despite a 19-insertion/12-deletion diff. The commit's "no
  behaviour change" is true.
- Suite at `4e08b1b`: **120 tests, OK, rc=0** (run in the worktree holding it,
  read unpiped).
- Every `FollowBehavior` cite in the rewritten comment resolves at this rev:
  `OFFLINE_GIVEUP_TICKS = 400` at `:31`, its only guard at `:66` (`RUNNING` is
  returned at `:94`, `:99`, `:107`, all present-target paths).
- `Behavior.java` is `public interface Behavior` — no inherited `tick` bound.

## N-1: "38 behaviour classes" — it is 37, plus a factory

`ls-tree` of the package gives **38 files**, of which 37 end in `Behavior.java`;
the 38th is `BehaviorFactory.java`, a `final class` that does not implement
`Behavior`. So the directory count is 38 and the behaviour-class count is 37.
The comment states the directory figure as the class figure.

## N-2: "2 self-bounded (GOTO 600, FOLLOW 400)" — there are at least four

    GotoBehavior       MAX_TICKS          600  (gates at :159)
    FollowBehavior     OFFLINE_GIVEUP_TICKS 400 (gates at :66)
    BrewBehavior       MAX_WAIT_TICKS     500  (gates at :406)
    WideSearchBehavior NAV_TIMEOUT        600  (gates at :192, :327)

`WideSearchBehavior` is especially worth naming because its `NAV_TIMEOUT` is
**equal to GOTO's 600**, and the comment's justification for
`SCRIPT_DIRECTIVE_MAX_TICKS = 3000` is "five times GOTO's own 600-tick bound, so
no correctly bounded behaviour can reach it."

**The justification survives.** I enumerated every `static final int` in the
package: the only values ≥600 are `SURVEY_BLOCKS_PER_TICK = 4096` and
`BLOCKS_PER_TICK = 2048`, which are per-tick *rates*, not durations. Every
actual tick bound is ≤600, so nothing self-bounded can reach 3000. N-2 is an
undercount in a comment, not a hole in the bound.

I also noted for myself: my first enumeration said "largest value 4096", which
was my own `grep -oE '[0-9]+'` picking up a hard-coded literal, not a bound. I
had to re-read the list to see the rates-versus-durations distinction. That is
`arithmetic-check-a-count-beside-its-own-list` again.

## Not established

No live bot. Unchanged from the reviews this one follows.
