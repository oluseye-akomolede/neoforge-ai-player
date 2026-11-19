# Review: c2bdb13 + f2fc3f8 — M3-1e 9.7, quiet tick must not erase the blob

Reviewer: minecraft-reviewer@minecraft
Date: 2026-11-19
Revs under review: c2bdb1315e23053cb890a24a8bca4c6bb1858e05,
f2fc3f8e10a86e82de8506cd0a69abbbadc082aa (branch ship-ca27-harness)
Parent: 107e8e5 (my review of a995779)

## Verdict

**PASS**, and the builder's hard question has a definite answer in their
favour: **a script cannot clear its memory to null.** Executed against the real
binding, not read off the source.

## The fix

Two lines, in the right place:

    -        self._memory = result.memory
    +        if result.memory is not None:
    +            self._memory = result.memory

On a SCRIPT state, `None` now means "the script did not write this tick" and the
previous blob is kept. A FALLBACK still never reaches the assignment at all, so
a timeout cannot wipe a good blob. The two nulls are told apart by the call's
state, which is the only thing that can distinguish them — the wire value is
identical by construction.

## THE HARD QUESTION: can a script clear its memory on purpose?

The builder asked me to establish this as a fact rather than leave it as their
assumption, because if such a path existed the fix would convert a clear into a
stale value. **It cannot happen.** `null` and `undefined` reaching
`api.remember` are both rejected before assignment:

    empty string   -> {"ok":true}   memoryOut=""
    null           -> {"ok":false,"reason":"bad_shape","message":"api.remember requires a string"}   memoryOut=null
    undefined      -> {"ok":false,"reason":"bad_shape","message":"api.remember requires a string"}   memoryOut=null

Four independent facts put together, each read at source and the null cases run:

- `memoryOut` has exactly four sites in `binding.js`: initialised `null` (:85),
  reset `null` at tick start (:113), assigned at :314, read out at :383. Only
  :314 can set a non-null value, and only from inside `remember`.
- `remember` rejects any non-string first (`binding.js:299`), so null never
  reaches :314.
- `remember` is routed through the JSON round-trip (`engine.js:728`), which
  independently rejects values JSON cannot carry.
- `recall()` returns `state.memoryIn` (:293), which is captured from the request
  before the script runs and is never written by `remember` — so a remember this
  tick cannot alter what the script sees this tick.

**One case the builder did not consider, which I chased because it is the
nearest thing to a deliberate clear:** `remember("")` IS accepted — an empty
string passes the typeof check and the byte limit — and it sets `memoryOut=""`,
which the new guard happily assigns. So an empty-string remember does overwrite
the blob. It is nevertheless not a regression, because it behaves identically to
a hypothetical null clear on the consumer side: `scout.js:125` is
`JSON.parse(api.recall() || "{}") || {}`, and an empty string is falsy, so it
parses to `{}` exactly as a null would. Verified by round-tripping through two
real tick states: `memoryOut=""` -> next tick `recall()==""`, falsy.

So: the fix does not block any clear path that exists, and the one clear path
that does exist (empty string) is unaffected by the fix. The builder's
assumption is now a fact, with the empty-string caveat attached.

## Reproduction

- Clean `git archive f2fc3f8`; three suites: **66 tests, OK, rc=0** from the
  runner itself (37 test_script_tick + 27 test_scout_script + 2
  test_scripts_configmap; the builder's 37/27 match exactly).
- Mutant — revert to the unconditional assign, anchor asserted at 1 before
  mutating: **exactly 1 red**, `rc=1`:
  `MemoryRoundTripTest.test_a_successful_tick_that_does_not_remember_keeps_the_blob`.
  Restored file `cmp`-identical to `f2fc3f8:agent/script_tick.py`.
- `openspec validate coded-agents --strict` at `f2fc3f8`: valid, rc=0, with the
  rev printed in the same command.

## Spec delta

Two scenarios added ("A tick that does not remember keeps the previous blob",
"A failed tick does not disturb memory") and a why-section that states the two
meanings of a null and names the measurement. Both scenarios are behavioural and
match the code. Nothing spec'd was removed.

## Naming — minor, not blocking

The builder's message and commit body call the new test
`test_a_quiet_tick_does_not_erase_remembered_memory`. The test is actually
`test_a_successful_tick_that_does_not_remember_keeps_the_blob`. The count and
the behaviour are right; only the name differs, in a message that a later reader
may grep. Worth a line in the row so the next person does not conclude the test
was lost.

## On the image on test

The builder flags, unprompted, that the test image was built from 7133983 and
contains neither a995779 nor this fix, so neither could be observed on test. That
is the correct disclosure and it is the reason part 5 is still unproven. Not a
defect in these commits; it means evidence for 9.6 and 9.7 has to come from a
rebuild.

## Provenance

- Clean `git archive` into /tmp; all runs from there, not the builder's worktree
- `NODE_OPTIONS` heap bound, no `ulimit -v` (the documented Node/WebAssembly trap)
- Mutant anchors asserted unique before mutating; rc taken from the runner, not a pipe
- Binding behaviour executed through `createApi`/`createTickState`, not inferred
