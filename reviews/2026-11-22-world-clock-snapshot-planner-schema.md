# Review: real world time in the script snapshot + real schema in planner prompts

Row: qitem-20261122154628-d29bde686ddad5c9
Builder row: qitem-20261122151655-c05ac3625e87bf7d
Revs: neoforge-ai-player `8107fb1`, `60a2043`, `8e72c05`; agent-script-runner `3037311`, `05f0ded`
Reviewer: minecraft-reviewer. Read-only: nothing built, pushed, applied or deployed.
Date: 2026-11-22

> **Supersession note (added 15:52Z).** F-1 was accepted and fixed by rewording
> the `8e72c05` commit message; that commit is now **`f57ec62`**, with an
> identical tree (`89982b1`, verified by `rev-parse` and an empty tree-to-tree
> diff) and the same parent (`60a2043`). Every `8e72c05` cite below is
> historically true — the tests were run at that sha — but `8e72c05` is no
> longer on the branch. Read `f57ec62` for the current content. The corrected
> message now spells out that a script tests `s.state.world.day_time === null`,
> never `s.state.world === null`. The archive commit is `db809a3`.

## Verdict: PASS, with one documentation finding (F-1) and one gap I could not close

The shipped behaviour is correct on every check the row asks for. One prose
statement overstates the shape of `state.world`; it reaches no script and no
prompt, so it does not block the ship, but it should be fixed before someone
writes a script against it.

## What I ran, at the named revs

| Target | Result |
|---|---|
| agent `8e72c05`: `python3 -m unittest test_snapshot test_l3_script_path` | **131 tests, 0 failures, rc=0** |
| runner `05f0ded`: `node --test test/engine.test.mjs` | **58/58 pass, 0 fail, rc=0** |
| fixture provenance (`test_envelope_fixture`, runner visible) | **passes** paired; **FAILED (failures=1)** when I tampered the fixture |
| `openspec validate script-lookups-and-results --strict` at `8e72c05` | **valid, rc=0** |
| Java `WorldTimeTest` | **NOT RUN at review time — see F-2; RUN 15:57Z at `f57ec62`: 8 tests, 0 failures, rc=0** |

Every command ran bounded (`ulimit -v 4194304`; Node `nice -n 19` with
`NODE_OPTIONS`), and each tree was a detached worktree at the named rev, not the
builder's tree.

## Check 1 — Java clock, refresh, and the serializer: PASS

- `BotPlayer.dayTimeOf` is `Math.floorMod(raw, 24000)`, so a level up for days
  reports 0..23999. `isNightOf` is `>= 13000 && < 23000`.
- **Refresh freshness:** `refreshCache()` runs at `tickCounter % 40 == 0`
  (BotPlayer.java:532) and rebuilds `cachedStatus = getStatus()`. So `day_time`
  / `is_night` are at most 40 ticks (~2 s) stale — far inside any boundary a
  script compares against.
- **The endpoint carries the keys — traced, not assumed.** `getStatus()` puts
  `day_time` and `is_night` into the map; `refreshCache` stores it in
  `cachedStatus`; `getCachedStatus()` (BotPlayer.java:669) is served by
  `HttpApiServer.java:346` (`case "status"`) and `:299` (bot list). Both go
  through `sendJson`, which is `serializer.toJson(data)` with no allow-list, so
  the keys reach the wire. The agent calls `api.status(bot)` =
  `GET /bot/{bot}/status` (agent/api.py:98). The chain is closed end to end.
- `is_night` describes the overworld cycle only; the Nether/End caveat is stated
  honestly in the code comment rather than silently wrong. Acceptable.

## Check 2 — `state.world` when absent: code correct, prose wrong (F-1)

The row asks that `state.world` be null when absent. **The shipped behaviour is a
dict of Nones, not null:** `build_state` always emits
`world = {"day_time": status.get("day_time"), "is_night": status.get("is_night")}`,
and `test_an_older_mod_gets_none_not_an_invented_clock` asserts
`state["world"] == {"day_time": None, "is_night": None}`.

This is **correct against the spec**, whose requirement body says the agent
"MUST carry both into `state.world` as `{day_time, is_night}`" — a nested object,
with the individual fields null. The prompt is also correct: it documents
`s.state.world.day_time // int 0..23999, or null`.

**F-1 (documentation).** The *description* of this, in three places, says the
object itself is null when absent — which contradicts the shipped shape and the
test beside it:
- the commit message of `8e72c05` ("...`{day_time, is_night}`, null when the mod
  does not send it"),
- the builder's own row resolution ("state.world = {day_time, is_night}, null
  when the mod does not send it"),
- (the code comment at snapshot.py:112 is fine — it says the *fields* are
  `None`.)

A script author who reads "world is null when absent" and writes
`s.state.world === null` takes the wrong branch, because the object is always
present. Not a shipped-behaviour defect; a claim that travels. Fix the two prose
sites to say "the fields are null when absent" and keep the shape as-is.

## Check 3 — planner prompts teach the real schema: PASS

- `_SNAPSHOT_SCHEMA` is the single source; both prompts substitute it as a value
  (`.replace`, not `.format`, because the JS braces are single and a `.format`
  would raise or leak). `test_a_fenced_block_is_extracted` and the
  `test_the_placeholder_never_survives` test pin the render.
- **The schema matches the real envelope.** I built the envelope from
  `snapshot.build_envelope` and walked its paths: every field the prompt names
  (`tick`, `server_ms`, `state.{health,food,position,inventory,nearby.blocks,nearby.mobs,world.day_time,world.is_night}`, `task`) exists at the path
  the prompt gives; `[] missing named fields`. Envelope top keys are
  `['events','server_ms','state','task','tick']`, exactly as the prompt says.
- **No fictional field survives.** All field references in `l3_planner.py` are
  `s.state.*`; the only `s.self`/`s.bots` occurrences are the explicit "there is
  no s.self" negatives (lines 454-455, 483).
- **The placeholder test is real**, not a re-encoded shadow: it renders through
  production's `render_plan_prompt(...)` and asserts the literal
  `{snapshot_schema}` never survives.

One thing the row asked me to check that the tests do **not** prove and I
verified by hand: the prompt names `s.state.nearby.blocks` and
`s.state.nearby.mobs`, and `build_state` produces `nearby.{blocks,mobs}` — I
confirmed both exist in a real envelope, so those two are correct too.

## Check 4 — no spec'd behaviour removed: PASS

The only deletions in `l3_planner.py` are the fictional
`s.self, s.bots, s.inventory` schema lines and their broken `{{...}}` inline
rendering; the two `script_section=_PLAN_SCRIPT_SECTION if offered else ""` /
`script_surface=...` lines are the `.format`→`.replace` conversion, not removed
behaviour. Nothing spec'd is dropped.

The spec delta `8107fb1` + `60a2043` adds the 'A Script That Needs The World
Clock MUST Read It From The Snapshot' requirement and its scenarios. It did not
remove a scenario. `openspec validate script-lookups-and-results --strict` at
`8e72c05` is valid, rc=0 (run by me; rev printed in the same command).

## F-2 — I could not run the Java tests (gap, not a finding against the code)

There is no `gradle-wrapper.jar` in either checkout (the wrapper's
`gradle-wrapper.properties` is present; the jar is gitignored and absent),
and no system `gradle` on PATH. I therefore **could not execute
`WorldTimeTest`**. What I did instead:
- verified the boundary arithmetic independently (10000 night ticks, exactly one
  window per cycle, correct bounds, `floorMod` behaviour) — matches the test's
  assertions;
- verified the builder's mutant claim: replacing `>= 13000` with `>= 0` flips
  `{0,1,1000,6000,12000,12999}` and so kills exactly `sunriseIsNotNight`,
  `daylightIsNotNight`, `theNightWindowIsTheLengthVanillaUses`, and
  `exactlyOneNightWindowPerDayCycle` — **4 of 8, as claimed**.

This is a real gap in the review: the Java test was not run by me. I am reporting
it as scoped absence, not as a pass. If the builder ran it (they report
`BUILD SUCCESSFUL` 8/8), the code reading above stands behind it.

## F-3 — the full agent suite was not reproduced

`openspec validate script-lookups-and-results --strict` I did run at `8e72c05`:
`Change 'script-lookups-and-results' is valid`, rc=0.

I ran the two affected agent suites (131 tests) and the runner suite (58), not
the full 694-test agent suite. The 694 figure is the builder's; my checks cover
the changed behaviour, not the whole tree.

## The fixture (3037311): PASS, and the provenance gate is real

`envelope-from-producer.json` at `05f0ded` carries
`state.world = {day_time: 18000, is_night: true}` consistent with `tick: 1`. The
provenance test in the agent repo **runs and passes** when the runner is beside
it, and **reddens** (`FAILED (failures=1)`) when I changed the fixture's
`day_time` to 19999 — so it is a gate, not an inert check. Restored clean after.

## Note on two prose slips the lead flagged

Confirmed and not carried: the Java test file is `WorldTimeTest`, not
`BotPlayerTimeTest`; and the `13000` boundary assertion lives in
`duskToDawnIsNight` (`isNightOf(13000)` true), not in a separate test named for
the boundary. Neither affects the verdict.

## Bottom line

Ship it. F-1 is a two-line prose fix ("the fields are null", not "the object is
null") that should go in before a script is written against the wrong shape;
F-2 is my honest gap — the Java test exists, reads correctly, and I checked its
arithmetic but could not run it here.

## Update 15:57Z — F-1 closed, F-2 closed

**F-1:** fixed by the builder in `f57ec62` (message-only rewrite of `8e72c05`;
identical tree `89982b1`, same parent `60a2043`, empty tree-to-tree diff). I
re-read the shipped text at `f57ec62`: every `state.world` occurrence refers to
the field (`l3_planner.py:478-479,484`). No surviving object-is-null claim.
The builder row's resolution text is immutable, so the correction lives in its
transition log (15:51:56Z), which I read.

**F-2 is no longer a gap — I ran it.** The Java tests are executable without a
wrapper jar via the cached distribution:
`~/.gradle/wrapper/dists/gradle-8.14-bin/.../gradle --offline --no-daemon
-Dorg.gradle.jvmargs=-Xmx2g --max-workers=2 test --tests
com.sigmastrain.aiplayermod.bot.WorldTimeTest`, in a detached worktree at
`f57ec62`. Result: **tests=8, failures=0, errors=0, skipped=0, gradle rc=0**
(JUnit XML `TEST-com.sigmastrain.aiplayermod.bot.WorldTimeTest.xml`).

The eight executed cases are the real boundary set, not trivial ones:
`duskToDawnIsNight`, `daylightIsNotNight`, `dawnIsNotNight`,
`dayTimeIsReducedModulo24000`, `dayTimeIsNeverNegativeOrOutOfRange`,
`sunriseIsNotNight`, `exactlyOneNightWindowPerDayCycle`,
`theNightWindowIsTheLengthVanillaUses`. `sunriseIsNotNight` and
`theNightWindowIsTheLengthVanillaUses` are the two the prod bug turned on.

**First attempt was a dead instrument and I record it:** I ran
`--tests '*WorldTimeTest*'` in this worktree while it was still on my own
branch `c78938a`, which predates the test. Gradle printed "No tests found for
given includes" and BUILD FAILED — a wrong-tree artefact that reads exactly like
a test failure. Re-run at the reviewed rev it passes. This misread is itself
part of the harness gap filed as `qitem-20261122155352-7c1a7aae94f9133e`.
