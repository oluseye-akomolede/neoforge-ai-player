# WIDE_SEARCH radius fork (ii): 3927924, f7c5ef4, b95971c, 8c7c12f — ~~PASS~~ NOT PASS (amended)

Reviewer: minecraft-reviewer@minecraft. 2026-11-22. Answers the two items the
builder said they could not check.

## Verdict

**NOT PASS — amended 30 minutes after first filing.** My original PASS was wrong
on requirement 2. I verified the new rev's arithmetic against itself instead of
against the parent rev, so I recorded "1089 cells, unchanged" when the change had
in fact halved the default reach from 512 to 256. Details and corrected counts
in the amended section (a); the lead caught this, not me.

What still stands: the spec delta is structurally sound, the tests are
load-bearing, radius 4 → 1 cell is correct, and the mod suite genuinely did not
run (**N-1**, declared honestly — an absence, not a pass). One uncited task tick
(**F-1**).

The blocking item is **requirement 2**: `resolveMaxRadius` must default to 512,
with a test pinning no-radius → max 512 and shells 32..512, and the spec delta
and vocabulary corrected to match.

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

The two per-radius counts hold: **radius 4 → 1 cell**, and **radius 256 → 1089
cells** (`33*33`).

> **AMENDED 2026-11-22 (supersedes the "regression unchanged" conclusion below).**
> This section originally reported the default walk as 32/64/128/256 → **1484
> cells** and called requirement 2 satisfied. **That was wrong, and the error was
> mine.** I computed the default from `MAX_RADIUS` at the *new* rev (256) and
> never opened the **parent** rev to ask what the default used to be. Requirement
> 2 says "no radius = today's behaviour unchanged" — a claim that can only be
> tested against `3927924^`, which I did not read.
>
> The lead caught it. At `3927924^` (`eb5498f`) line 90 reads:
>
> ```java
> maxRadius = directive.getRadius() > 0 ? directive.getRadius() : 512;
> ```
>
> So the parent default was **512**, and `resolveMaxRadius` at `8c7c12f:488`
> sets **256**. The change **halves** today's default reach — the exact
> regression requirement 2 was written to prevent.
>
> The walk stops early because of the clamp: at `8c7c12f:361`,
> `if (nextRadius <= prevRadius ...)` fires as soon as the clamped next radius
> stops growing. `SHELL_RADII` contains 1024, but with the default at 512 the
> walk terminates at 512 and **1024 is never reached** — so "the walk reaches
> 1024" is false at both revs.
>
> Corrected counts, computed from the rev's own cell enumeration
> (`(2r/16 + 1)^2`):
>
> | rev | no-radius max | shells walked | cells |
> |---|---|---|---|
> | `eb5498f` (parent) | 512 | 32,64,128,256,512 | 25+81+289+1089+4225 = **5709** |
> | `8c7c12f` (reviewed) | 256 | 32,64,128,256 | 25+81+289+1089 = **1484** |
>
> The lead's 5709 is exact. My 1484 is the correct count *for the new rev* and
> is precisely the defect: 1484 ≠ 5709. The verdict on this requirement is
> **NOT PASS**; it needs `resolveMaxRadius`'s default restored to 512, a test
> pinning no-radius → max 512 with shells 32..512, and the spec delta plus
> vocabulary corrected to match. The builder is fixing it; I will review the fix
> commit.
>
> Everything else in this review — the 1-cell-at-radius-4 check, the delta's
> scenario coverage, the mutant count — stands, since none of it depended on the
> default.

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
