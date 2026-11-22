# Review: 7e72410 — refuse GOTO/TELEPORT without coordinates; test every required-field row

Reviewer: minecraft-reviewer@minecraft. Reviewed at **7e72410** (parent `21b2ec4`,
confirmed), on `minecraft-wt-deepseek`, not at my branch HEAD.

Verdict: **PASS**, with two notes (neither a blocker).

## Spec
`openspec validate script-lookups-and-results --strict` rc=0. The delta adds the
coordinate scenarios; the four the row describes are present, plus the BUILD
exemption and "a zero coordinate is a coordinate".

## The rule — VERIFIED by driving it
    GOTO {}                     -> refused: needs coordinate 'x' as a number; ... (got [])
    GOTO {x:0, y:64, z:0}       -> BOUND
    TELEPORT {}                 -> refused
    BUILD {target:'shelter'}    -> BOUND
    MINE  {target:'...'}        -> BOUND

`_missing_coords` refuses an absent or non-number coordinate, excludes `bool`
(Python counts True as int — `{"x": true}` would otherwise bind as 1), and
treats numeric 0 as a real coordinate, so a bot can still be sent to x=0.

## The source-anchored pin — VERIFIED it bites
`test_the_table_matches_every_unguarded_reader` parses BehaviorFactory (not a
hard-coded map), brace-matches `if (hasLocation()) { ... }` spans so multi-line
guards count, and requires each excluded class to carry a written reason.

Mutant, driven: adding `double mutantZ = directive.getZ();` to
`ContainerStoreBehavior.start()` reds it with a diagnostic naming
CONTAINER_STORE and the offending line. My FIRST mutant — an unguarded read in
`BuildBehavior` — SURVIVED, correctly: BUILD is in `_ZERO_MEANS_FALLBACK`, so
the scanner skips it before comparing. That is the documented semantics, not a
defect. (I nearly filed "the pin is inert"; it is not.)

Coords-join prompt mutant (drop the `BINDABLE_KINDS` filter) reds exactly
`test_removing_a_coordinate_kind_removes_its_prompt_line`, rc=1. The builder's
account of why that test had to be added is accurate — the join filters nothing
while every coordinate kind is bindable, so without the removal probe it could
be deleted silently.

Both mutated Java files restored, `sha256sum` verified, `git status` clean.

## Suites (exactly what I ran — not the builder's invocation)
`test_action_binding` + `test_script_prompt_kinds`: **51 tests OK rc=0.**
`discover -s agent -p 'test_*.py'`: **84 tests, 1 error, 0 failures rc=1.**
The single error is `dashboard` -> `ModuleNotFoundError: No module named
'uvicorn'`, independently confirmed (`import uvicorn` fails) and this commit
touches no dashboard file. Environmental, not this change.

The builder reported 543 discovered from their own invocation; agent/ holds 8
`test_*.py` modules, so `discover -s .` cannot reach that number from here. I am
NOT claiming to have reproduced 543 — I verified the two changed modules in full
and every other module in `agent/` in discovery, all green but for the uvicorn
import.

## Notes
1. **NaN/Infinity bind.** `_missing_coords` accepts any non-bool `int`/`float`,
   so `float('nan')`, `inf`, `-inf` bind. Reachable: `planner.py:404` calls
   `json.loads` with default `parse_constant`, which accepts `NaN` from a model
   reply, and there is no `allow_nan=False`/`parse_constant` guard on ingress.
   Downstream effect is likely a rejected move rather than a wedge, but it is
   the same class of "garbage reaches the mod" this change exists to stop.
   Suggest `math.isfinite` beside the bool check, or a decision that it is out
   of scope.
2. **`_ZERO_MEANS_FALLBACK` is a blind spot by design.** An unguarded read
   inside an excluded class is invisible to the pin. That is correct for BUILD
   today, but if a second class is added to the dict without the same
   zero-means-here semantics, the pin will not notice. The written-reason
   requirement is the real control; keep it enforced.

## Judgement calls answered
- **TELEPORT as never-valid-without-coordinates: agreed.** `TeleportBehavior`
  reads `targetX/Y/Z` unconditionally and calls `bot.teleport` /
  `teleportToDimension` with them — there is no zero-means-fallback branch.
  Zero sends the bot to origin, including across dimensions, which is the worst
  form of this bug rather than a feature. Keep it in the table.
- **BUILD excluded: agreed**, verified at `BuildBehavior.java:99-107`.

## My own instrument failures this review
- Read `--tests`-filtered gradle output and a `tail` summary that reported the
  pipe's status; used the runner's own summary lines and direct rc.
- First mutant survived for the documented exclusion reason; nearly reported the
  pin as inert before reading the exclusion dict.
