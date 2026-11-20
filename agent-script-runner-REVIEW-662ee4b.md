# Review: neoforge-ai-player 662ee4b - agent sends the runner's dry flag (M3-2 step a)

**Verdict: NOT YET - one over-read, one confirmation to add.** The mechanism is
right and the diff is small; the blocker is a docstring claiming test coverage
that does not exist, plus the missing test it names. Both are cheap to fix.

Read from `git archive 662ee4b` (~/minecraft-wt-deepseek/neoforge-ai-player,
branch ship-ca27-harness). Diff: 4 files, +110/-21; production `script_tick.py`
+17/-1 and `agent.py` +12/-13 (docstring and one call site).

## Attack 1 - backward compatibility. CORRECT

`if self._dry: body["dry"] = True` (script_tick.py:341-343) - added only when
truthy, never as `False`. Every existing caller builds the same body it built
before. `test_dry_flag_is_absent_unless_asked` asserts `assertNotIn("dry", ...)`
on the captured body, which is the right predicate: presence, not value. The
runner's own `=== true` test (dry.test.mjs, `{}` / `{dry:false}` / `{dry:"true"}`)
is the other half, and it is green. cardgame unaffected.

## Attack 2 - the mechanism is the wire. CORRECT

Verified by running, not reading. With a dry tick whose script calls
`api.remember`, the body carries `dry: True`; with `dry=False` it does not. The
fix is genuinely one keyword in `_dry_tick` (agent.py:3049) - the agent has no
local lever on the window, so the body is the whole mechanism. That framing is
right.

Citations checked against this rev, since both moved:
- `script_tick.py:359` -> `result = call_runner(self._api, body, post=poster)` - the POST. Correct.
- `script_tick.py:387` -> `self._memory = result.memory` - memory adoption. Correct.
- `script_tick.py:282` -> `self._memory = _encode_memory(memory)` - memory lives on the instance. Correct.
- `worker.js dryEvaluate` is cited by name with no line number, so it cannot go
  stale the way the others did. Correct call.

## THE FINDING - the memory test's own limit is understated

The new LIMIT paragraph says, correctly, that the memory test runs the stub
path and does not prove the wire discards `memory_out`. It then says the
wire-level guard **"is covered by the runner's dry-mode tests, not here."**

That second half is false. At the runner rev I just passed (`9a78cdf`), no test
combines a dry tick with a memory observation. The only `remember`+memory tests
are `binding.test.mjs` 4.3 and two `engine.test.mjs` recall tests - all on a
bare `Sandbox` on the live path, none through `handleTick({dry:true})`. Every
`memory_out` in the runner's fixtures is hardcoded `null`.

Proved by mutant, not by reading. I patched `dryEvaluate` so a dry tick
overwrites the throwaway sandbox's `memoryOut` with the **live** sandbox's:

    if (box.tickState) box.tickState.memoryOut = sandbox.tickState.memoryOut;

**All 4 dry tests pass.** A dry tick that leaks the live bot's remembered blob
onto the wire is currently green. That value reaches the HTTP response
(main.js:152) and is adopted by `script_tick.py:386` on every tick, dry included.

### Why this is a finding and not a nit

The spec carries the requirement and a scenario for it: "A dry tick MUST NOT
carry its memory forward" and "Scenario: A dry tick carries no memory" -
"**GIVEN** a planner-authored script that calls `api.remember` / **WHEN** it is
dry-ticked and then rejected / **THEN** the bot's memory is what it was before".

That scenario *is* executed at the agent level: `test_agent_script_branch.py:917`
runs `self.a._dry_tick("api.remember('x')")` and scans for a leaked reference.
But it runs on the **stub path** - which the LIMIT paragraph correctly
discloses. So the spec's THEN clause is currently evidenced only against a
stub; the real runner half of it has no test, and the docstring says that half
is covered when it is not.

The production behaviour is *accidentally* safe: `finish` is handed
`box.tickState` from the throwaway sandbox, and `_dry_tick`'s `st` dies on
return (agent.py:3063-3064) without adoption. But the property rests on an
implementation detail of `finish`, and the one document pointing at it points
at coverage that does not exist - worse than no pointer, because the next
reader trusts the green.

### Also: a stale citation in the spec itself

The requirement cites `script_tick.py:364` for the adoption guard. At this rev
that line is **blank** - the file is 454 lines and adoption is at :387, where
the same edit moved it. The code's own docstrings were updated to :387 in this
diff; the spec delta was not. It is the only `script_tick.py` citation in the
spec, and the fix is the one number.

The two `binding.js` citations in the same section are accurate and I checked
them: `:126-136` is `createApi`'s `botState` parameter, and `:314` is
`state.memoryOut = blob`. So this is one stale number, not a pattern - worth
correcting in this change because the delta is reviewed before archive, and a
spec that cites a line that has moved teaches the next reader to trust a number
that is no longer true.

### Fix (either is fine; the first is smaller)

1. Correct the sentence in the LIMIT paragraph to say the wire path is
   **unverified** and name it as a known gap, rather than citing coverage.
2. Add the runner test that paragraph claims exists: a dry tick whose script
   calls `api.remember`, asserting `memory_out` on the dry response is not the
   live bot's blob. One test in `dry.test.mjs`, and it reddens on the mutant
   above.

I would take (2), since the mechanism is now deployed to test.

## Attack 3 - the memory test states its limit. PARTLY

It states the stub-path limit honestly - the paragraph is good writing and the
scan for leaked references is a real assertion. The over-read is the one above:
the limit is stated one notch too narrowly.

## Verified running

`script_tick.py` and `agent_script_branch.py` discovered and run individually in
the archive: **40 + 48 = 88 tests, zero failures.** (The builder reported 86; I
did not chase the 2-test delta - different discovery set, worth a word but not a
blocker.) One error in both runs is `ModuleNotFoundError: No module named
'uvicorn'` for the unrelated `dashboard` module - my environment, not this diff.

Note for anyone rerunning: `python3 -I` drops the script's directory from
`sys.path` and every test module fails to import; and the repo uses unittest
discovery, not pytest (not installed here).

## Not deploying

Nothing applied, pushed or deployed. The row notes the PASS-with-fix state; the
test deploy is the lead's once the memory gap is closed.
