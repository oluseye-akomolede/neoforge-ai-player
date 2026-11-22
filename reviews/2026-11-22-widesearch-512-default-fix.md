# WIDE_SEARCH 512 default: 7d95aeb + 43c03c9 — PASS on the fix, two task ticks wrong

Reviewer: minecraft-reviewer@minecraft. 2026-11-22. Reviews the fix for the
regression my previous review wrongly passed.

Verdict: **the code and spec fix is correct and I accept it.** Two task-list
entries are wrong and must be corrected before the change is archived — one is
ticked against a test that cannot see what it claims (**F-1**), one is ticked
while describing the regression itself (**F-2**). Neither is a code defect.

---

## The regression is fixed

The regression is fixed. At `7d95aeb`:

```java
56:    static final int DEFAULT_RADIUS = 512;
497:       if (requested <= 0) requested = DEFAULT_RADIUS;
498:       return Math.max(1, Math.min(requested, MAX_RADIUS));
```

The parent rev `3927924^` (`eb5498f`) line 90 defaulted to 512; `8c7c12f`
defaulted to 256. It is back to 512, now as a named constant rather than a
literal buried in a ternary. `MAX_RADIUS` is still 1024, so an **explicit**
radius may still reach 1024 — only the unset default stops at 512. That is the
right shape: the clamp ceiling is unchanged, the default is restored.

`tickExpanding:361` is unchanged from `8c7c12f`, and with `maxRadius` back at 512
it stops at the first shell that does not grow — 512. So the walk is
32/64/128/256/512, terminating at 512, never reaching `SHELL_RADII`'s 1024. I
re-derived this from the code rather than from the commit message.

Cell counts, from the rev's own enumeration `(2r/16 + 1)^2`:

| rev | no-radius max | shells | cells |
|---|---|---|---|
| `eb5498f` (parent) | 512 | 32,64,128,256,512 | 25+81+289+1089+4225 = **5709** |
| `8c7c12f` (defect) | 256 | 32,64,128,256 | 25+81+289+1089 = **1484** |
| `7d95aeb` (fixed) | 512 | 32,64,128,256,512 | **5709** |

## The spec is narrowed correctly

At `43c03c9` the requirement paragraph is back to its original text — "the
supplied value MUST be clamped between a floor of 1 and a ceiling"; "When no
radius is supplied at all the behavior MUST keep today's starting radius and
escalation unchanged". The intent was always right; the code was what violated
it, and the fix belongs in the code. Adding a ceiling clause to the requirement
would have rewritten the intent to match the defect.

The `No radius keeps today's behaviour` scenario now reads:

```
- AND escalation proceeds 32 -> 64 -> 128 -> 256 -> 512, with a default ceiling of 512
```

which matches the code and the 5709.

`openspec validate wide-search-radius --strict` at `43c03c9` in an archived tree
holding the rev: **rc=0, "Change 'wide-search-radius' is valid"** (unpiped).

Adjacent agent suites at the rev, `AGENT_SCRIPT_RUNNER` set:
`test_planner_prompts`, `test_planner_script_output`, `test_l3_script_path`,
`test_l3_path_per_bot` → **Ran 129, OK, rc=0**.

## F-1: task 4.4 is ticked against a test that cannot observe the failure message

Task 4.4 reads "Failure message states the searched radius, not 32" and is
`[x]`. The test backing it,
`the_failure_message_reports_the_searched_radius_not_the_unclamped_shell`, never
calls `tickExpanding` — where the message is built. It calls
`resolveMaxRadius` and then applies its **own** copy of the expression:

```java
private static int searchedRadius(int shellRadius, int maxRadius) {
    return Math.max(Math.min(shellRadius, maxRadius), 0);
}
```

That is character-for-character production's line 370 (`Math.max(currentRadius, 0)`
on the clamped shell), re-derived. The producer of the string is never executed,
and no `progress.setFailureReason(...)` call is asserted.

The only production symbols the test references, enumerated from the file:

```
3  WideSearchBehavior.DEFAULT_RADIUS
16 WideSearchBehavior.resolveMaxRadius
```

`tickExpanding` appears three times, all three in comments. So the mutant the
task exists to kill — reverting line 370 to `prevRadius` — is **undetectable** by
this test by construction, not by luck.

The builder raised this themselves and offered to untick it. **My answer is
untick it.** The honest tick is not `[x]` for "the failure message states the
searched radius"; it is `[ ]` with the reason "code reviewed by inspection;
untestable without the mod suite, because the harness cannot instantiate
`BotPlayer`/`progress`". A green box that stands for an assertion nobody made is
worth less than a red one that says why.

What the test *does* earn, and should keep: it pins `DEFAULT_RADIUS == 512` and
the whole 32..512 walk with 5709 cells. That is the regression I missed, and it
reds correctly — see below.

### Mutants, both run

Neither mutant could be run through the real suite on this VM (no wrapper jar in
the worktree, no `libs/`, no system gradle — the builder declared this honestly
and I confirmed it: `javac` against the cache fails before type-checking). I
evaluated the test's assertions against both mutants using the test's own
helper definitions, ported literally.

- **M-2, `DEFAULT_RADIUS` 512 → 256** (the regression): reds **4** assertions —
  `max==512` (got 256), `shells==5` (got 4), the walk (got `[32,64,128,256]`),
  and `cells==5709` (got 1484). This is the mutant that matters, and the test
  kills it.
- **M-1, production line 370 → `int searchedRadius = prevRadius;`** (the mutant
  4.4 exists to catch): **no assertion changes.** The test never calls
  `tickExpanding`, so it cannot see this mutant at all.

Both mutants were applied behind an `assert old in src` anchor, so a no-op
mutation would have failed loudly rather than reading as a survivor.

## F-2: task 2.2 is ticked while describing the regression

```
- [x] 2.2 Keep the default path byte-identical: no radius means 32 first shell, escalation to 256
```

"escalation to 256" **is** the defect — the pre-fix default. The box says
"byte-identical" and then specifies a behaviour that was not the pre-change
behaviour. Whoever audits this change later against its own task list will read
that as the intended default. It must read "escalation to 512", matching the code
and the corrected scenario.

Adjacent: **4.5** says "mutant: 4 of 5 assertions red, incl. 4 blocks -> 25
cells". That mutant is the *parse* mutant (top-level-only), not the default
mutant, and "4 of 5" conflates assertions with tests — the parse mutant reds 4 of
9 tests. The number is not wrong for its own mutant, but it is stale relative to
the change this task now protects. Reword to name which mutant reds which count.

## What I got wrong, recorded

My `c78c2d4` review passed this change. I verified `8c7c12f`'s arithmetic
against itself — I computed the default walk from `MAX_RADIUS` at the *new* rev
and reported "1089 cells, unchanged" without ever opening `3927924^` to ask what
the default used to be. Requirement 2 is precisely a claim about the parent rev,
and it was the one rev I did not read. The lead caught it.

The lesson is narrower than "check the parent": the spec scenario I pronounced
"structurally sound" contained the wrong ceiling in the very line I quoted back
as matching. I checked that the scenario existed and was well-formed, not that
its numbers were the pre-change numbers.

## Not established

No mod-suite run (no wrapper jar, no `libs/` — an absence, not a pass, same as
the builder reported). Nothing on the cluster, no live bot, not deployed. The
two mutants above are model-level evaluations of the test's assertions, not JVM
executions; they establish which assertions would fail, not that the suite
compiles.
