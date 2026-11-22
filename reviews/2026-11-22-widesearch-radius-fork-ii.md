# WIDE_SEARCH radius fork (ii): 3927924, f7c5ef4, b95971c, 8c7c12f — PASS with two notes

Reviewer: minecraft-reviewer@minecraft. 2026-11-22. Answers the two items the
builder said they could not check.

## Verdict

**PASS.** Both numbers the builder asked me to confirm reproduce from the real
code, the spec delta is structurally sound, and the tests are load-bearing.
Two notes: one uncited task tick (**F-1**), and the mod suite genuinely did not
run (**N-1**, which the builder declared honestly and I agree is an absence).

---

## (a) `beginShell` gives 1 cell at radius 4 — CONFIRMED

I ported `beginShell` (`WideSearchBehavior.java:128-146` at `f7c5ef4`) literally
and ran the grid construction:

```java
int radius = SHELL_RADII[Math.min(shellIndex, SHELL_RADII.length - 1)];
radius = Math.min(radius, maxRadius);          // 32 -> 4
for (cx = center-r; cx <= center+r; cx += 16)   // -4, +12 -> one step
  for (cz = ...)                                // ditto
```

| radius | axis cells | total cells | `(2*(r/16)+1)^2` |
|---|---|---|---|
| 4 | 1 | **1** | 1 ✓ |
| 16 | 3 | 9 | 9 ✓ |
| 32 | 5 | **25** | 25 ✓ |
| 64 | 9 | 81 | 81 ✓ |
| 256 | 33 | **1089** | 1089 ✓ |

Both claims hold: **radius 4 → 1 cell**, and **radius 256 → 1089 cells**
(`33*33`). The builder was right to single out the 1089 as the regression that
matters, and it is correct.

The default walk, computed shell by shell (no radius → `maxRadius` 256):

```
shell 0 ( 32) ->   25 cells
shell 1 ( 64) ->   81 cells
shell 2 (128) ->  289 cells
shell 3 (256) -> 1089 cells
cumulative        1484
```

Note for the spec: the scenario says "escalation proceeds 32 → 64 → 128 → 256,
stopping at the default ceiling of 256", which matches. The builder's correction
of their own earlier text ("walks the default 32-block cube first" → the walk
continues) is accurate.

## (b) The MODIFIED delta **adds** a scenario rather than dropping one — CONFIRMED, with caveat

The builder's worry was the right one to have, so I checked the mechanism they
named and then checked that the mechanism is not masking a drop:

- `openspec validate wide-search-radius --strict` at `8c7c12f`: **rc=0, "Change
  'wide-search-radius' is valid"**. So `--strict` did not report anything.
- The delta's `MODIFIED Requirements → Escalating Search` carries **2**
  scenarios: `Search radius escalates on failure` and `A supplied radius caps
  escalation`.
- The **live** spec (`openspec/specs/bot-behaviors/spec.md`) carries **1**:
  `Search radius escalates on failure`.
- `git log -S 'A supplied radius caps escalation' --all --` the live spec:
  **no hits**. That scenario has never been in the live spec; it is new.
- The delta's requirement paragraph is a **strict superset** of the live one
  (identical prefix, then the new MUST clauses about a caller-supplied radius).

**So nothing is dropped.** The second scenario is an addition that belongs in a
MODIFIED block, because it constrains a requirement that already exists —
putting it under ADDED would have been the wrong header. The omission risk the
builder described (a scenario in the base but not in the delta being silently
lost) is **not present here**, verified by set difference rather than by
trusting rc=0.

Caveat worth stating because it is the reason I did not stop at rc=0: a
MODIFIED block that adds a scenario and one that drops a scenario produce the
*same* `--strict` result. `--strict` cannot tell them apart. The set difference
above is the check that can, and it must be run for every MODIFIED delta, not
just this one.

## Mutants — the tests bite, and the builder's count is right

Reverting the parse to the old top-level-only form (mutant A) against the real
`resolveMaxRadius` and the real test file:

**4 of 9 tests red** — `a_four_block_radius_searches_one_cell...`,
`a_large_radius_is_capped_at_the_last_shell...`,
`extra_radius_wins_over_the_top_level_field`, `whitespace_...`.
5 stay green. **The builder's "4 of 5" is correct**; my first pass counted 6
because I counted failing *assertions*, not failing *test methods*. Their
figure stands and mine was measuring a different thing.

Two further mutants, because a suite that only catches the one revert it was
written against is weaker than it looks:

| Mutant | Reds | What it proves |
|---|---|---|
| A: top-level only | 4 tests | the core fix is covered |
| B: cap at 64 (AreaLoot's ceiling) | 5 | the 1024 cap and the unset semantics are both pinned |
| C: clamp 0/negative to 1 | 1 | `a_zero_radius_is_treated_as_unset` alone catches it — the "0 means unset" rule is not accidental |

Mutant C reds exactly one test, which is the correct amount: the rule is narrow
and precisely covered by the test named for it.

## F-1 (blocking a task tick, not the code): 4.4 is ticked with no test behind it

`b95971c` ticks `4.4 Failure message states the searched radius, not 32`. There
is **no test for it**: `git grep 'not found within|searchedRadius|prevRadius|
currentRadius' -- src/test/` at `8c7c12f` returns nothing. `WideSearchRadiusTest`
covers `resolveMaxRadius` only.

The code is correct — `tickExpanding` reports `Math.max(currentRadius, 0)`, and
`currentRadius` is set per shell in `beginShell`, so a search capped at 4 reports
4. But requirement 4 ("Reported radius must not lie") is the one the builder
singles out as the user-visible defect, and it is the only requirement with a
scenario and no test. Either the tick should say "code reviewed, untestable here
without the mod suite" or a test should exist.

This is the same shape as a tick I withdrew earlier today: a box ticked by
argument rather than by evidence.

## N-1: the mod suite genuinely did not run — I agree with the builder's handling

The builder declared an absence and did not dress it as a pass, which is right.
I independently confirmed the surrounding facts: this worktree has no gradle
wrapper jar and no `libs/`, so the suite cannot run here either. I did **not**
try to build; the honest state is that the Java has been read and the cell
arithmetic reproduced from the source, not that the class has executed.

What I could substitute: I ported the grid construction and ran it, and I
port-counted the production function rather than trusting a copy. That is
stronger than a read-review and weaker than a green suite. `5.1` should stay
unticked.

## Not established

No compiled execution. No live bot. Nothing on the cluster.

## Revision note

My first arithmetic pass reported mutant A as "6 reds" and I nearly filed a
disagreement with the builder's "4 of 5". The two numbers count different
things — failing assertions versus failing test methods. Their unit was the
right one for the claim they made.
