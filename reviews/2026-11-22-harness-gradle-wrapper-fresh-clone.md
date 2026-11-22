# Review — make the Java test suite runnable from a fresh clone (71f6199)

Row: `qitem-20261122160711-e32e2231`
Branch: `ship-ca27-harness` (not pushed)
Reviewed rev: `71f6199` (parent `db809a3`)
Reviewer ran from: a real `git clone` of the branch at `71f6199` in `/tmp/clone-71f6199`, with **no `libs/` directory**, plus detached worktrees elsewhere.

## Verdict: PASS

The row's central claim — that `./gradlew test` runs from a fresh clone — is proven
end-to-end here, and the result is stronger than the row claimed: the **whole** Java
suite runs, not only the targeted class.

## What I verified myself, at 71f6199

### The wrapper jar is real and is what it says
- `sha256(gradle/wrapper/gradle-wrapper.jar)` at `71f6199` =
  `7d3a4ac4de1c32b59bc6a4eb8ecb8e612ccd0cf1ae1e99f66902da64df296172` — matches the
  builder's claim byte for byte. Computed from `git show 71f6199:...`, not from a
  working tree.
- It is a tracked blob (`100644`), and `gradle-wrapper.properties` is byte-unchanged
  by the regeneration (`git diff 71f6199^ 71f6199 -- gradle/wrapper/gradle-wrapper.properties`
  is empty). Confirmed it sets no `distributionSha256Sum`, as the builder stated.
- A sha match is provenance, not function, so I opened the jar: 33 entries, a real
  manifest with `Main-Class: org.gradle.wrapper.GradleWrapperMain`, and
  `GradleWrapperMain` present. It is a genuine Gradle wrapper, not a stub.

### The fresh-clone proof, reproduced
A genuine clone (`git clone --no-local`, checkout `71f6199`, `libs/` absent):

```
./gradlew test --tests '*WorldTimeTest*' --rerun-tasks --no-build-cache
> Task :test
BUILD SUCCESSFUL
```

and the JUnit XML — not the console line, which TESTING.md rightly says to distrust —
gives `tests="8" skipped="0" failures="0" errors="0"`. The eight are the real boundary
set: `duskToDawnIsNight`, `daylightIsNotNight`, `dawnIsNotNight`,
`dayTimeIsReducedModulo24000`, `dayTimeIsNeverNegativeOrOutOfRange`,
`sunriseIsNotNight`, `exactlyOneNightWindowPerDayCycle`,
`theNightWindowIsTheLengthVanillaUses`.

I also ran the **whole** suite unfiltered from the same clone: `Task :test`,
`BUILD SUCCESSFUL`, and the XML tally across all ten classes is
**tests=83 skipped=0 failures=0 errors=0** (`BoundedHandlerTest` 4, `BoundedWaitTest` 9,
`HealthProbeListenerTest` 5, `TickHeartbeatTest` 25, `NearbyBlockIndexTest` 8,
`WorldTimeTest` 8, `BotBrainApplyDirectiveTest` 3, `GotoLiftTest` 7,
`MineBehaviorTargetTest` 3, `WideSearchRadiusTest` 11). So the repo's Java suite is now
runnable for a fresh reader in full, which is more than the row set out to do.

### The `libs/` claims hold
- `grep -c libs build.gradle` = 0, and neither `build.gradle` nor `settings.gradle`
  references a `libs/` directory.
- `libs` does not appear in `.gitignore` at all. The project brief's "`libs/` jars are
  gitignored but were copied over" does **not** describe this repo; the TESTING.md
  section is accurate and I verified the absence from the clone.
- TESTING.md's own suggested check `git ls-files "*WorldTimeTest*"` works and returns
  `src/test/java/com/sigmastrain/aiplayermod/bot/WorldTimeTest.java`. The mitigation
  is exercised, not merely written.

### The scope correction is correct
The builder volunteered that tracking the jar removes the *cause* of my earlier misread
(the class is now always present) but **not** the reading hazard: a `--tests` filter that
matches no class still prints `No tests found for given includes` and `BUILD FAILED`,
indistinguishable in colour from a real regression. I accept that scoping. It is the
honest description of what this row buys, and TESTING.md is the durable mitigation.

I could not reproduce the builder's `failOnNoMatchingTests` experiment from the branch,
because a cleanly reverted attempt leaves no trace — no revert commit and no
`failOnNoMatchingTests` in `build.gradle` at `71f6199`. That is consistent with the
account but is not independent confirmation of the byte-identical-output measurement.
Recorded as unverified, not contradicted.

## Findings

**F-1 (withdrawn — I was wrong).** I first wrote that the hazard line in TESTING.md
was quoted with a trailing `(--tests filter)` that Gradle would not print. I then ran it
instead of resting on that:

```
./gradlew test --tests '*NoSuchTest*' --rerun-tasks
rc=1
> No tests found for given includes: [*NoSuchTest*](--tests filter)
BUILD FAILED in 8s
```

The builder's literal is **byte-exact**, including the parenthetical. My finding was
wrong and is withdrawn; the quoted line, the advice around it, and the `BUILD FAILED`
claim all reproduce. What this run does confirm is the scope point: a filter matching
nothing exits 1 and prints `BUILD FAILED`, the same as a real regression, so the
reading hazard is real and TESTING.md is the right mitigation.

**F-2 (information for the lead). The project brief is wrong about `libs/`.** The brief
says "`libs/` jars are gitignored but were copied over; do not delete them." In this
repo `libs/` is neither gitignored nor present, and the Java tests do not use it. Not
this row's defect, but a culture document other seats read, so it should be corrected
where it lives rather than only in TESTING.md.

## Not done, stated plainly

- Nothing pushed, nothing applied to the cluster — read-only plus a scratch clone.
- I did not independently reproduce the `failOnNoMatchingTests` measurement (see above).
- I verified the hazard message byte-form directly (see F-1) and found the builder's
  quoted line exact; my initial objection to it was wrong.

## Repro

```
git clone --no-local --branch ship-ca27-harness <repo> /tmp/clone-71f6199
cd /tmp/clone-71f6199 && git checkout 71f6199
nice -n 19 ./gradlew test --rerun-tasks --no-build-cache --max-workers=2 \
  -Dorg.gradle.jvmargs=-Xmx2g
# then read build/test-results/test/TEST-*.xml for tests= / skipped= / failures= / errors=
# NOT the console "BUILD SUCCESSFUL", and never a FROM-CACHE run.
```
