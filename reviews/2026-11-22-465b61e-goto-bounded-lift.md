# 465b61e — GOTO bounded lift, enclosed fails, arrival reported

Rev reviewed: `465b61e` on `ship-ca27-harness` (parent `039143d`, which this
commit contains). Reviewer: minecraft-reviewer@minecraft. 2026-11-22.
Worktree: `/home/sigmastrain/minecraft-wt-qwen/neoforge-ai-player`, detached at
`465b61e`.

**Verdict: PASS on the lift bound and the enclosed failure. The arrival channel
is NOT wired for scripts — the commit's replacement for trial 4.3 cannot pass.**
That is finding F-1 below and it is the reason this is not a plain PASS: the
prompt now tells a planner to write its arrival check against `adjusted_to`,
which no script can read.

## What holds, verified at this rev

- **The lift is genuinely bounded.** `decideLift`
  (`GotoBehavior.java:122-133`) tests `lift = 0..GOTO_MAX_LIFT` inclusive and
  returns `enclosed` past it. `GOTO_MAX_LIFT = 3` (`:35`). The pre-fix loop it
  replaces (`039143d`, `:42-48`) had no bound: `while (targetY <
  level.getMaxBuildHeight() - 2)`. So "unbounded to the build limit" is the
  true pre-fix state, not a reconstruction.
- **Mutant A (unbind the lift: `GOTO_MAX_LIFT` 3 → 256) reds exactly the two
  tests that name the bound**, by name: `the_lift_is_bounded_so_it_never_searches_to_the_surface`
  and `a_target_buried_one_past_the_bound_is_unreachable`. 6 tests, 2 failures,
  4 pass. Reproduces the builder's claim ("reds 2 by name").
- **The enclosed failure returns before any movement.** `start()` sets
  `targetEnclosed` and returns at `:63-69`; `tick()` refuses at `:136-140`
  before the distance/teleport logic at `:171`. An enclosed target can no
  longer be walked, climbed or teleported to, which is the trial 4.2 defect.
- **The prompt drift pin bites.** Mutant B — the prompt says "lifted up to 5
  blocks" while the Java says 3 — reds `test_the_prompt_lift_bound_matches_the_mod`
  with `'lifted up to 3 blocks' not found`. The pin reads the constant out of
  `GotoBehavior.java` rather than restating it, so it cannot drift silently.
- **Tests run, not cached.** `:test --tests '*GotoLiftTest*' --rerun-tasks
  --no-build-cache --offline` → `BUILD SUCCESSFUL in 29s`; JUnit XML
  `tests=6 failures=0 errors=0 skipped=0`. Six named cases, not a count taken
  from the console.
- **Agent prompt module:** `test_planner_script_output` 14 tests, OK, rc=0.
- **`openspec validate script-lookups-and-results --strict` rc=0**, "Change is
  valid", read unpiped.
- The self-reported defect (the first `arrived_at` was a comma-joined
  `String.format("%.1f, %.1f, %.1f")`) is genuinely gone from this rev:
  `arrived_at` is `Map.of("x", …, "y", …, "z", …)` at `:148-152`, and
  `adjusted_from`/`adjusted_to` are `{x,y,z}` maps at `:75-84`.

## F-1: a script cannot read `result` — `adjusted_to` and `arrived_at` never reach it

The requirement says an adjustment "is only acceptable when it is bounded AND
reported", and the prompt now instructs the planner to "Write an arrival check
against `adjusted_to`… never against the coordinates you asked for." I traced
the channel end to end at this rev. It is wired for the *planner* and not for a
*script*:

1. **The mod does emit it.** `ProgressReport.toMap()` puts the results under
   `"result"` (`ProgressReport.java:86`); `BotBrain.toMap()` nests that under
   `"progress"` (`BotBrain.java:180-188`); `GET /bot/<name>/directive` returns
   `bot.getBrain().toMap()` (`HttpApiServer.java:1336-1339`). `api.get_directive`
   (`agent/api.py:43-45`) is that route, and `snapshot.py:65,76` puts it in
   `state.task`/`envelope.task`. **So a script can see `result` — one tick
   late, and only if it looks at an old directive.**
2. **The action's own reply does not carry it.** `api.do` returns `{ok, seq}`
   (`binding.js:324`, and the prompt says so); the runner never sees the mod's
   progress. So a script cannot read the result of the action it just issued.
3. **The agent discards the structured half.** `_l3_orchestrator_dispatch`
   reads `prog["result"]`, then passes only the *formatted line*
   `COMPLETED GOTO {counters} result={...}` onward (`agent.py:1404-1415`). The
   **dict is dropped**: `_record_finding` consumes only LOCATE-shaped results
   (`:1138-1149`), so a GOTO result is discarded. What reaches the next script
   tick is `snapshot.task` = the directive `toMap()` — id, type, status, x/y/z —
   with **no `progress` key** (`Directive.java:59-73`). The progress map exists
   only on the `/directive` **status** route, which is a different call from the
   `get_directive` the snapshot uses.

**Why this is the trial 4.3 case, not a nicety.** The prompt's two arrival-check
options are `adjusted_to` (unreachable, above) and `look.self().position`.
Consider the case `adjusted_from` exists to describe: target buried 1–3 blocks,
lifted, bot arrives. GOTO completes at `y+1`; the marker block the script is
looking for sits at `y`. A check written against `look.self().position` and the
*requested* coordinates then never passes — while the prompt now tells the
planner **not** to compare against the requested coordinates, without offering
anything that works. For an un-lifted target the prompt's advice is fine. For a
lifted one it is a trap.

**Likely what trial 4.3 actually is:** issue GOTO, arrive, but keep re-issuing
because the script's arrival check does not agree with where it is. Bounding the
lift removes the 36-block case. It does not give the script a key to the held
position.

**Fix direction (one place, no protocol change).** The bounded-and-reported
promise needs a script-visible read. The cheapest honest route: put
`progress` (or just its `result` map) on the directive `toMap()` the snapshot
already serves, keyed so the script can tell which directive it belongs to —
`Directive.toMap()` already carries `id` and `status`. `api.get_directive`
would then return it one tick later, which is exactly the "verify on a later
tick" pattern the prompt already preaches. Alternative: surface the last
directive result in `snapshot.state` (the `events` field is defined for this and
is currently empty). Either is a small change; both need a test that a script
can *read* the value, in the run's own shape, not one that a dict exists
server-side.

## Not established, and I am not implying otherwise

- **`arrived_at` has no test.** The builder says so: it lives in `tick()`, needs
  a live `Level`, and the mutant removing it survives. I reproduced the survival
  by reading, not by running — I did not run a Java suite over `GotoBehavior`
  with that `putResult` removed, because the cost (recompiling the mod test
  source set) bought a result the builder already stated. The shape is right;
  its delivery is not covered (F-1).
- **No movement, teleport or end-to-end was observed.** The 64-block teleport
  branch (`:171`) does consume the bounded `targetY`, and the enclosed case
  returns before it — that much is read, not run.
- **`scripts.test` for the runner repo was not run** — this commit changes no
  runner file, and the runner is at `b4e773d` (the rev this seat cleared
  earlier).

## Smaller observations, all read (no verdict)

1. **`GOTO_MAX_LIFT` is documented by arg, not by constant.** `decideLift` takes
   `requestedYForMessage` only to name the requested Y in the enclosed message
   — a parameter that exists solely for a log string. Harmless, but a cleaner
   signature would pass the `BlockPos` and read `getY()` from it; the caller
   already has one (`:57`). Not a defect.
2. **The timeout path reports a moved target.** `MAX_TICKS` failure
   (`:159-162`) leaves `targetEnclosed == false`, so the status line still says
   "Moving to <lifted>" (`describeState`, `:226-228`) and the failure reason is
   only `"Timed out after 600 ticks"`. A script showing that line will believe
   the bot was going where it asked. This is the same *class* as trial 4.2 at a
   lower stake — one sentence in the reason would close it ("…while aiming at
   the lifted (x, y, z); requested (x, y, z)"). Not blocking.
3. **Spec wording outruns the result.** The spec says "the COMPLETED result MUST
   carry the actual arrival position and an `adjusted_from` field". The code
   puts `adjusted_from`/`adjusted_to` in `start()` and `arrived_at` in `tick()`,
   so a target never lifted yields neither adjustment field. The spec sentence
   is conditional on "When the target IS lifted" in the paragraph above it, so
   it is arguably correct — but the capitalised MUST reads absolute. Align the
   wording with F-1's fix.

## How this commit reads overall

The core diagnosis is right and the fix is the right shape: a pure function, a
named bound, a failure with the requested coordinates in it, and a pre-brain
prompt. The two mutants I ran behave as the builder said. What is missing is
the half the requirement itself calls out — *reported* — reaching the only
reader that matters for a script. Fix F-1 and this is a clean PASS.
