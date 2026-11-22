# F-1 fix: a script can read its GOTO's result — PASS, one stale cite

Revs reviewed: `neoforge-ai-player` `9ddfdef` (agent + mod + spec),
`agent-script-runner` `148e459` (runner).
Reviewer: minecraft-reviewer@minecraft. 2026-11-22.

`9ddfdef` was checked out in the mod worktree for every read below;
`148e459` in the runner worktree. Both worktrees restored afterwards
(mod at `9ddfdef` detached, runner at `b4e773d`).

## Verdict

**F-1 is closed.** The finding was that `GotoBehavior` emitted `arrived_at`
and `adjusted_from`/`adjusted_to` correctly while no script could read them,
so `SCRIPT_SURFACE` sent a planner to a field that did not exist. That is now
fixed end to end, and I reproduced the seam rather than accepting two
hand-built fixtures.

The one new finding (F-2, below) is a stale line cite in the spec text. It
does not affect behaviour.

## The seam, driven for real

The honest risk in this fix is that the Python fixture and the runner fixture
agree with each other while both disagree with the Java producer — the
fixture-must-come-from-the-producer failure this repo has hit before. So I
fed Java-shaped values through the real functions:

    $ git show 9ddfdef:.../GotoBehavior.java   # the emitted shapes
    putResult("adjusted_from", requested)     # LinkedHashMap<String,Object>
    putResult("adjusted_to",   adjusted)      # of Double
    putResult("arrived_at", Map.of("x", ...)) # Math.round(p*10.0)/10.0

    $ python3 -I  # build_state -> build_envelope -> freeze, real modules
    CHAIN-OK: status, arrived_at, adjusted_to all survive build_state+freeze

The frozen bytes were then handed to the runner's own `createLook`, the same
code path the sandbox evaluates:

    $ node /tmp/seam.mjs     # input: the frozen envelope, not a fixture
    {"ok":true,"id":4711,"type":"GOTO","status":"COMPLETED",
     "result":{"adjusted_from":{"x":10,"y":64,"z":10},
               "adjusted_to":{"x":10,"y":65,"z":10},
               "arrived_at":{"x":10.1,"y":65,"z":9.8}},
     "phase":"done","failure_reason":null}
    SEAM-OK

`arrived_at.y` is 65 while the requested `y` is 64 — the lifted case, which
is exactly the comparison that used to re-issue forever. A script can now
tell arrival from request.

## What I ran

| Check | Result |
|---|---|
| `GotoLiftTest`, `--rerun-tasks --no-build-cache` | JUnit XML `tests="7" failures="0" errors="0"`, `BUILD SUCCESSFUL`, executed not cached |
| `test_snapshot` + `test_planner_script_output` | `Ran 44 tests … OK`, rc=0 |
| `look-engine.test.mjs` (declared glob form) | `# tests 21 # pass 21 # fail 0`, rc=0 |
| `openspec validate script-lookups-and-results --strict` | rc=0, "is valid", run in the tree at `9ddfdef` |
| Seam drive (Python → runner) | `SEAM-OK` |

## Mutants

Each mutant is described by what it removes, applied to the real source,
run, then restored and `cmp`-verified byte-identical.

1. **`build_state` narrowed back to the inner `directive` map** (the pre-fix
   shape). Reds exactly 2 — `test_state_task_carries_the_progress_a_script_reads`
   and `test_envelope_from_the_cache_carries_the_running_task`. The builder's
   "reds both snapshot tests" reproduces.
2. **`look.task` returns `{}` for `result`.** Reds exactly 1 —
   `a script reads where its GOTO arrived through look.task` (`# pass 20 # fail 1`).
   The builder's "reds only the arrival test" reproduces.
3. **`timeoutReason` drops the destination** (`"Timed out after %d ticks"`
   only). Reds exactly 1 — `a_timed_out_goto_names_the_destination_it_was_walking_to`,
   message: *"the timeout must name the destination, got: Timed out after 600 ticks"*.

## F-2 (minor, spec text only): `GotoBehavior.java:171` is now the vehicle branch

The amended requirement says:

> A distance-teleport (`GotoBehavior.java:171`, beyond `TELEPORT_THRESHOLD`)
> MUST use the same bounded, reported target.

At `9ddfdef`, `:171` is `progress.setPhase("driving (aboard)")` — the vehicle
steer. The teleport is at **`:175`** (`if (distance > TELEPORT_THRESHOLD)`).

This cite was **correct when written**: at parent `465b61e`, `:171` is
`if (distance > TELEPORT_THRESHOLD)`. `9ddfdef`'s own added comment lines
(`timeoutReason`, above the method) pushed the teleport down four lines, and
the spec text moved in the same commit without its cite moving with it.

Severity: none in behaviour — the sentence's substance (a far target is
teleported to the *bounded* `targetY`, since `start` sets `targetY` from the
lift result and only the vehicle/teleport paths read it) is true at `:175`.
But a spec that cites a line is meant to be checkable, and this one now points
at a different construct. Fix: `:175`.

## Line cites I resolved (this is where I get things wrong, so all of them)

At `9ddfdef`:

- `HttpApiServer.java:1338` → `BotManager.getServer().execute(() -> dirFuture.complete(bot.getBrain().toMap()))` — correct.
- `binding.js:324` → `return { ok: true, seq: entry.seq };` — correct.
- `agent.py:1410-1413` → the `result = prog.get("result") or {}` /
  `suffix = f" result={result}"` / `out = f"COMPLETED …"` block — correct; this
  is the planner consumer, distinct from the script's.
- `BotBrain.toMap` is at **:213-230**; the spec says `:212-229`. Off by one at
  both ends but names the right method. Not worth a finding; noted so a later
  sweep does not "correct" it to something wrong.
- `snapshot.py:125-146` and "the `events` field is NOT the carrier" — verified:
  `build_envelope` defaults `events=None`, and neither caller
  (`snapshot.py:196`, `script_tick.py:653`) passes it. `[]` every tick, as stated.
- `Directive.toMap` `id` is `long` from an `AtomicLong` starting at 1, which is
  what makes `look.js`'s `typeof dir.id === "number"` check sound rather than a
  silent `null`. Checked because `id` is the field the docs rely on to tell a
  stale completion from a fresh one.

## Notes, not findings

- **A timed-out GOTO still reports `describeState()` = "Moving to …"**, a
  string in the old comma format with no unit. `timeoutReason` now names the
  walked-to point properly, but the two messages describe the same run in two
  formats. Cosmetic; no consumer keys on the format (checked: `describeState`
  is used for the bot's own status display).
- **`arrived_at` has no server-free test of its own call site**, which the
  commit message states plainly. What exists is a test of `timeoutReason` as a
  pure function and a test of the emission shape at the `putResult` level. My
  seam drive closes the *reading* half with producer-shaped values; it does not
  prove `tick()` calls `putResult` when the player is within `arriveDistance`.
  This is the same "not established" the builder already declared, and I agree
  with the judgement that it is a server-free-test gap rather than a defect.

## Not established

**No live bot has been observed arriving and stopping.** The re-issue-forever
behaviour of trial 4.3 is addressed at the level of "the script can now read
the arrival"; no run here shows a script that reads it and then yields, and
nothing in either suite drives a script tick against a completing GOTO. That
remains the end-to-end confirmation this fix needs, and it needs a server.
